"""Flat runtime identity view retained for backend and proof checks."""

from __future__ import annotations

from typing import Any

from backend.runtime_context import build_runtime_context


def build_runtime_identity() -> dict[str, Any]:
    """Return the active DB identity and trusted-seed fingerprint status."""
    context = build_runtime_context()
    database = context["database"]
    trusted_seed = context["trusted_seed"]
    clock = context["clock"]
    proof = context["proof"]
    return {
        "context_contract_version": context["contract_version"],
        "db_mode": context["runtime"]["mode"],
        "db_path": database["path"],
        "db_path_hash": database["path_hash"],
        "process_id": context["runtime"]["process_id"],
        "schema_version": database["schema_version"],
        "seed_version": trusted_seed["seed_version"],
        "reference_date": clock["reference_date"],
        "reference_datetime": clock["reference_datetime"],
        "clock_source": clock["source"],
        "manifest_fingerprint": trusted_seed["manifest_fingerprint"],
        "live_fingerprint": database["live_fingerprint"],
        "fingerprint_match": trusted_seed["fingerprint_match"],
        "trusted_seed_ready": proof["trusted_seed_ready"],
        "proof_blocking_reasons": proof["blocking_reasons"],
    }
