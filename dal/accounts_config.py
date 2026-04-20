"""dal/accounts_config.py — Accessor for the gitignored accounts.yaml.

Single source of truth for per-account identifiers. Connectors, migrations,
and scripts call the helpers here instead of hard-coding
`{institution}_{last4}` literals in source — keeping real last-4 digits
out of tracked files.

Post P0-SEC Track B: `get_account_id()` returns the opaque `id:` field
written into `accounts.yaml` (generated once via
`scripts/init_accounts_yaml.py`). That id is **not derived from last4**,
so the historical `{institution}_{last4}` coupling is gone at the
identifier layer. `last4` remains gitignored as a display-only attribute
surfaced by `get_last4()` for UI reconciliation.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

log = logging.getLogger("sentry.dal.accounts_config")

BASE_DIR = Path(__file__).resolve().parent.parent
ACCOUNTS_YAML = BASE_DIR / "accounts.yaml"


@lru_cache(maxsize=1)
def _load() -> dict:
    if not ACCOUNTS_YAML.exists():
        log.warning("accounts.yaml not present at %s", ACCOUNTS_YAML)
        return {}
    import yaml
    with open(ACCOUNTS_YAML, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def reload_config() -> None:
    """Drop the cached copy so the next call re-reads the file."""
    _load.cache_clear()


def _find_account(institution: str, *, name_contains: Optional[str] = None,
                  account_type: Optional[str] = None) -> Optional[dict]:
    """Return the first account entry matching the filters, or None."""
    data = _load()
    accounts = data.get(institution)
    if not isinstance(accounts, list):
        return None
    for acct in accounts:
        if not isinstance(acct, dict):
            continue
        if name_contains is not None:
            name = str(acct.get("name", "")).lower()
            if name_contains.lower() not in name:
                continue
        if account_type is not None and acct.get("type") != account_type:
            continue
        return acct
    return None


def get_last4(institution: str, *, name_contains: Optional[str] = None,
              account_type: Optional[str] = None) -> Optional[str]:
    """Return the last4 string for an account, or None if not configured.

    Raises nothing on miss — callers decide whether to raise or fall back.
    """
    acct = _find_account(
        institution, name_contains=name_contains, account_type=account_type
    )
    if acct is None:
        return None
    return str(acct.get("last4", "")).strip() or None


def get_account_id(institution: str, *, name_contains: Optional[str] = None,
                   account_type: Optional[str] = None) -> Optional[str]:
    """Return the opaque `id:` for the account, or None if not configured.

    Post P0-SEC Track B the `id:` field in accounts.yaml is authoritative.
    Run ``python scripts/init_accounts_yaml.py`` after adding an account
    entry to generate the opaque id (or ``--force`` to regenerate —
    destructive for existing DB FKs).
    """
    acct = _find_account(
        institution, name_contains=name_contains, account_type=account_type
    )
    if acct is None:
        return None
    raw = acct.get("id")
    if raw is None:
        return None
    return str(raw).strip() or None


def all_account_ids(institution: Optional[str] = None) -> list[str]:
    """Return every configured `id:` for the institution (or all)."""
    data = _load()
    out: list[str] = []
    for inst, accounts in data.items():
        if institution is not None and inst != institution:
            continue
        if not isinstance(accounts, list):
            continue
        for acct in accounts:
            if not isinstance(acct, dict):
                continue
            raw = acct.get("id")
            if raw is None:
                continue
            acct_id = str(raw).strip()
            if acct_id:
                out.append(acct_id)
    return out
