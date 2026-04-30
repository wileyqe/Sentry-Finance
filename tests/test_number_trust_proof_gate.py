import json
from pathlib import Path

from scripts import run_number_trust_proof
from scripts.dummy_data.trusted_seed import TRUSTED_REFERENCE_DATE, TRUSTED_SEED_VERSION


def _manifest() -> dict:
    return {
        "seed_version": TRUSTED_SEED_VERSION,
        "reference_date": TRUSTED_REFERENCE_DATE.isoformat(),
        "database_fingerprint": "abc123",
    }


def _runtime_context(db_path: Path) -> dict:
    return {
        "contract_version": run_number_trust_proof.CONTRACT_VERSION,
        "runtime": {"mode": "trusted", "process_id": 123},
        "database": {
            "path": str(db_path.resolve()),
            "live_fingerprint": "abc123",
            "schema_version": 44,
        },
        "trusted_seed": {
            "seed_version": TRUSTED_SEED_VERSION,
            "reference_date": TRUSTED_REFERENCE_DATE.isoformat(),
            "manifest_fingerprint": "abc123",
            "fingerprint_match": True,
        },
        "proof": {"trusted_seed_ready": True, "blocking_reasons": []},
    }


def _runtime_identity() -> dict:
    return {
        "seed_version": TRUSTED_SEED_VERSION,
        "reference_date": TRUSTED_REFERENCE_DATE.isoformat(),
        "manifest_fingerprint": "abc123",
        "live_fingerprint": "abc123",
        "fingerprint_match": True,
        "trusted_seed_ready": True,
    }


def test_validate_runtime_identity_accepts_matching_trusted_context(tmp_path):
    db_path = tmp_path / "dummy.db"
    failures = run_number_trust_proof.validate_runtime_identity(
        db_path=db_path,
        manifest=_manifest(),
        context=_runtime_context(db_path),
        identity=_runtime_identity(),
    )
    assert failures == []


def test_validate_runtime_identity_reports_path_and_fingerprint_drift(tmp_path):
    db_path = tmp_path / "dummy.db"
    context = _runtime_context(tmp_path / "other.db")
    context["database"]["live_fingerprint"] = "different"

    failures = run_number_trust_proof.validate_runtime_identity(
        db_path=db_path,
        manifest=_manifest(),
        context=context,
        identity=_runtime_identity(),
    )

    assert any("runtime DB path" in failure for failure in failures)
    assert any("live fingerprint" in failure for failure in failures)


def test_final_report_records_passed_gates(tmp_path, monkeypatch):
    monkeypatch.setattr(run_number_trust_proof, "REPORT_DIR", tmp_path)
    report = {
        "status": "PASS",
        "failure": None,
        "db_path": str(tmp_path / "dummy.db"),
        "backend_url": "http://127.0.0.1:8000",
        "frontend_url": "http://127.0.0.1:1420",
        "stack": {
            "backend": {"mode": "started"},
            "frontend": {"mode": "reused"},
        },
        "runtime_context": _runtime_context(tmp_path / "dummy.db"),
        "steps": [
            {"name": "reseed trusted DB", "status": "pass", "duration_seconds": 1.0},
            {"name": "DOM/browser audit", "status": "pass", "duration_seconds": 2.0},
        ],
        "artifacts": {"api_audit_markdown": str(tmp_path / "api.md")},
    }

    json_path, md_path = run_number_trust_proof._write_final_report(report, "20260430-010203")

    assert json_path.name == "number-trust-proof-20260430-010203.json"
    assert md_path.name == "number-trust-proof-20260430-010203.md"
    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "PASS"
    md = md_path.read_text(encoding="utf-8")
    assert "All proof gates passed." in md
    assert "`pass` DOM/browser audit" in md
