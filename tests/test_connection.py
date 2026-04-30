import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dal.connection import DB_PATH, get_db, resolve_db_path  # noqa: E402
from dal.database import init_db  # noqa: E402
from dal.trusted_seed_manifest import live_seed_fingerprint  # noqa: E402


def test_resolve_db_path_reads_environment_at_call_time(monkeypatch, tmp_path):
    monkeypatch.delenv("SENTRY_DB_PATH", raising=False)
    with pytest.raises(RuntimeError, match="SENTRY_DB_PATH is required"):
        resolve_db_path()

    first = tmp_path / "first.db"
    second = tmp_path / "second.db"

    assert resolve_db_path(DB_PATH) == DB_PATH

    monkeypatch.setenv("SENTRY_DB_PATH", str(first))
    assert resolve_db_path() == first

    monkeypatch.setenv("SENTRY_DB_PATH", str(second))
    assert resolve_db_path() == second


def test_resolve_db_path_can_require_explicit_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("SENTRY_DB_PATH", raising=False)
    with pytest.raises(RuntimeError, match="SENTRY_DB_PATH is required"):
        resolve_db_path(require_explicit=True)
    with pytest.raises(RuntimeError, match="SENTRY_DB_PATH is required"):
        resolve_db_path(require_explicit=False)

    explicit = tmp_path / "explicit.db"
    assert resolve_db_path(explicit, require_explicit=True) == explicit

    env_path = tmp_path / "env.db"
    monkeypatch.setenv("SENTRY_DB_PATH", str(env_path))
    assert resolve_db_path(require_explicit=True) == Path(env_path)


def test_get_db_requires_env_or_explicit_path(monkeypatch, tmp_path):
    monkeypatch.delenv("SENTRY_DB_PATH", raising=False)
    with pytest.raises(RuntimeError, match="SENTRY_DB_PATH is required"):
        with get_db():
            pass

    db_path = tmp_path / "explicit.db"
    init_db(db_path)
    with get_db(db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] > 0


def test_runtime_identity_reports_active_db_and_live_fingerprint(monkeypatch, tmp_path):
    db_path = tmp_path / "runtime-identity.db"
    init_db(db_path)

    with get_db(db_path) as conn:
        live = live_seed_fingerprint(conn)
        manifest = {
            "seed_version": "unit-test-seed",
            "end_date": "2026-04-27",
            "reference_date": "2026-04-28",
            "reference_datetime": "2026-04-28T12:00:00+00:00",
            "years": 3,
            "database_fingerprint": live["database_fingerprint"],
        }
        conn.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            ("trusted_seed_manifest", json.dumps(manifest, sort_keys=True)),
        )
        conn.commit()

    monkeypatch.setenv("SENTRY_DB_PATH", str(db_path))
    monkeypatch.setenv("SENTRY_DB_MODE", "trusted")
    monkeypatch.delenv("SENTRY_REFERENCE_DATE", raising=False)
    monkeypatch.delenv("SENTRY_REFERENCE_DATETIME", raising=False)

    from backend.runtime_context import CONTRACT_VERSION, build_runtime_context
    from backend.runtime_identity import build_runtime_identity

    context = build_runtime_context()
    assert context["contract_version"] == CONTRACT_VERSION
    assert context["runtime"]["mode"] == "trusted"
    assert context["database"]["path"] == str(db_path.resolve())
    assert len(context["database"]["path_hash"]) == 64
    assert context["database"]["schema_version"] > 0
    assert context["database"]["live_fingerprint"] == live["database_fingerprint"]
    assert context["trusted_seed"] == {
        "present": True,
        "seed_version": "unit-test-seed",
        "end_date": "2026-04-27",
        "reference_date": "2026-04-28",
        "reference_datetime": "2026-04-28T12:00:00+00:00",
        "years": 3,
        "generated_at": None,
        "manifest_fingerprint": live["database_fingerprint"],
        "fingerprint_match": True,
    }
    assert context["clock"] == {
        "source": "trusted_seed_manifest",
        "reference_date": "2026-04-28",
        "reference_datetime": "2026-04-28T12:00:00+00:00",
        "fixed": True,
    }
    assert context["proof"] == {
        "trusted_seed_ready": True,
        "blocking_reasons": [],
    }

    identity = build_runtime_identity()
    assert identity["context_contract_version"] == CONTRACT_VERSION
    assert identity["db_path"] == str(db_path.resolve())
    assert identity["db_mode"] == "trusted"
    assert identity["seed_version"] == "unit-test-seed"
    assert identity["reference_date"] == "2026-04-28"
    assert identity["reference_datetime"] == "2026-04-28T12:00:00+00:00"
    assert identity["clock_source"] == "trusted_seed_manifest"
    assert identity["manifest_fingerprint"] == live["database_fingerprint"]
    assert identity["live_fingerprint"] == live["database_fingerprint"]
    assert identity["fingerprint_match"] is True
    assert identity["trusted_seed_ready"] is True
    assert identity["proof_blocking_reasons"] == []


def test_runtime_identity_flags_manifest_drift(monkeypatch, tmp_path):
    db_path = tmp_path / "runtime-identity-drift.db"
    init_db(db_path)

    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            (
                "trusted_seed_manifest",
                json.dumps(
                    {
                        "seed_version": "unit-test-seed",
                        "reference_date": "2026-04-28",
                        "database_fingerprint": "not-the-live-fingerprint",
                    },
                    sort_keys=True,
                ),
            ),
        )
        conn.commit()

    monkeypatch.setenv("SENTRY_DB_PATH", str(db_path))
    monkeypatch.setenv("SENTRY_DB_MODE", "trusted")

    from backend.runtime_context import build_runtime_context
    from backend.runtime_identity import build_runtime_identity

    context = build_runtime_context()
    assert context["proof"] == {
        "trusted_seed_ready": False,
        "blocking_reasons": ["trusted_seed_fingerprint_mismatch"],
    }

    identity = build_runtime_identity()
    assert identity["manifest_fingerprint"] == "not-the-live-fingerprint"
    assert identity["live_fingerprint"] != identity["manifest_fingerprint"]
    assert identity["fingerprint_match"] is False
    assert identity["trusted_seed_ready"] is False
    assert identity["proof_blocking_reasons"] == ["trusted_seed_fingerprint_mismatch"]


def test_runtime_context_flags_clock_override(monkeypatch, tmp_path):
    db_path = tmp_path / "runtime-context-clock-override.db"
    init_db(db_path)

    with get_db(db_path) as conn:
        live = live_seed_fingerprint(conn)
        conn.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            (
                "trusted_seed_manifest",
                json.dumps(
                    {
                        "seed_version": "unit-test-seed",
                        "reference_date": "2026-04-28",
                        "reference_datetime": "2026-04-28T12:00:00+00:00",
                        "database_fingerprint": live["database_fingerprint"],
                    },
                    sort_keys=True,
                ),
            ),
        )
        conn.commit()

    monkeypatch.setenv("SENTRY_DB_PATH", str(db_path))
    monkeypatch.setenv("SENTRY_DB_MODE", "trusted")
    monkeypatch.setenv("SENTRY_REFERENCE_DATE", "2026-05-01")
    monkeypatch.delenv("SENTRY_REFERENCE_DATETIME", raising=False)

    from backend.runtime_context import build_runtime_context

    context = build_runtime_context()
    assert context["clock"] == {
        "source": "env_reference_date",
        "reference_date": "2026-05-01",
        "reference_datetime": "2026-05-01T00:00:00+00:00",
        "fixed": True,
    }
    assert context["proof"] == {
        "trusted_seed_ready": False,
        "blocking_reasons": ["reference_clock_source:env_reference_date"],
    }
