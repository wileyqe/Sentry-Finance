"""
v32: income_sources registry (Phase 14 Phase B).

Adds a per-owner registry of income sources that the Sankey classifier
consults to decide how each income flow is coloured and routed on the
left edge. Replaces the Phase-A behavior where *every* payroll
``other_deductions`` value landed in CONSUMED; post-v32, rows matching
a registered source with ``tax_treatment='employer_match_bypass'``
(for example) route directly to STORED_ILLIQUID via a pseudo-edge.

Columns of note
---------------
- ``match_rule_json`` is an opaque JSON blob. Current Phase B shape:
  ``{"counterparty_substring": "...", "category": "...",
  "owner_id": "..."}``. At least one of counterparty or category must
  be present (enforced by ``dal.flow_classification.match_rule_matches``).
- ``estimated_tax_reserve_pct`` defaults to ``0.0`` and is unused in
  Phase B. Present now so the future opt-in tax-projection view does
  not require a schema change.
- ``bypass_cash_routing`` (0/1) = 1 means the source draws a pseudo-edge
  direct to STORED_ILLIQUID without a checking-account hop. Employer
  retirement matches use this.

The ``tax_treatment`` CHECK set is closed to the eight Phase B values
documented in ``docs/prompts/Phase-14/P14-T02_four-terminal-buckets.md``.
Extending it is a future migration, not a code change.
"""

VERSION = 32


def run(conn):
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS income_sources (
            id                        TEXT    PRIMARY KEY,
            display_label             TEXT    NOT NULL,
            owner_id                  TEXT    NOT NULL REFERENCES owners(id),
            tax_treatment             TEXT    NOT NULL CHECK (tax_treatment IN (
                'w2_withheld',
                'pension_withheld',
                'nontaxable',
                'contractor_no_withholding',
                'interest_dividend',
                'employer_match_bypass',
                'rental_income',
                'other'
            )),
            default_category          TEXT,
            match_rule_json           TEXT    NOT NULL,
            estimated_tax_reserve_pct REAL    NOT NULL DEFAULT 0.0,
            bypass_cash_routing       INTEGER NOT NULL DEFAULT 0
                                              CHECK (bypass_cash_routing IN (0, 1)),
            active                    INTEGER NOT NULL DEFAULT 1
                                              CHECK (active IN (0, 1)),
            created_at                TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at                TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)

    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_income_sources_owner "
        "ON income_sources(owner_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_income_sources_active "
        "ON income_sources(active)"
    )
