"""Credit score persistence and retrieval."""

import json
import sqlite3
from typing import Optional


def record_credit_score(
    conn: sqlite3.Connection,
    score: int,
    score_type: str,
    source: str,
    institution_id: str,
    score_date: str,
    factors: list[str] | None = None,
    owner_id: Optional[str] = None,
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
           (score, score_type, source, institution_id, score_date, factors, owner_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            score,
            score_type,
            source,
            institution_id,
            score_date,
            json.dumps(factors) if factors else None,
            owner_id.lower() if owner_id else None,
        ),
    )
    conn.commit()
    return True


def get_latest_credit_scores(
    conn: sqlite3.Connection,
    owner_id: Optional[str] = None,
) -> list[dict]:
    """Return the latest credit score per institution/source.

    If owner_id is provided, restricts results to scores stamped with
    that owner. Owner ids are matched case-insensitively.
    """
    if owner_id:
        rows = conn.execute(
            """
            SELECT cs.*
            FROM credit_scores cs
            INNER JOIN (
                SELECT institution_id, source, MAX(score_date) as max_date
                FROM credit_scores
                WHERE LOWER(owner_id) = LOWER(?)
                GROUP BY institution_id, source
            ) latest ON cs.institution_id = latest.institution_id
                     AND cs.source = latest.source
                     AND cs.score_date = latest.max_date
            WHERE LOWER(cs.owner_id) = LOWER(?)
            ORDER BY cs.score_date DESC
            """,
            (owner_id, owner_id),
        ).fetchall()
    else:
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
    owner_id: Optional[str] = None,
) -> list[dict]:
    """Return credit score history for all sources over the last N months.

    Returns list of dicts ordered by score_date ascending. If owner_id
    is provided, restricts to that owner's scores (case-insensitive).
    """
    if owner_id:
        rows = conn.execute(
            """SELECT score, score_type, source, institution_id, score_date
               FROM credit_scores
               WHERE score_date >= date('now', ?)
                 AND LOWER(owner_id) = LOWER(?)
               ORDER BY score_date ASC""",
            (f"-{months} months", owner_id),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT score, score_type, source, institution_id, score_date
               FROM credit_scores
               WHERE score_date >= date('now', ?)
               ORDER BY score_date ASC""",
            (f"-{months} months",),
        ).fetchall()

    return [dict(r) for r in rows]
