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
