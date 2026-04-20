"""scripts/init_accounts_yaml.py — Generate opaque `id:` fields in accounts.yaml.

The P0-SEC Track B refactor moved away from `{institution}_{last4}` as the
`accounts.id` primary key. Every account entry in the gitignored
`accounts.yaml` now carries an opaque `id:` field; `dal.accounts_config.
get_account_id()` returns that field directly.

This one-shot helper scans the working `accounts.yaml` and appends an
`id:` to any entry missing one. Existing ids are left alone so re-running
the script is idempotent.

Usage:
    python scripts/init_accounts_yaml.py             # add missing ids
    python scripts/init_accounts_yaml.py --dry-run   # print changes, don't write
    python scripts/init_accounts_yaml.py --force     # regenerate EVERY id

New ids use `{institution}_{8-hex}` with the hex sourced from uuid4 —
opaque, unique, and not derivable from the last-4 digits.
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
ACCOUNTS_YAML = BASE_DIR / "accounts.yaml"


def _new_id(institution: str) -> str:
    return f"{institution}_{uuid.uuid4().hex[:8]}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="regenerate id: for every account (destructive for DB FKs)")
    args = ap.parse_args()

    if not ACCOUNTS_YAML.exists():
        print(f"error: {ACCOUNTS_YAML} not found. Copy accounts.yaml.example first.",
              file=sys.stderr)
        return 1

    with open(ACCOUNTS_YAML, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    added = 0
    changed = 0
    for institution, accounts in list(data.items()):
        if not isinstance(accounts, list):
            continue
        for acct in accounts:
            if not isinstance(acct, dict):
                continue
            existing = acct.get("id")
            if existing and not args.force:
                continue
            new_id = _new_id(institution)
            if existing:
                changed += 1
                print(f"  {institution}/{acct.get('name')}: {existing} -> {new_id}")
            else:
                added += 1
                print(f"  {institution}/{acct.get('name')}: + {new_id}")
            acct["id"] = new_id

    if added == 0 and changed == 0:
        print("accounts.yaml already has id: on every account — nothing to do.")
        return 0

    if args.dry_run:
        print(f"\n[dry-run] would add {added} id(s), regenerate {changed}.")
        return 0

    with open(ACCOUNTS_YAML, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)

    print(f"\nWrote {ACCOUNTS_YAML}: added {added} id(s), regenerated {changed}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
