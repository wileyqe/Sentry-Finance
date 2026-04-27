"""
v42: Add ``owner_id`` column to ``document_drops``.

Closes the last residual of the 2026-04-25 numeric audit (10 endpoints
were missing ``owner_id``; 9 fixed in-session). The yearly tax-checklist
endpoint can now scope to a specific owner so:

- The primary owner's view shows DFAS 1099-R, Fidelity Consolidated 1099,
  Acorns 1099, Affirm 1099-INT, and the household NFCU 1098.
- A non-primary owner (e.g. Amy) sees only the household NFCU 1098 —
  no military pension, no Fidelity/Acorns/Affirm yet.
- Household view (``owner_id`` not passed) preserves today's behavior.

Backfill rules per parser_type — match the inference each parser's
``resolve_owner_id`` runs on new commits:

- ``dfas_1099r``, ``mypay_ras``, ``fidelity_1099``, ``acorns_1099``,
  ``affirm_1099int`` → primary owner from ``owner_config.yaml``
  (``Quintin`` for the seeded household).
- ``nfcu_1098`` → ``NULL`` (mortgage is household-scoped).
- Everything else → ``NULL`` (preserves the prior household-only model).

Idempotent against partial re-runs via ``column_exists``.
"""

from dal.migrations import column_exists

VERSION = 42

_PRIMARY_PARSER_TYPES = (
    "dfas_1099r",
    "mypay_ras",
    "fidelity_1099",
    "acorns_1099",
    "affirm_1099int",
)


def run(conn):
    from dal.owners import get_primary_owner

    if not column_exists(conn, "document_drops", "owner_id"):
        conn.execute(
            "ALTER TABLE document_drops ADD COLUMN owner_id TEXT"
        )

    primary = (get_primary_owner() or "quintin").lower()
    placeholders = ",".join("?" * len(_PRIMARY_PARSER_TYPES))
    conn.execute(
        f"""UPDATE document_drops
            SET owner_id = ?
            WHERE owner_id IS NULL
              AND parser_type IN ({placeholders})""",
        (primary, *_PRIMARY_PARSER_TYPES),
    )
