"""dal/accounts_config.py — Accessor for the gitignored accounts.yaml.

Single source of truth for per-account identifiers. Connectors, migrations,
and scripts call the helpers here instead of hard-coding
`{institution}_{last4}` literals in source — keeping real last-4 digits
out of tracked files.

This is the compatibility layer for the P0-SEC identifier refactor.
A future migration (v31+) is expected to replace `{institution}_{last4}`
with `{institution}_{uuid4}`; when that lands, `get_account_id()` becomes
the single choke point that needs to return the new opaque id instead of
re-deriving from last4.
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
    """Return the canonical account_id for the account, or None.

    Today this returns ``f"{institution}_{last4}"`` to match the current
    schema. When the v31 identifier refactor lands, this helper is the
    single place that flips to the new opaque id.
    """
    last4 = get_last4(
        institution, name_contains=name_contains, account_type=account_type
    )
    if not last4:
        return None
    return f"{institution}_{last4}"


def all_account_ids(institution: Optional[str] = None) -> list[str]:
    """Return every account_id for the institution (or every institution)."""
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
            last4 = str(acct.get("last4", "")).strip()
            if not last4:
                continue
            out.append(f"{inst}_{last4}")
    return out
