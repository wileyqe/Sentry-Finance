from pathlib import Path

import pytest

from dal.connection import DB_PATH, resolve_db_path


def test_resolve_db_path_reads_environment_at_call_time(monkeypatch, tmp_path):
    monkeypatch.delenv("SENTRY_DB_PATH", raising=False)
    assert resolve_db_path() == DB_PATH

    first = tmp_path / "first.db"
    second = tmp_path / "second.db"

    monkeypatch.setenv("SENTRY_DB_PATH", str(first))
    assert resolve_db_path() == first

    monkeypatch.setenv("SENTRY_DB_PATH", str(second))
    assert resolve_db_path() == second


def test_resolve_db_path_can_require_explicit_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("SENTRY_DB_PATH", raising=False)
    with pytest.raises(RuntimeError, match="SENTRY_DB_PATH is required"):
        resolve_db_path(require_explicit=True)

    explicit = tmp_path / "explicit.db"
    assert resolve_db_path(explicit, require_explicit=True) == explicit

    env_path = tmp_path / "env.db"
    monkeypatch.setenv("SENTRY_DB_PATH", str(env_path))
    assert resolve_db_path(require_explicit=True) == Path(env_path)
