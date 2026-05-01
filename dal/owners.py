"""
dal/owners.py — Ownership management for multi-user dashboard views.

Supports the Yours / Ours / Mine dashboard toggle by partitioning
accounts by owner.  NULL owner_id is treated as "ours" (visible in
all views).

Views:
  ours   → all active accounts (default)
  mine   → owner_id = primary_owner OR owner_id IS NULL
  theirs → owner_id != primary_owner AND owner_id IS NOT NULL
"""

import logging
import os
import sqlite3
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger("sentry.dal.owners")


def redact_account_id_for_logs(account_id: str | None) -> str:
    # account_id is ``{institution_id}_{last4}`` where last4 comes from
    # live web scraping; log/SSE output must not persist real card digits.
    if not account_id:
        return "<unknown>"
    if "_" not in account_id:
        return account_id
    institution, _sep, _last4 = account_id.rpartition("_")
    return f"{institution}_****"


BASE_DIR = Path(__file__).resolve().parent.parent
_CONFIG_PATH = BASE_DIR / "config" / "owner_config.yaml"
_OWNERSHIP_OVERRIDES_ENV = "SENTRY_ACCOUNT_OWNERSHIP_PATH"
_OWNERSHIP_OVERRIDES_PATH = BASE_DIR / "config" / "account_ownership.local.yaml"

# ── Config Loading ───────────────────────────────────────────────────────────

_config_cache: Optional[dict] = None


def _load_config() -> dict:
    """Load and cache owner_config.yaml."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    if not _CONFIG_PATH.exists():
        log.warning("owner_config.yaml not found — ownership features disabled")
        _config_cache = {"primary_owner": None, "owners": []}
        return _config_cache

    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        _config_cache = yaml.safe_load(f) or {}
    return _config_cache


def get_primary_owner() -> Optional[str]:
    """Return the primary owner ID from config."""
    return _load_config().get("primary_owner")


def get_configured_owners() -> list[dict]:
    """Return the list of configured owners from owner_config.yaml."""
    return _load_config().get("owners", [])


# ── Durable Account Ownership Overrides ─────────────────────────────────────


def account_ownership_overrides_path(path: Path | str | None = None) -> Path:
    """Return the gitignored local rebuild-authority path for owner edits."""
    if path is not None:
        return Path(path)
    configured = os.environ.get(_OWNERSHIP_OVERRIDES_ENV)
    if configured:
        return Path(configured)
    return _OWNERSHIP_OVERRIDES_PATH


def _normalize_owner_id(owner_id: Optional[str]) -> Optional[str]:
    if owner_id is None:
        return None
    cleaned = str(owner_id).strip()
    if cleaned.lower() in {"", "null", "none", "shared", "household", "ours"}:
        return None
    return cleaned.lower()


def _canonical_owner_id(
    conn: sqlite3.Connection, owner_id: Optional[str]
) -> Optional[str]:
    normalized = _normalize_owner_id(owner_id)
    if normalized is None:
        return None

    row = conn.execute(
        "SELECT id FROM owners WHERE LOWER(id) = LOWER(?)",
        (normalized,),
    ).fetchone()
    if not row:
        raise ValueError(f"Owner {normalized!r} not found")
    return row["id"]


def load_account_ownership_overrides(
    path: Path | str | None = None,
) -> dict[str, Optional[str]]:
    """Load local account-owner rebuild overrides.

    The file is intentionally gitignored because account ids can come from
    real local account configuration. Shape:

    ``version: 1``
    ``account_owners: {account_id: owner_id_or_null}``
    """
    override_path = account_ownership_overrides_path(path)
    if not override_path.exists():
        return {}

    with open(override_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    raw = data.get("account_owners", {})
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("account_owners must be a mapping")

    out: dict[str, Optional[str]] = {}
    for account_id, owner_id in raw.items():
        cleaned_account_id = str(account_id).strip()
        if not cleaned_account_id:
            raise ValueError("account_owners contains an empty account id")
        out[cleaned_account_id] = _normalize_owner_id(owner_id)
    return out


def _write_account_ownership_overrides(
    overrides: dict[str, Optional[str]],
    path: Path | str | None = None,
) -> None:
    override_path = account_ownership_overrides_path(path)
    override_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "account_owners": {
            account_id: owner_id
            for account_id, owner_id in sorted(overrides.items())
        },
    }
    tmp_path = override_path.with_name(f"{override_path.name}.tmp")
    tmp_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    tmp_path.replace(override_path)


def record_account_ownership_override(
    account_id: str,
    owner_id: Optional[str],
    path: Path | str | None = None,
) -> None:
    """Persist one account-owner assignment to the local rebuild file."""
    cleaned_account_id = str(account_id).strip()
    if not cleaned_account_id:
        raise ValueError("account_id is required")

    normalized_owner_id = _normalize_owner_id(owner_id)
    overrides = load_account_ownership_overrides(path)
    overrides[cleaned_account_id] = normalized_owner_id
    _write_account_ownership_overrides(overrides, path)
    log.info(
        "Persisted ownership override for account %s -> owner %s",
        redact_account_id_for_logs(cleaned_account_id),
        normalized_owner_id or "(shared)",
    )


def apply_account_ownership_overrides(
    conn: sqlite3.Connection,
    path: Path | str | None = None,
) -> dict[str, int]:
    """Apply gitignored local ownership overrides to existing accounts.

    Missing accounts are skipped because accounts.yaml may have changed.
    Unknown owners raise ValueError so rebuilds cannot silently land on
    an ambiguous ownership state.
    """
    overrides = load_account_ownership_overrides(path)
    stats = {"loaded": len(overrides), "applied": 0, "missing_accounts": 0}
    for account_id, owner_id in sorted(overrides.items()):
        row = conn.execute("SELECT id FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if not row:
            stats["missing_accounts"] += 1
            log.warning(
                "Skipping ownership override for missing account %s",
                redact_account_id_for_logs(account_id),
            )
            continue
        assign_account_owner(conn, account_id, owner_id)
        stats["applied"] += 1
    return stats


# ── CRUD Operations ─────────────────────────────────────────────────────────


def create_owner(conn: sqlite3.Connection, owner_id: str, display_name: str) -> None:
    """Insert a new owner record (idempotent via INSERT OR IGNORE)."""
    conn.execute(
        """
        INSERT OR IGNORE INTO owners (id, display_name)
        VALUES (?, ?)
    """,
        (owner_id, display_name),
    )
    log.debug("Created owner: %s (%s)", owner_id, display_name)


def list_owners(conn: sqlite3.Connection) -> list[dict]:
    """Return all owner records."""
    rows = conn.execute(
        "SELECT id, display_name, created_at FROM owners ORDER BY display_name"
    ).fetchall()
    return [dict(r) for r in rows]


def update_owner(
    conn: sqlite3.Connection,
    owner_id: str,
    *,
    display_name: Optional[str] = None,
) -> None:
    """Update mutable fields on an owner. Only non-None kwargs are written.

    Owner ``id`` is immutable — it's referenced by ``accounts.owner_id`` and
    several denormalized rows. Only display name and (future) cosmetic
    fields can change here.

    Raises ``ValueError`` if the owner does not exist or any value fails
    validation. Caller commits.
    """
    row = conn.execute(
        "SELECT id FROM owners WHERE LOWER(id) = LOWER(?)", (owner_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"Owner {owner_id!r} not found")

    sets: list[str] = []
    params: list = []
    if display_name is not None:
        cleaned = display_name.strip()
        if not cleaned:
            raise ValueError("display_name cannot be empty")
        if len(cleaned) > 50:
            raise ValueError("display_name max length is 50")
        sets.append("display_name = ?")
        params.append(cleaned)

    if not sets:
        return  # nothing to update — silent noop

    params.append(owner_id)
    conn.execute(
        f"UPDATE owners SET {', '.join(sets)} WHERE LOWER(id) = LOWER(?)",
        params,
    )
    log.info("Updated owner %s: %s", owner_id, ", ".join(sets))


def assign_account_owner(
    conn: sqlite3.Connection,
    account_id: str,
    owner_id: Optional[str],
    *,
    persist_override: bool = False,
    overrides_path: Path | str | None = None,
) -> Optional[str]:
    """Set the owner_id on an account. Pass None to make it shared (ours).

    Validates the account and owner before writing. Caller commits.
    """
    cleaned_account_id = str(account_id).strip()
    if not cleaned_account_id:
        raise ValueError("account_id is required")

    row = conn.execute(
        "SELECT id FROM accounts WHERE id = ?",
        (cleaned_account_id,),
    ).fetchone()
    if not row:
        raise ValueError("Account not found")

    canonical_owner_id = _canonical_owner_id(conn, owner_id)
    conn.execute(
        "UPDATE accounts SET owner_id = ? WHERE id = ?",
        (canonical_owner_id, cleaned_account_id),
    )
    if persist_override:
        record_account_ownership_override(
            cleaned_account_id,
            canonical_owner_id,
            path=overrides_path,
        )
    log.info(
        "Assigned account %s -> owner %s",
        redact_account_id_for_logs(cleaned_account_id),
        canonical_owner_id or "(shared)",
    )
    return canonical_owner_id


def get_account_owner(conn: sqlite3.Connection, account_id: str) -> Optional[str]:
    """Return the owner_id for a given account, or None if shared."""
    row = conn.execute(
        "SELECT owner_id FROM accounts WHERE id = ?", (account_id,)
    ).fetchone()
    return row["owner_id"] if row else None


def list_account_ownership_assignments(conn: sqlite3.Connection) -> list[dict]:
    """Return active account rows needed by Settings ownership assignment."""
    rows = conn.execute(
        """
        SELECT
            a.id,
            a.institution_id,
            COALESCE(i.display_name, a.institution_id) AS institution_name,
            a.name,
            a.type,
            a.owner_id,
            a.closed_at,
            a.is_active,
            a.is_synthetic
        FROM accounts a
        LEFT JOIN institutions i ON i.id = a.institution_id
        WHERE a.is_active = 1
        ORDER BY institution_name, a.name, a.id
        """
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["is_active"] = bool(item.get("is_active"))
        item["is_synthetic"] = bool(item.get("is_synthetic"))
        out.append(item)
    return out


# ── View Resolution ─────────────────────────────────────────────────────────


def resolve_account_ids_for_view(
    conn: sqlite3.Connection, view: str = "ours"
) -> Optional[set[str]]:
    """Resolve a dashboard view to a set of account IDs.

    Args:
        conn: Active SQLite connection.
        view: One of "ours", "mine", "theirs", OR any owner_id string
              that exists in the `owners` table. Owner ids are matched
              case-insensitively.

    Returns:
        A set of account IDs matching the view, or None if view
        is "ours" (meaning no filtering — return everything).

    The dashboard uses this resolver in two modes:
    - Legacy ours/mine/theirs (pre-Phase 7) pivots around the
      configured primary_owner.
    - Per-owner views ("quintin", "amy", etc.) treat each owner_id as
      its own discrete view, returning that owner's accounts plus the
      shared / NULL-owner accounts.
    """
    view_norm = view.lower().strip()

    if view_norm == "ours":
        # No filtering — caller should use all accounts
        return None

    primary = get_primary_owner()

    if view_norm == "mine":
        if not primary:
            log.warning("No primary_owner configured — falling back to 'ours' view")
            return None
        rows = conn.execute(
            """
            SELECT id FROM accounts
            WHERE is_active = 1
              AND (LOWER(owner_id) = LOWER(?) OR owner_id IS NULL)
        """,
            (primary,),
        ).fetchall()
        return {r["id"] for r in rows}

    if view_norm == "theirs":
        if not primary:
            log.warning("No primary_owner configured — falling back to 'ours' view")
            return None
        rows = conn.execute(
            """
            SELECT id FROM accounts
            WHERE is_active = 1
              AND (
                (owner_id IS NOT NULL AND LOWER(owner_id) != LOWER(?))
                OR owner_id IS NULL
              )
        """,
            (primary,),
        ).fetchall()
        return {r["id"] for r in rows}

    # Per-owner view: treat `view` as an owner_id. Match case-insensitively
    # against the owners table. If no such owner exists, fall back to "ours".
    owner_row = conn.execute(
        "SELECT id FROM owners WHERE LOWER(id) = LOWER(?)",
        (view_norm,),
    ).fetchone()
    if not owner_row:
        log.warning("Unknown view '%s' — falling back to 'ours'", view)
        return None

    rows = conn.execute(
        """
        SELECT id FROM accounts
        WHERE is_active = 1
          AND (LOWER(owner_id) = LOWER(?) OR owner_id IS NULL)
        """,
        (view_norm,),
    ).fetchall()
    return {r["id"] for r in rows}


def seed_owners(conn: sqlite3.Connection) -> None:
    """Seed the owners table from owner_config.yaml.

    Called during database initialization alongside seed_institutions().
    Idempotent via INSERT OR IGNORE.
    """
    owners = get_configured_owners()
    for owner in owners:
        create_owner(conn, owner["id"], owner["display_name"])

    if owners:
        conn.commit()
        log.info("Seeded %d owners from owner_config.yaml", len(owners))


def resolve_owner_account_ids(
    conn: sqlite3.Connection,
    owner_id: str | None,
    account_ids: list[str] | None = None,
) -> list[str] | None:
    """
    Convenience resolver: if owner_id is given and account_ids is not,
    resolves to the owned account_ids. Returns None for 'no filter'.

    WARNING: this resolver distinguishes ``None`` (no filter — return
    everything) from ``[]`` (owner owns no accounts — caller should
    return zero rows). Many historical call sites conflate the two via
    ``if not account_ids:`` truthy checks, which silently drops the
    filter and leaks another owner's data. Prefer ``build_account_filter``
    below for new code — it encodes the correct short-circuit.
    """
    if account_ids or not owner_id:
        return account_ids
    result = resolve_account_ids_for_view(conn, owner_id)
    return list(result) if result is not None else None


def build_account_filter(
    conn: sqlite3.Connection,
    owner_id: str | None,
    account_ids: list[str] | None,
    *,
    column: str = "account_id",
) -> tuple[str, list]:
    """
    Build a SQL filter fragment for an owner-scoped or account-scoped query.

    Returns ``(sql_fragment, params)``:

    - ``("", [])`` — no filter is set (household / "ours" view).
      Caller's query runs unchanged and returns everything.
    - ``(" AND 1=0", [])`` — filter resolved to zero accounts (owner owns
      nothing). The ``1=0`` clause is universally folded by the SQLite
      query planner into an empty result set, so aggregates return NULL
      (which downstream ``row["x"] or 0`` guards already handle) and
      row-listing queries return ``[]``.
    - ``(" AND {column} IN (?, ?, ...)", [ids...])`` — active filter.

    This helper exists because the historical ``if not account_ids:``
    pattern in cash_flow / reports / budgets / forecasting / allocation /
    performance silently collapsed ``[]`` and ``None`` into the same
    "no filter" branch, causing per-owner views to leak the primary
    owner's data whenever the scoped owner had zero accounts.

    Args:
        conn: DB connection (used to resolve ``owner_id`` → account set
            via ``resolve_account_ids_for_view``).
        owner_id: Optional owner id to scope by. Ignored when
            ``account_ids`` is already supplied.
        account_ids: Optional explicit account id list. Takes precedence
            over ``owner_id`` when given.
        column: Column name the ``IN (...)`` clause should apply to.
            Defaults to ``account_id``; queries that join through a
            differently-named column (e.g. ``ih.account_id``) should
            override this.

    Callers that pre-resolved their own account list can still call this
    helper by passing the resolved list as ``account_ids`` and leaving
    ``owner_id`` as ``None`` — the helper will only resolve when both
    ``account_ids is None`` and ``owner_id`` is truthy.
    """
    if account_ids is None and owner_id:
        resolved = resolve_account_ids_for_view(conn, owner_id)
        # resolved is None ⇒ no-filter view ("ours"); keep account_ids None.
        # resolved is a set (possibly empty) ⇒ materialize as list so the
        # next two branches can distinguish the empty-filter case.
        account_ids = list(resolved) if resolved is not None else None
    if account_ids is None:
        return "", []
    if not account_ids:
        return " AND 1=0", []
    placeholders = ", ".join("?" for _ in account_ids)
    return f" AND {column} IN ({placeholders})", list(account_ids)
