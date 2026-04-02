# P4-T02: Credit Score Scraping

## Context

You are working on Sentry Finance, a local-first personal finance app.
Both NFCU and Chase provide free credit score access to their members:

- **NFCU** — FICO Score (from TransUnion), updated monthly, displayed on
  the dashboard or in a "Credit Score" section after login. The score is
  visible on the main accounts overview page or requires navigating to a
  dedicated credit score page.
- **Chase** — VantageScore 3.0 (from Experian), available via Chase Credit
  Journey. Accessible from the Chase dashboard sidebar or from
  `https://creditcards.chase.com/free-credit-score`.

Neither connector currently extracts credit scores.

## Starting State

- `extractors/nfcu_connector.py` has a 3-phase export (`_trigger_export`)
  with balance, transaction, and loan detail scraping. No credit score logic.
- `extractors/chase_connector.py` has a multi-phase export. No credit score logic.
- No `credit_scores` table exists in the database.
- `dal/balances.py` has `record_balance()` and `record_loan_details()` as
  precedent for "scrape → persist" patterns.

## Task

### 1. New Migration: `v17_credit_scores.py`

Create `dal/migrations/v17_credit_scores.py`:

```python
"""Schema V17 — Credit score history table."""

VERSION = 17

_DDL = """
CREATE TABLE IF NOT EXISTS credit_scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    score           INTEGER NOT NULL,
    score_type      TEXT NOT NULL,       -- 'FICO' or 'VantageScore'
    source          TEXT NOT NULL,       -- 'TransUnion', 'Experian', etc.
    institution_id  TEXT NOT NULL REFERENCES institutions(id),
    score_date      TEXT NOT NULL,       -- YYYY-MM-DD when score was computed
    factors         TEXT,                -- JSON array of key factors (optional)
    as_of           TEXT NOT NULL DEFAULT (datetime('now')),
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_credit_score_date
    ON credit_scores(score_date DESC);
CREATE INDEX IF NOT EXISTS idx_credit_score_institution
    ON credit_scores(institution_id, score_date DESC);
"""

def run(conn):
    conn.executescript(_DDL)
```

**Deduplication constraint:** No UNIQUE constraint on the table — instead,
deduplicate on insert (check if a row with the same `institution_id` +
`score_date` already exists before inserting).

### 2. New DAL Function: `dal/credit_scores.py`

```python
"""Credit score persistence and retrieval."""

import json
import sqlite3
from datetime import datetime


def record_credit_score(
    conn: sqlite3.Connection,
    score: int,
    score_type: str,
    source: str,
    institution_id: str,
    score_date: str,
    factors: list[str] | None = None,
) -> bool:
    """Persist a credit score, deduplicating by institution + date.

    Returns True if inserted, False if duplicate.
    """
    existing = conn.execute(
        """SELECT id FROM credit_scores
           WHERE institution_id = ? AND score_date = ?""",
        (institution_id, score_date),
    ).fetchone()
    if existing:
        return False

    conn.execute(
        """INSERT INTO credit_scores
           (score, score_type, source, institution_id, score_date, factors)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            score,
            score_type,
            source,
            institution_id,
            score_date,
            json.dumps(factors) if factors else None,
        ),
    )
    conn.commit()
    return True


def get_latest_credit_scores(conn: sqlite3.Connection) -> list[dict]:
    """Return the latest credit score per institution/source.

    Returns list of dicts with: score, score_type, source, institution_id,
    score_date, factors.
    """
    rows = conn.execute("""
        SELECT cs.*
        FROM credit_scores cs
        INNER JOIN (
            SELECT institution_id, source, MAX(score_date) as max_date
            FROM credit_scores
            GROUP BY institution_id, source
        ) latest ON cs.institution_id = latest.institution_id
                 AND cs.source = latest.source
                 AND cs.score_date = latest.max_date
        ORDER BY cs.score_date DESC
    """).fetchall()

    return [
        {
            "score": r["score"],
            "score_type": r["score_type"],
            "source": r["source"],
            "institution_id": r["institution_id"],
            "score_date": r["score_date"],
            "factors": json.loads(r["factors"]) if r["factors"] else [],
        }
        for r in rows
    ]


def get_credit_score_history(
    conn: sqlite3.Connection,
    months: int = 12,
) -> list[dict]:
    """Return credit score history for all sources over the last N months.

    Returns list of dicts ordered by score_date ascending.
    """
    rows = conn.execute(
        """SELECT score, score_type, source, institution_id, score_date
           FROM credit_scores
           WHERE score_date >= date('now', ?)
           ORDER BY score_date ASC""",
        (f"-{months} months",),
    ).fetchall()

    return [dict(r) for r in rows]
```

### 3. NFCU Credit Score Scraping

Add a Phase 4 to `_trigger_export()` in `nfcu_connector.py`:

```python
# ── Phase 4: Credit Score ────────────────────────────────────
if any(getattr(a, 'wants_credit_score', False) for a in accounts):
    print("\n  ── Phase 4: Credit Score ──")
    self._scrape_credit_score(page)
```

Implement `_scrape_credit_score()`:
- Navigate to the NFCU credit score page (try the dashboard first,
  or navigate to a known credit score URL)
- Look for the 3-digit score value near labels like "FICO", "Credit Score",
  "Your Score", etc.
- Extract the score date if visible ("as of MM/DD/YYYY")
- Optionally extract key factors if listed
- Call `record_credit_score()` to persist
- Use regex extraction similar to the existing `_extract_field_value()`

Add `wants_credit_score` support to `AccountConfig` in
`skills/institution_connector.py` (default `False`).

### 4. Chase Credit Score Scraping

Add credit score extraction to `chase_connector.py`:
- During Phase 1 (or as a new phase), look for Credit Journey data
- Navigate to `https://creditcards.chase.com/free-credit-score` or
  look for the score widget on the Chase dashboard
- Extract VantageScore 3.0, source "Experian"
- Persist via `record_credit_score()`

### 5. API Endpoint

Add to `backend/routers/reports.py`:

```python
@router.get("/api/credit-scores")
def credit_scores():
    """Return latest credit scores per source."""
    with get_db() as conn:
        from dal.credit_scores import get_latest_credit_scores
        scores = get_latest_credit_scores(conn)
    return {"scores": scores}


@router.get("/api/credit-scores/history")
def credit_score_history(months: int = Query(12, ge=1, le=60)):
    """Return credit score history for trend display."""
    with get_db() as conn:
        from dal.credit_scores import get_credit_score_history
        history = get_credit_score_history(conn, months=months)
    return {"history": history, "count": len(history)}
```

## Files to Create

1. `dal/migrations/v17_credit_scores.py` — new table
2. `dal/credit_scores.py` — persistence and retrieval functions

## Files to Modify

1. `extractors/nfcu_connector.py` — add Phase 4 credit score scraping
2. `extractors/chase_connector.py` — add credit score scraping
3. `skills/institution_connector.py` — add `wants_credit_score` to AccountConfig
4. `config/owner_config.yaml` — enable credit score for NFCU and Chase accounts
5. `backend/routers/reports.py` — add API endpoints

## Files NOT to Modify

- Database schema beyond V17
- `dal/balances.py`
- Any frontend files
- Other connector files (Affirm, Fidelity, TSP, Acorns)

## Constraints

- Credit scores are **read-only** — scraped and stored, never modified
- Deduplication by `(institution_id, score_date)` — same score_date = skip
- Score must be an integer between 300 and 850 (validation on persist)
- `factors` is optional — not all pages show key factors
- If the credit score page is behind an extra click/navigation,
  handle it gracefully without blocking the main pipeline
- Use `try/except` around the credit score phase — a failure here must
  NOT abort the rest of the export

## Done Checklist

- [ ] V17 migration creates `credit_scores` table with proper indexes
- [ ] `dal/credit_scores.py` has `record_credit_score()`, `get_latest_credit_scores()`, `get_credit_score_history()`
- [ ] NFCU connector extracts FICO score (score, date, optional factors)
- [ ] Chase connector extracts VantageScore (score, date, optional factors)
- [ ] `wants_credit_score` config support added to AccountConfig
- [ ] Deduplication prevents duplicate inserts for same institution+date
- [ ] API endpoints exist: `GET /api/credit-scores` and `GET /api/credit-scores/history`
- [ ] Credit score scraping failures do NOT abort main export

## Verification

After completion, Claude will:
1. Read V17 migration and verify table schema
2. Read `dal/credit_scores.py` and verify dedup logic
3. Run import checks for all modified modules
4. Verify credit score scraping is wrapped in try/except
5. Verify `AccountConfig` has `wants_credit_score` attribute
