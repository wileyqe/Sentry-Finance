"""Runtime context contract for backend, frontend, and proof tooling."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from dal.clock import reference_clock_context
from dal.connection import db_mode, get_db, resolve_db_path
from dal.trusted_seed_manifest import live_seed_fingerprint, load_manifest

CONTRACT_VERSION = "runtime-context-v1"
TRUSTED_CLOCK_SOURCE = "trusted_seed_manifest"
TRUSTED_MODE = "trusted"


def build_runtime_context() -> dict[str, Any]:
    """Return the backend runtime context used by UI and proof checks."""
    resolved_path = resolve_db_path().resolve()
    mode = db_mode()

    with get_db(resolved_path) as conn:
        schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
        manifest = load_manifest(conn)
        live = live_seed_fingerprint(conn)
        clock = reference_clock_context(conn)

    live_fingerprint = live["database_fingerprint"]
    manifest_fingerprint = (manifest or {}).get("database_fingerprint")
    fingerprint_match = bool(
        manifest_fingerprint and manifest_fingerprint == live_fingerprint
    )
    blocking_reasons = _trusted_seed_blocking_reasons(
        mode=mode,
        manifest=manifest,
        fingerprint_match=fingerprint_match,
        clock_source=clock["source"],
    )

    return {
        "contract_version": CONTRACT_VERSION,
        "runtime": {
            "mode": mode,
            "process_id": os.getpid(),
        },
        "database": {
            "path": str(resolved_path),
            "path_hash": _path_hash(resolved_path),
            "schema_version": schema_version,
            "live_fingerprint": live_fingerprint,
        },
        "trusted_seed": {
            "present": manifest is not None,
            "seed_version": (manifest or {}).get("seed_version"),
            "end_date": (manifest or {}).get("end_date"),
            "reference_date": (manifest or {}).get("reference_date"),
            "reference_datetime": (manifest or {}).get("reference_datetime"),
            "years": (manifest or {}).get("years"),
            "generated_at": (manifest or {}).get("generated_at"),
            "manifest_fingerprint": manifest_fingerprint,
            "fingerprint_match": fingerprint_match,
        },
        "clock": clock,
        "proof": {
            "trusted_seed_ready": not blocking_reasons,
            "blocking_reasons": blocking_reasons,
        },
    }


def _path_hash(path: Path) -> str:
    return hashlib.sha256(str(path).lower().encode("utf-8")).hexdigest()


def _trusted_seed_blocking_reasons(
    *,
    mode: str,
    manifest: dict[str, Any] | None,
    fingerprint_match: bool,
    clock_source: str,
) -> list[str]:
    reasons: list[str] = []
    if mode != TRUSTED_MODE:
        reasons.append("runtime_mode_not_trusted")
    if manifest is None:
        reasons.append("trusted_seed_manifest_missing")
    elif not fingerprint_match:
        reasons.append("trusted_seed_fingerprint_mismatch")
    if manifest is not None and clock_source != TRUSTED_CLOCK_SOURCE:
        reasons.append(f"reference_clock_source:{clock_source}")
    return reasons
