"""
v31: Opaque account_id refactor (P0-SEC Track B).

Replaces `{institution}_{last4}` as `accounts.id` with the opaque `id:`
field sourced from gitignored `accounts.yaml`. Real last-4 digits no
longer flow into identifiers, closing the last residual PII leak vector
at the DB layer (the git history scrub is handled separately via
`git filter-repo --replace-text`).

Mechanically this is a data-only migration — `accounts.id` is already
TEXT, so no schema change is required. The migration:

  1. Reads every account row from the DB.
  2. For each row, looks up the target opaque id from accounts.yaml by
     matching on (institution_id, last4, type). If a match is missing
     the migration raises with actionable guidance (run
     `scripts/init_accounts_yaml.py` first).
  3. With FKs disabled, rewrites every dependent table — 12 FK columns
     across 11 tables, plus the TSP account literal embedded in
     document_drops.summary_json blobs.
  4. Rewrites accounts.id last.
  5. Re-enables FKs and runs `PRAGMA foreign_key_check` to assert
     integrity before commit.

A fresh DB (zero account rows) no-ops.  An already-migrated DB no-ops
when every old_id equals new_id.
"""
from __future__ import annotations

import json
import logging

VERSION = 31

log = logging.getLogger("sentry.migrations.v31")


# Tables holding account-id references. Order is not sensitive since
# all writes happen under a single transaction with FKs disabled.
_FK_TABLES: list[tuple[str, str]] = [
    ("transactions", "account_id"),
    ("balance_snapshots", "account_id"),
    ("loan_details", "account_id"),
    ("portfolio_snapshots", "account_id"),
    ("positions_ledger", "account_id"),
    ("investment_holdings", "account_id"),
    ("real_estate", "linked_loan_id"),
    ("recurring_transactions", "account_id"),
    ("recurring_transactions", "linked_account_id"),
    ("savings_goals", "linked_account_id"),
    ("tax_buckets", "account_id"),
    ("apy_history", "account_id"),
]


def _build_yaml_index(yaml_data: dict) -> dict[tuple[str, str, str], str]:
    """Map (institution, last4, type) → new opaque id from accounts.yaml."""
    idx: dict[tuple[str, str, str], str] = {}
    for institution, entries in yaml_data.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            new_id = entry.get("id")
            if not new_id:
                continue
            key = (
                str(institution),
                str(entry.get("last4", "")).strip(),
                str(entry.get("type", "")).strip(),
            )
            idx[key] = str(new_id)
    return idx


def _rewrite_document_drops_json(cur, mapping: dict[str, str]) -> int:
    """Rewrite any old account-id literals embedded in summary_json blobs."""
    try:
        cur.execute("SELECT id, summary_json FROM document_drops")
    except Exception:
        return 0
    touched = 0
    for row_id, raw in cur.fetchall():
        if not raw:
            continue
        try:
            blob = json.loads(raw)
        except (TypeError, ValueError):
            continue
        changed = False
        if isinstance(blob, dict):
            acct = blob.get("account")
            if isinstance(acct, str) and acct in mapping:
                blob["account"] = mapping[acct]
                changed = True
        if changed:
            cur.execute(
                "UPDATE document_drops SET summary_json = ? WHERE id = ?",
                (json.dumps(blob), row_id),
            )
            touched += 1
    return touched


def run(conn):
    from dal.accounts_config import reload_config, _load  # noqa: WPS437

    reload_config()
    yaml_data = _load()
    yaml_index = _build_yaml_index(yaml_data)

    cur = conn.cursor()
    cur.execute("SELECT id, institution_id, last4, type FROM accounts")
    rows = cur.fetchall()

    if not rows:
        return  # fresh DB: seeder uses opaque ids directly

    mapping: dict[str, str] = {}
    missing: list[tuple[str, str, str, str]] = []
    for old_id, institution, last4, type_ in rows:
        key = (str(institution), str(last4 or "").strip(), str(type_ or "").strip())
        new_id = yaml_index.get(key)
        if new_id is None:
            missing.append((old_id, *key))
            continue
        if new_id != old_id:
            mapping[old_id] = new_id

    if missing:
        lines = [f"  old_id={o!r} institution={i!r} last4={l4!r} type={t!r}"
                 for (o, i, l4, t) in missing]
        raise RuntimeError(
            "v31 migration: accounts.yaml has no matching id: for these DB rows:\n"
            + "\n".join(lines)
            + "\n\nRun `python scripts/init_accounts_yaml.py` to generate ids, "
            "then re-run the migration."
        )

    if not mapping:
        return  # every old_id already equals its new_id

    cur.execute("PRAGMA foreign_keys = OFF")
    try:
        for table, col in _FK_TABLES:
            for old_id, new_id in mapping.items():
                cur.execute(
                    f"UPDATE {table} SET {col} = ? WHERE {col} = ?",
                    (new_id, old_id),
                )

        _rewrite_document_drops_json(cur, mapping)

        for old_id, new_id in mapping.items():
            cur.execute(
                "UPDATE accounts SET id = ? WHERE id = ?",
                (new_id, old_id),
            )

        cur.execute("PRAGMA foreign_key_check")
        violations = cur.fetchall()
        if violations:
            raise RuntimeError(f"v31: FK violations post-rewrite: {violations}")

        log.info("v31: rewrote %d account_id(s) across %d FK column(s)",
                 len(mapping), len(_FK_TABLES))
    finally:
        cur.execute("PRAGMA foreign_keys = ON")

    conn.commit()
