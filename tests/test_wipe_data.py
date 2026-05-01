import json
import sqlite3
from pathlib import Path

import pytest

from scripts import wipe_data


def _create_db(path: Path, *, trusted: bool = False) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            PRAGMA user_version = 43;

            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );

            CREATE TABLE accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            );

            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            );

            CREATE TABLE app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (43, '2026-05-01')"
        )
        conn.execute("INSERT INTO accounts(name) VALUES ('checking'), ('savings')")
        conn.execute("INSERT INTO transactions(account_id, amount) VALUES (1, -100), (2, 200)")
        conn.execute("INSERT INTO app_settings(key, value) VALUES ('theme', 'dark')")
        if trusted:
            conn.execute(
                "INSERT INTO app_settings(key, value) VALUES (?, ?)",
                (
                    wipe_data.TRUSTED_MANIFEST_KEY,
                    json.dumps(
                        {
                            "seed_version": "trusted-test",
                            "database_fingerprint": "abc123",
                        }
                    ),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _count(path: Path, table: str) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_resolve_target_db_requires_explicit_path_or_env(monkeypatch):
    monkeypatch.delenv("SENTRY_DB_PATH", raising=False)

    with pytest.raises(wipe_data.WipeError, match="--db or SENTRY_DB_PATH"):
        wipe_data.resolve_target_db(None)


def test_dry_run_reports_tables_counts_preserved_tables_and_manifest(tmp_path):
    db_path = tmp_path / "trusted.db"
    _create_db(db_path, trusted=True)

    plan = wipe_data.build_wipe_plan(db_path, env={})
    report = wipe_data.format_plan(plan)

    assert f"Database: {db_path.resolve()}" in report
    assert "Detected DB mode: trusted-seed-manifest" in report
    assert "Trusted-seed manifest: present" in report
    assert "seed_version=trusted-test" in report
    assert "fingerprint=abc123" in report
    assert "  - accounts: 2" in report
    assert "  - transactions: 2" in report
    assert "  - app_settings: 2" in report
    assert "  - schema_migrations: 1" in report
    assert "Required confirmation token: WIPE " in report


def test_execute_refuses_wrong_confirmation_without_backup_or_wipe(tmp_path):
    db_path = tmp_path / "app.db"
    _create_db(db_path)
    plan = wipe_data.build_wipe_plan(db_path, env={})

    with pytest.raises(wipe_data.WipeError, match="confirmation token mismatch"):
        wipe_data.wipe_database(plan, confirmation="WIPE somewhere-else")

    assert _count(db_path, "accounts") == 2
    assert not list(tmp_path.glob("app.backup.*.db"))


def test_execute_creates_backup_wipes_data_and_preserves_structural_tables(tmp_path):
    db_path = tmp_path / "app.db"
    _create_db(db_path)
    plan = wipe_data.build_wipe_plan(db_path, env={})

    result = wipe_data.wipe_database(plan, confirmation=plan.confirmation_token)

    assert result.backup_path.exists()
    assert result.backup_path.parent == tmp_path
    assert _count(result.backup_path, "accounts") == 2
    assert _count(db_path, "accounts") == 0
    assert _count(db_path, "transactions") == 0
    assert _count(db_path, "app_settings") == 0
    assert _count(db_path, "schema_migrations") == 1

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 43
    finally:
        conn.close()


def test_execute_refuses_trusted_manifest_without_named_override(tmp_path):
    db_path = tmp_path / "trusted.db"
    _create_db(db_path, trusted=True)
    plan = wipe_data.build_wipe_plan(db_path, env={})

    with pytest.raises(wipe_data.WipeError, match="trusted-seed manifest detected"):
        wipe_data.wipe_database(plan, confirmation=plan.confirmation_token)

    assert _count(db_path, "accounts") == 2
    assert not list(tmp_path.glob("trusted.backup.*.db"))


def test_trusted_override_wipes_manifest_after_backup(tmp_path):
    db_path = tmp_path / "trusted.db"
    _create_db(db_path, trusted=True)
    plan = wipe_data.build_wipe_plan(db_path, env={})

    result = wipe_data.wipe_database(
        plan,
        confirmation=plan.confirmation_token,
        allow_trusted_seed_wipe=True,
    )

    assert result.backup_path.exists()
    assert _count(db_path, "accounts") == 0
    assert _count(db_path, "app_settings") == 0
