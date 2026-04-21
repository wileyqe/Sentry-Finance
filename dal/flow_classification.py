"""
dal/flow_classification.py — Phase 14 Phase B terminal-bucket classifier.

Single home for the rules that classify a flow edge in the Sankey into one of
five bucket labels. Imported by ``dal.reports.get_flow_data`` and consumed in
tests to lock the invariant that every dollar in the period lands in exactly
one of the three drawn buckets (CONSUMED / STORED_LIQUID / STORED_ILLIQUID).

Phase B does NOT draw the ``GROWN`` bucket — market-value moves on already-owned
positions are net-worth math, not cash flow. Phase D's reconciliation identity
folds them back in.

Rule sets are frozensets at module top with comments citing the source
(migration or category file). When a new category ships, this is the one file
that knows about it.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from enum import Enum
from typing import Optional

from dal.category_classifications import (
    TRANSFER_CATEGORIES,
    LOAN_CATEGORIES,
    EXCLUDED_FROM_SPEND,
)

log = logging.getLogger("sentry.dal.flow_classification")


# ── Bucket labels ────────────────────────────────────────────────────────────


class BucketLabel(str, Enum):
    """Terminal fate of a dollar in the Sankey period."""

    CONSUMED = "CONSUMED"              # spent — gone
    STORED_LIQUID = "STORED_LIQUID"    # checking / HYSA / brokerage cash
    STORED_ILLIQUID = "STORED_ILLIQUID"  # retirement / HSA / principal / securities
    GROWN = "GROWN"                    # reserved; not drawn in Phase B
    ROUTING = "ROUTING"                # intermediate hub / pass-through nodes


# ── Peer-account-type classifications ────────────────────────────────────────
#
# Source: `accounts.type` values emitted across the DAL and seeders.
# See dal/debt.py (loan/credit_card/bnpl), dal/investments.py
# (investment/retirement), dal/derived.py (liability_types set).

# Peer types that parks cash as liquid savings.
_LIQUID_PEER_TYPES: frozenset[str] = frozenset({
    "checking",
    "savings",
    "money_market",
})

# Peer types that always classify as illiquid regardless of same-window buy match.
# Retirement includes 401k/403b/IRA/TSP; HSA is its own bucket-wise illiquid
# (even though balance can sit as cash, the tax-barrier makes it illiquid for
# flow-accounting purposes in Phase B).
_ILLIQUID_PEER_TYPES: frozenset[str] = frozenset({
    "retirement",
    "hsa",
})


# ── Categorical transfers (non-peer-resolvable) ───────────────────────────────
#
# Source: dal/category_classifications.py.
# Credit-card payments and loan payments are neither consumption nor savings —
# they are liability-balance reductions. Phase B treats CC pay-downs as
# CONSUMED (cash leaves the household), and loan payments are handled by the
# mortgage-decomposition path (principal → illiquid, interest/escrow → spent)
# before this classifier sees them. If a loan payment slips through
# uncomposed, default to CONSUMED as a fail-safe (fail-loud via log).

_DEBT_SERVICE_CATEGORIES: frozenset[str] = (
    LOAN_CATEGORIES | frozenset({"Credit Card Payments"})
)


# ── Classifier API ───────────────────────────────────────────────────────────


def classify(
    category: Optional[str],
    account_type: Optional[str],
    transfer_peer_account_type: Optional[str] = None,
    brokerage_buy_matched: bool = False,
    is_transfer: bool = False,
    is_credit: bool = False,
) -> BucketLabel:
    """Return the terminal bucket for a flow edge given its context.

    Parameters
    ----------
    category : str | None
        The transaction's category (e.g. "Groceries", "Transfers", "Mortgage").
    account_type : str | None
        The ``accounts.type`` of the transaction's own account. Informational;
        most rules key off ``transfer_peer_account_type`` when a transfer exists.
    transfer_peer_account_type : str | None
        For a transfer (``transfer_tag IS NOT NULL``), the peer leg's
        ``accounts.type``. None when no peer resolved — classifier logs a
        warning and falls back to CONSUMED.
    brokerage_buy_matched : bool
        For a transfer with a brokerage-type peer, whether a matching
        ``positions_ledger`` row with ``share_delta > 0`` exists within the
        same window. True → STORED_ILLIQUID, False → STORED_LIQUID (cash
        sitting in brokerage).
    is_transfer : bool
        Convenience flag — True when the transaction has a transfer_tag.
        Equivalent to ``transfer_peer_account_type`` being non-None, but
        callers sometimes resolve the tag without resolving the peer.
    is_credit : bool
        Sign of the transaction (signed_amount > 0). Income flows should NOT
        call this classifier — their buckets are decided by the income-source
        registry. This flag exists to log-warn if a credit sneaks in.

    Returns
    -------
    BucketLabel
        One of CONSUMED / STORED_LIQUID / STORED_ILLIQUID. GROWN and ROUTING
        are never returned by this function.
    """
    if is_credit and not is_transfer:
        log.warning(
            "flow_classification.classify called on a non-transfer credit "
            "(category=%r account_type=%r). Income flows should use the "
            "income-source registry. Defaulting to CONSUMED.",
            category,
            account_type,
        )
        return BucketLabel.CONSUMED

    # Transfer path — peer's account type decides.
    if is_transfer or transfer_peer_account_type is not None:
        peer = (transfer_peer_account_type or "").strip().lower()

        if not peer:
            log.warning(
                "flow_classification.classify: transfer with no resolved peer "
                "(category=%r account_type=%r). Falling back to CONSUMED.",
                category,
                account_type,
            )
            return BucketLabel.CONSUMED

        if peer in _ILLIQUID_PEER_TYPES:
            return BucketLabel.STORED_ILLIQUID

        if peer in _LIQUID_PEER_TYPES:
            return BucketLabel.STORED_LIQUID

        if peer in ("investment", "brokerage"):
            return (
                BucketLabel.STORED_ILLIQUID
                if brokerage_buy_matched
                else BucketLabel.STORED_LIQUID
            )

        # Liability peers: credit card / loan / bnpl. Moving cash to a
        # liability pays down a balance — CONSUMED (cash leaves the
        # household). Principal is accounted for via loan_payment_splits,
        # not here.
        if peer in ("credit_card", "loan", "bnpl", "mortgage"):
            return BucketLabel.CONSUMED

        log.warning(
            "flow_classification.classify: unknown peer account_type=%r. "
            "Falling back to CONSUMED.",
            peer,
        )
        return BucketLabel.CONSUMED

    # Non-transfer debit path — category decides.
    cat = (category or "").strip()

    # Loan/CC payments that slipped past decomposition are CONSUMED; caller
    # should have split them. Log-warn so the fail is loud.
    if cat in _DEBT_SERVICE_CATEGORIES:
        log.debug(
            "flow_classification.classify: debt-service category %r without "
            "a decomposition. Treating as CONSUMED (cash leaves household).",
            cat,
        )
        return BucketLabel.CONSUMED

    # Categorical transfers without a resolved peer — fail-safe to CONSUMED
    # with a warning so we notice broken reconciliation.
    if cat in TRANSFER_CATEGORIES:
        log.warning(
            "flow_classification.classify: transfer category %r with no "
            "transfer_tag resolution. Falling back to CONSUMED.",
            cat,
        )
        return BucketLabel.CONSUMED

    # Everything else is real spending.
    if cat in EXCLUDED_FROM_SPEND:
        # Refunds-adjustments etc — not spending, but not savings either.
        # Default to CONSUMED; they offset spending rather than accumulating.
        return BucketLabel.CONSUMED

    return BucketLabel.CONSUMED


# ── Brokerage-buy match helper ───────────────────────────────────────────────


def brokerage_buy_matches_transfer(
    conn: sqlite3.Connection,
    account_id: str,
    posting_date: str,
    window_days: int = 5,
) -> bool:
    """Return True when a ``positions_ledger`` row exists for the account
    with ``share_delta > 0`` within ``window_days`` business days of the
    given posting date.

    Used to decide whether a transfer into a brokerage account classifies as
    STORED_LIQUID (cash still sitting) or STORED_ILLIQUID (a buy consumed it).
    Business-day windowing is approximated as calendar days ± the window —
    good enough for Phase B; Phase D may sharpen if miscounts appear.

    Parameters
    ----------
    conn : sqlite3.Connection
    account_id : str
        Opaque account id (matches ``positions_ledger.account_id``).
    posting_date : str
        ISO date (``YYYY-MM-DD``) of the transfer leg.
    window_days : int
        Forward-looking window in calendar days. Default 5 (≈ one business
        week). The ledger row must be ``>= posting_date`` (a buy settles on
        or after the cash transfer; older buys belong to a prior period).
    """
    if not account_id or not posting_date:
        return False

    row = conn.execute(
        """
        SELECT 1
        FROM positions_ledger
        WHERE account_id = ?
          AND share_delta > 0
          AND date(timestamp) >= date(?)
          AND date(timestamp) <= date(?, ?)
        LIMIT 1
        """,
        (account_id, posting_date, posting_date, f"+{int(window_days)} days"),
    ).fetchone()
    return row is not None


# ── Income-source match-rule helpers ─────────────────────────────────────────


def match_rule_matches(
    rule_json: str,
    *,
    counterparty: Optional[str] = None,
    category: Optional[str] = None,
    owner_id: Optional[str] = None,
) -> bool:
    """Return True when the given transaction context matches the stored
    match-rule blob from ``income_sources.match_rule_json``.

    The blob is opaque at the schema level. Shape in Phase B:

        {
            "counterparty_substring": "...",   # optional, case-insensitive
            "category":               "...",   # optional, exact match
            "owner_id":               "..."    # optional, exact match
        }

    At least one of ``counterparty_substring`` or ``category`` MUST be present
    — a zero-key blob would match every transaction and is rejected as
    malformed (log-warn, return False).
    """
    try:
        rule = json.loads(rule_json) if rule_json else {}
    except (TypeError, ValueError):
        log.warning("income_sources.match_rule_json is not valid JSON: %r", rule_json)
        return False

    if not isinstance(rule, dict):
        return False

    counter_sub = rule.get("counterparty_substring")
    cat_rule = rule.get("category")
    owner_rule = rule.get("owner_id")

    if not counter_sub and not cat_rule:
        log.warning(
            "income_sources match_rule has neither counterparty_substring nor "
            "category — would match every transaction. Skipping."
        )
        return False

    if counter_sub:
        hay = (counterparty or "").lower()
        if counter_sub.lower() not in hay:
            return False

    if cat_rule and cat_rule != (category or ""):
        return False

    if owner_rule and owner_rule != (owner_id or ""):
        return False

    return True
