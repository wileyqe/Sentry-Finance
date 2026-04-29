"""Runtime database identity helpers for backend and proof checks."""

from __future__ import annotations

import os
from typing import Any

from dal.connection import db_mode, get_db, resolve_db_path
from dal.trusted_seed_manifest import live_seed_fingerprint, load_manifest


def build_runtime_identity() -> dict[str, Any]:
    """Return the active DB identity and trusted-seed fingerprint status."""
    resolved_path = resolve_db_path().resolve()
    with get_db(resolved_path) as conn:
        schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
        manifest = load_manifest(conn)
        live = live_seed_fingerprint(conn)

    manifest_fingerprint = (manifest or {}).get("database_fingerprint")
    live_fingerprint = live["database_fingerprint"]
    return {
        "db_mode": db_mode(),
        "db_path": str(resolved_path),
        "process_id": os.getpid(),
        "schema_version": schema_version,
        "seed_version": (manifest or {}).get("seed_version"),
        "reference_date": (manifest or {}).get("reference_date"),
        "manifest_fingerprint": manifest_fingerprint,
        "live_fingerprint": live_fingerprint,
        "fingerprint_match": bool(
            manifest_fingerprint and manifest_fingerprint == live_fingerprint
        ),
    }
