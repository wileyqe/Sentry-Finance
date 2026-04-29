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
            "reference_date": "2026-04-28",
            "database_fingerprint": live["database_fingerprint"],
        }
        conn.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            ("trusted_seed_manifest", json.dumps(manifest, sort_keys=True)),
        )
        conn.commit()

    monkeypatch.setenv("SENTRY_DB_PATH", str(db_path))
    monkeypatch.setenv("SENTRY_DB_MODE", "trusted")

    from backend.runtime_identity import build_runtime_identity

    identity = build_runtime_identity()
    assert identity["db_path"] == str(db_path.resolve())
    assert identity["db_mode"] == "trusted"
    assert identity["seed_version"] == "unit-test-seed"
    assert identity["reference_date"] == "2026-04-28"
    assert identity["manifest_fingerprint"] == live["database_fingerprint"]
    assert identity["live_fingerprint"] == live["database_fingerprint"]
    assert identity["fingerprint_match"] is True


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

    from backend.runtime_identity import build_runtime_identity

    identity = build_runtime_identity()
    assert identity["manifest_fingerprint"] == "not-the-live-fingerprint"
    assert identity["live_fingerprint"] != identity["manifest_fingerprint"]
    assert identity["fingerprint_match"] is False
