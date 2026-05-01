"""Safe destructive SQLite data-wipe helper for Sentry Finance.

This is an offline maintenance tool. It intentionally uses only the Python
standard library and plain SQLite introspection instead of application DAL
helpers so it can inspect or wipe a chosen database without hidden app startup
behavior.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence


TRUSTED_MANIFEST_KEY = "trusted_seed_manifest"
CONFIRMATION_PREFIX = "WIPE "

STRUCTURAL_TABLES = frozenset(
    {
        "alembic_version",
        "migrations",
        "schema_migrations",
        "sqlite_sequence",
    }
)


class WipeError(RuntimeError):
    """Raised when wipe planning or execution is unsafe or impossible."""


@dataclass(frozen=True)
class TablePlan:
    name: str
    row_count: int


@dataclass(frozen=True)
class TrustedManifestStatus:
    present: bool
    seed_version: str | None = None
    database_fingerprint: str | None = None
    parse_error: str | None = None


@dataclass(frozen=True)
class WipePlan:
    db_path: Path
    db_mode: str | None
    tables_to_wipe: tuple[TablePlan, ...]
    preserved_tables: tuple[TablePlan, ...]
    trusted_manifest: TrustedManifestStatus

    @property
    def confirmation_token(self) -> str:
        return f"{CONFIRMATION_PREFIX}{self.db_path}"


@dataclass(frozen=True)
class WipeResult:
    backup_path: Path
    wiped_tables: tuple[TablePlan, ...]


def resolve_target_db(db_arg: str | None, env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    raw_path = db_arg or env.get("SENTRY_DB_PATH")
    if not raw_path:
        raise WipeError("--db or SENTRY_DB_PATH is required; refusing to infer a database")
    db_path = Path(raw_path).expanduser().resolve()
    if not db_path.exists():
        raise WipeError(f"database does not exist: {db_path}")
    if not db_path.is_file():
        raise WipeError(f"database path is not a file: {db_path}")
    return db_path


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def connect_existing(db_path: Path, *, readonly: bool) -> sqlite3.Connection:
    mode = "ro" if readonly else "rw"
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode={mode}", uri=True)
    except sqlite3.Error as exc:
        raise WipeError(f"could not open database {db_path}: {exc}") from exc
    conn.row_factory = sqlite3.Row
    return conn


def list_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ).fetchall()
    return [str(row["name"]) for row in rows]


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def table_row_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) AS count FROM {quote_identifier(table)}").fetchone()
    except sqlite3.Error as exc:
        raise WipeError(f"could not count rows in {table}: {exc}") from exc
    return int(row["count"])


def is_structural_table(table: str) -> bool:
    return table.startswith("sqlite_") or table in STRUCTURAL_TABLES


def load_trusted_manifest_status(conn: sqlite3.Connection) -> TrustedManifestStatus:
    if not table_exists(conn, "app_settings"):
        return TrustedManifestStatus(present=False)
    try:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            (TRUSTED_MANIFEST_KEY,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise WipeError(f"could not inspect trusted-seed manifest: {exc}") from exc
    if row is None:
        return TrustedManifestStatus(present=False)

    try:
        payload = json.loads(row["value"])
    except (TypeError, json.JSONDecodeError) as exc:
        return TrustedManifestStatus(present=True, parse_error=str(exc))

    return TrustedManifestStatus(
        present=True,
        seed_version=payload.get("seed_version"),
        database_fingerprint=payload.get("database_fingerprint"),
    )


def detect_db_mode(
    trusted_manifest: TrustedManifestStatus,
    env: Mapping[str, str] | None = None,
) -> str | None:
    env = os.environ if env is None else env
    if env.get("SENTRY_DB_MODE"):
        return env["SENTRY_DB_MODE"]
    if trusted_manifest.present:
        return "trusted-seed-manifest"
    return None


def build_wipe_plan(db_path: Path, env: Mapping[str, str] | None = None) -> WipePlan:
    with connect_existing(db_path, readonly=True) as conn:
        trusted_manifest = load_trusted_manifest_status(conn)
        wipe_tables: list[TablePlan] = []
        preserved_tables: list[TablePlan] = []
        for table in list_tables(conn):
            table_plan = TablePlan(name=table, row_count=table_row_count(conn, table))
            if is_structural_table(table):
                preserved_tables.append(table_plan)
            else:
                wipe_tables.append(table_plan)

    return WipePlan(
        db_path=db_path,
        db_mode=detect_db_mode(trusted_manifest, env=env),
        tables_to_wipe=tuple(wipe_tables),
        preserved_tables=tuple(preserved_tables),
        trusted_manifest=trusted_manifest,
    )


def format_plan(plan: WipePlan, *, execute: bool = False) -> str:
    lines = [
        "EXECUTE PLAN" if execute else "DRY RUN - no data will be deleted",
        f"Database: {plan.db_path}",
        f"Detected DB mode: {plan.db_mode or 'unknown'}",
    ]

    manifest = plan.trusted_manifest
    if manifest.present:
        details = []
        if manifest.seed_version:
            details.append(f"seed_version={manifest.seed_version}")
        if manifest.database_fingerprint:
            details.append(f"fingerprint={manifest.database_fingerprint}")
        if manifest.parse_error:
            details.append(f"parse_error={manifest.parse_error}")
        suffix = f" ({', '.join(details)})" if details else ""
        lines.append(f"Trusted-seed manifest: present{suffix}")
    else:
        lines.append("Trusted-seed manifest: not present")

    lines.append("")
    lines.append("Tables that would be wiped:")
    if plan.tables_to_wipe:
        lines.extend(f"  - {table.name}: {table.row_count}" for table in plan.tables_to_wipe)
    else:
        lines.append("  - none")

    lines.append("")
    lines.append("Tables intentionally preserved:")
    if plan.preserved_tables:
        lines.extend(f"  - {table.name}: {table.row_count}" for table in plan.preserved_tables)
    else:
        lines.append("  - none")

    lines.append("")
    lines.append(f"Required confirmation token: {plan.confirmation_token}")
    return "\n".join(lines)


def backup_database(db_path: Path, backup_dir: Path | None = None) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    target_dir = (backup_dir or db_path.parent).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    backup_path = target_dir / f"{db_path.stem}.backup.{timestamp}{db_path.suffix or '.db'}"
    if backup_path.exists():
        raise WipeError(f"backup path already exists: {backup_path}")

    try:
        with connect_existing(db_path, readonly=True) as source:
            with sqlite3.connect(backup_path) as dest:
                source.backup(dest)
    except Exception as exc:
        try:
            if backup_path.exists():
                backup_path.unlink()
        except OSError:
            pass
        raise WipeError(f"backup failed: {exc}") from exc

    shutil.copystat(db_path, backup_path)
    return backup_path


def wipe_database(
    plan: WipePlan,
    *,
    confirmation: str | None,
    allow_trusted_seed_wipe: bool = False,
    backup_dir: Path | None = None,
) -> WipeResult:
    if plan.trusted_manifest.present and not allow_trusted_seed_wipe:
        raise WipeError(
            "trusted-seed manifest detected; pass --allow-trusted-seed-wipe "
            "only when you intentionally want to destroy this fixture"
        )
    if confirmation != plan.confirmation_token:
        raise WipeError(
            "confirmation token mismatch; expected the exact token printed by the dry-run"
        )

    backup_path = backup_database(plan.db_path, backup_dir=backup_dir)

    try:
        with connect_existing(plan.db_path, readonly=False) as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("BEGIN IMMEDIATE")
            try:
                for table in plan.tables_to_wipe:
                    conn.execute(f"DELETE FROM {quote_identifier(table.name)}")
                if table_exists(conn, "sqlite_sequence") and plan.tables_to_wipe:
                    table_names = [table.name for table in plan.tables_to_wipe]
                    placeholders = ",".join("?" for _ in table_names)
                    conn.execute(
                        f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})",
                        table_names,
                    )
                conn.commit()
            except sqlite3.Error:
                conn.rollback()
                raise
            finally:
                conn.execute("PRAGMA foreign_keys = ON")
    except sqlite3.Error as exc:
        raise WipeError(f"wipe failed after backup {backup_path}: {exc}") from exc

    return WipeResult(backup_path=backup_path, wiped_tables=plan.tables_to_wipe)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect or destructively wipe data rows from a chosen Sentry SQLite DB"
    )
    parser.add_argument("--db", help="SQLite database path. Defaults to SENTRY_DB_PATH.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually wipe data. Omit for the default dry-run.",
    )
    parser.add_argument(
        "--confirm",
        help="Exact confirmation token printed by the dry-run for this DB path.",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        help="Directory for the timestamped backup copy. Defaults to the DB directory.",
    )
    parser.add_argument(
        "--allow-trusted-seed-wipe",
        action="store_true",
        help="Intentionally allow wiping a DB that contains a trusted-seed manifest.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        db_path = resolve_target_db(args.db)
        plan = build_wipe_plan(db_path)
        print(format_plan(plan, execute=args.execute))

        if not args.execute:
            print("")
            print("No changes made. Add --execute and the exact --confirm token to wipe.")
            return 0

        result = wipe_database(
            plan,
            confirmation=args.confirm,
            allow_trusted_seed_wipe=args.allow_trusted_seed_wipe,
            backup_dir=args.backup_dir,
        )
        print("")
        print(f"Backup created: {result.backup_path}")
        print(f"Wiped tables: {len(result.wiped_tables)}")
        return 0
    except WipeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
