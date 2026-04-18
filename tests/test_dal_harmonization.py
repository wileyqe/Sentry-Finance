"""
tests/test_dal_harmonization.py — Regression guard for the Phase-17
wrapper harmonization pass.

Asserts the two invariants that were added to existing wrappers
(``record_credit_score``, ``add_valuation``) and the caller-commits
change (no internal ``conn.commit()``).
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.database import init_db, get_db  # noqa: E402
from dal.credit_scores import record_credit_score  # noqa: E402
from dal.vehicles import add_valuation, add_vehicle  # noqa: E402


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    p = Path(path)
    init_db(p)
    with get_db(p) as conn:
        conn.execute("INSERT INTO institutions (id, display_name) VALUES ('nfcu','NFCU')")
        conn.execute(
            "INSERT INTO vehicle_assets (id, make, model, year) "
            "VALUES ('car_A','Toyota','Corolla',2020)"
        )
        conn.commit()
    yield p
    try:
        os.unlink(path)
    except OSError:
        pass


# ── Invariant: credit_scores.score must be 300–850 ───────────────────────


def test_credit_score_rejects_below_range(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match=r"outside valid \[300, 850\]"):
            record_credit_score(
                conn, score=299, score_type="FICO", source="TransUnion",
                institution_id="nfcu", score_date="2026-01-15",
            )


def test_credit_score_rejects_above_range(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match=r"outside valid \[300, 850\]"):
            record_credit_score(
                conn, score=851, score_type="FICO", source="TransUnion",
                institution_id="nfcu", score_date="2026-01-15",
            )


def test_credit_score_accepts_boundary_values(db):
    with get_db(db) as conn:
        record_credit_score(
            conn, score=300, score_type="FICO", source="TransUnion",
            institution_id="nfcu", score_date="2026-01-01",
        )
        record_credit_score(
            conn, score=850, score_type="FICO", source="TransUnion",
            institution_id="nfcu", score_date="2026-01-02",
        )
        conn.commit()
        rows = conn.execute("SELECT score FROM credit_scores ORDER BY score_date").fetchall()
    assert [r["score"] for r in rows] == [300, 850]


# ── Invariant: vehicle_valuations.estimated_value must be > 0 ────────────


def test_add_valuation_rejects_zero(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="estimated_value must be > 0"):
            add_valuation(conn, "car_A", "2026-01-15", 0)


def test_add_valuation_rejects_negative(db):
    with get_db(db) as conn:
        with pytest.raises(ValueError, match="estimated_value must be > 0"):
            add_valuation(conn, "car_A", "2026-01-15", -100.0)


# ── Caller-commits contract: no internal commit in record_credit_score ──


def test_record_credit_score_does_not_commit(db):
    """Without an explicit ``conn.commit()``, a new connection must not
    see the row — this is the load-bearing assertion for the harmonized
    caller-commits convention. Pre-Phase-17 this would have silently
    committed and passed.
    """
    with get_db(db) as conn:
        record_credit_score(
            conn, score=720, score_type="FICO", source="TransUnion",
            institution_id="nfcu", score_date="2026-03-01",
        )
        # NOTE: no conn.commit() here

    # Open a fresh connection — it should see nothing.
    with get_db(db) as other:
        count = other.execute(
            "SELECT COUNT(*) FROM credit_scores WHERE score_date='2026-03-01'"
        ).fetchone()[0]
    assert count == 0


def test_add_valuation_does_not_commit(db):
    with get_db(db) as conn:
        add_valuation(conn, "car_A", "2026-03-01", 15000.0, source="KBB")
        # NOTE: no conn.commit() here

    with get_db(db) as other:
        count = other.execute(
            "SELECT COUNT(*) FROM vehicle_valuations WHERE valuation_date='2026-03-01'"
        ).fetchone()[0]
    assert count == 0


def test_add_vehicle_does_not_commit(db):
    with get_db(db) as conn:
        add_vehicle(conn, "car_B", "Honda", "Civic", 2022)
        # NOTE: no conn.commit() here

    with get_db(db) as other:
        row = other.execute(
            "SELECT id FROM vehicle_assets WHERE id='car_B'"
        ).fetchone()
    assert row is None
