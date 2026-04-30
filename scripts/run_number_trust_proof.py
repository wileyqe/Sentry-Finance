"""One-command proof gate for trusted synthetic number trust.

The gate reseeds the canonical trusted database, proves the running backend is
attached to that exact database/fingerprint, runs the API and DOM number-trust
audits, then runs the required build/test checks. It writes a final promoted
proof report under docs/audits/number-trust/reports.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.runtime_context import CONTRACT_VERSION  # noqa: E402
from scripts.dummy_data.trusted_seed import (  # noqa: E402
    TRUSTED_REFERENCE_DATE,
    TRUSTED_SEED_VERSION,
)

REPORT_DIR = ROOT / "docs" / "audits" / "number-trust" / "reports"
DEFAULT_DB_PATH = ROOT / "data" / "dummy.db"
DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
DEFAULT_FRONTEND_URL = "http://127.0.0.1:1420"


class ProofFailure(RuntimeError):
    """Raised when a required proof gate fails."""


@dataclass
class ManagedProcess:
    name: str
    process: subprocess.Popen[str]
    log_path: Path
    log_handle: Any


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def _tail(text: str, limit: int = 3000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def _proof_env(db_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["SENTRY_DB_PATH"] = str(db_path.resolve())
    env["SENTRY_DB_MODE"] = "trusted"
    env.pop("SENTRY_REFERENCE_DATE", None)
    env.pop("SENTRY_REFERENCE_DATETIME", None)
    return env


def _npm_command() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def _url_json(url: str, timeout: float = 3.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except (OSError, urllib.error.URLError):
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def _url_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 500
    except (OSError, urllib.error.URLError):
        return False


def _run_command(
    *,
    name: str,
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    steps: list[dict[str, Any]],
) -> subprocess.CompletedProcess[str]:
    started = time.monotonic()
    proc = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    duration = time.monotonic() - started
    step = {
        "name": name,
        "status": "pass" if proc.returncode == 0 else "fail",
        "command": command,
        "cwd": str(cwd),
        "returncode": proc.returncode,
        "duration_seconds": round(duration, 2),
        "stdout_tail": _tail(proc.stdout),
        "stderr_tail": _tail(proc.stderr),
    }
    steps.append(step)
    if proc.returncode != 0:
        raise ProofFailure(f"{name} failed with exit code {proc.returncode}")
    return proc


def _extract_report_path(output: str, label: str) -> str | None:
    prefix = f"{label}:"
    for line in output.splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return None


def _wait_for(
    *,
    name: str,
    predicate: Any,
    timeout_seconds: int,
    process: ManagedProcess | None = None,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process and process.process.poll() is not None:
            raise ProofFailure(
                f"{name} exited early with code {process.process.returncode}; "
                f"see {_display_path(process.log_path)}"
            )
        if predicate():
            return
        time.sleep(1)
    raise ProofFailure(f"Timed out waiting for {name}")


def _start_process(
    *,
    name: str,
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    report_stamp: str,
) -> ManagedProcess:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    log_path = REPORT_DIR / f"number-trust-proof-{report_stamp}-{name}.log"
    log_handle = log_path.open("w", encoding="utf-8")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    proc = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=creationflags,
    )
    return ManagedProcess(name=name, process=proc, log_path=log_path, log_handle=log_handle)


def _stop_process(process: ManagedProcess) -> None:
    if process.process.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            process.process.terminate()
            try:
                process.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.process.kill()
                process.process.wait(timeout=10)
    process.log_handle.close()


def _ensure_backend(
    *,
    backend_url: str,
    env: dict[str, str],
    report_stamp: str,
    started: list[ManagedProcess],
    stack: dict[str, Any],
    steps: list[dict[str, Any]],
    timeout_seconds: int,
) -> None:
    started_at = time.monotonic()
    context_url = f"{backend_url.rstrip('/')}/api/runtime/context"
    if _url_json(context_url):
        stack["backend"] = {"mode": "reused", "url": backend_url}
        steps.append({
            "name": "backend stack",
            "status": "pass",
            "mode": "reused",
            "url": backend_url,
            "duration_seconds": round(time.monotonic() - started_at, 2),
        })
        return

    process = _start_process(
        name="backend",
        command=[sys.executable, str(ROOT / "backend" / "api_server.py")],
        cwd=ROOT,
        env=env,
        report_stamp=report_stamp,
    )
    started.append(process)
    stack["backend"] = {
        "mode": "started",
        "url": backend_url,
        "pid": process.process.pid,
        "log": str(process.log_path),
    }
    _wait_for(
        name="backend runtime context",
        predicate=lambda: _url_json(context_url) is not None,
        timeout_seconds=timeout_seconds,
        process=process,
    )
    steps.append({
        "name": "backend stack",
        "status": "pass",
        "mode": "started",
        "url": backend_url,
        "duration_seconds": round(time.monotonic() - started_at, 2),
        "log": str(process.log_path),
    })


def _ensure_frontend(
    *,
    frontend_url: str,
    env: dict[str, str],
    report_stamp: str,
    started: list[ManagedProcess],
    stack: dict[str, Any],
    steps: list[dict[str, Any]],
    timeout_seconds: int,
) -> None:
    started_at = time.monotonic()
    if _url_ok(frontend_url):
        stack["frontend"] = {"mode": "reused", "url": frontend_url}
        steps.append({
            "name": "frontend stack",
            "status": "pass",
            "mode": "reused",
            "url": frontend_url,
            "duration_seconds": round(time.monotonic() - started_at, 2),
        })
        return

    process = _start_process(
        name="frontend",
        command=[_npm_command(), "run", "dev", "--", "--host", "127.0.0.1"],
        cwd=ROOT / "frontend",
        env=env,
        report_stamp=report_stamp,
    )
    started.append(process)
    stack["frontend"] = {
        "mode": "started",
        "url": frontend_url,
        "pid": process.process.pid,
        "log": str(process.log_path),
    }
    _wait_for(
        name="frontend dev server",
        predicate=lambda: _url_ok(frontend_url),
        timeout_seconds=timeout_seconds,
        process=process,
    )
    steps.append({
        "name": "frontend stack",
        "status": "pass",
        "mode": "started",
        "url": frontend_url,
        "duration_seconds": round(time.monotonic() - started_at, 2),
        "log": str(process.log_path),
    })


def _load_manifest(db_path: Path) -> dict[str, Any]:
    manifest_path = ROOT / "data" / "trusted_seed_manifest.json"
    if not manifest_path.exists():
        raise ProofFailure(f"Trusted seed manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_path = DEFAULT_DB_PATH.resolve()
    if db_path.resolve() == expected_path:
        return manifest
    return manifest


def validate_runtime_identity(
    *,
    db_path: Path,
    manifest: dict[str, Any],
    context: dict[str, Any],
    identity: dict[str, Any],
) -> list[str]:
    """Return identity mismatch descriptions for the proof report."""

    expected_path = str(db_path.resolve()).lower()
    context_path = str(Path(context["database"]["path"]).resolve()).lower()
    expected_fingerprint = manifest.get("database_fingerprint")
    failures: list[str] = []

    checks = [
        ("runtime contract", context.get("contract_version"), CONTRACT_VERSION),
        ("runtime mode", context.get("runtime", {}).get("mode"), "trusted"),
        ("runtime DB path", context_path, expected_path),
        ("seed version", context.get("trusted_seed", {}).get("seed_version"), TRUSTED_SEED_VERSION),
        (
            "reference date",
            context.get("trusted_seed", {}).get("reference_date"),
            TRUSTED_REFERENCE_DATE.isoformat(),
        ),
        (
            "manifest fingerprint",
            context.get("trusted_seed", {}).get("manifest_fingerprint"),
            expected_fingerprint,
        ),
        (
            "live fingerprint",
            context.get("database", {}).get("live_fingerprint"),
            expected_fingerprint,
        ),
        ("fingerprint match", context.get("trusted_seed", {}).get("fingerprint_match"), True),
        ("trusted seed ready", context.get("proof", {}).get("trusted_seed_ready"), True),
        ("identity seed version", identity.get("seed_version"), TRUSTED_SEED_VERSION),
        ("identity reference date", identity.get("reference_date"), TRUSTED_REFERENCE_DATE.isoformat()),
        ("identity manifest fingerprint", identity.get("manifest_fingerprint"), expected_fingerprint),
        ("identity live fingerprint", identity.get("live_fingerprint"), expected_fingerprint),
        ("identity fingerprint match", identity.get("fingerprint_match"), True),
        ("identity ready", identity.get("trusted_seed_ready"), True),
    ]
    for label, actual, expected in checks:
        if actual != expected:
            failures.append(f"{label}: expected {expected!r}, got {actual!r}")
    if context.get("proof", {}).get("blocking_reasons"):
        failures.append(f"blocking reasons: {context['proof']['blocking_reasons']!r}")
    return failures


def _verify_runtime_identity(
    *,
    db_path: Path,
    backend_url: str,
    manifest: dict[str, Any],
    steps: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.monotonic()
    context = _url_json(f"{backend_url.rstrip('/')}/api/runtime/context")
    identity = _url_json(f"{backend_url.rstrip('/')}/api/runtime/identity")
    if context is None or identity is None:
        raise ProofFailure("Backend runtime identity endpoints are not reachable")
    failures = validate_runtime_identity(
        db_path=db_path,
        manifest=manifest,
        context=context,
        identity=identity,
    )
    steps.append({
        "name": "runtime identity",
        "status": "pass" if not failures else "fail",
        "duration_seconds": round(time.monotonic() - started, 2),
        "checks": {
            "db_path": context.get("database", {}).get("path"),
            "seed_version": context.get("trusted_seed", {}).get("seed_version"),
            "reference_date": context.get("trusted_seed", {}).get("reference_date"),
            "manifest_fingerprint": context.get("trusted_seed", {}).get("manifest_fingerprint"),
            "live_fingerprint": context.get("database", {}).get("live_fingerprint"),
            "trusted_seed_ready": context.get("proof", {}).get("trusted_seed_ready"),
        },
        "failures": failures,
    })
    if failures:
        raise ProofFailure("Runtime identity check failed")
    return context, identity


def _write_final_report(report: dict[str, Any], report_stamp: str) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORT_DIR / f"number-trust-proof-{report_stamp}.json"
    md_path = REPORT_DIR / f"number-trust-proof-{report_stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    runtime = report.get("runtime_context") or {}
    trusted_seed = runtime.get("trusted_seed") or {}
    database = runtime.get("database") or {}
    lines = [
        "# Number Trust Proof Gate",
        "",
        f"- Status: `{report['status']}`",
        f"- Database: `{report['db_path']}`",
        f"- Seed version: `{trusted_seed.get('seed_version')}`",
        f"- Reference date: `{trusted_seed.get('reference_date')}`",
        f"- Manifest fingerprint: `{trusted_seed.get('manifest_fingerprint')}`",
        f"- Live fingerprint: `{database.get('live_fingerprint')}`",
        f"- Runtime trusted seed ready: `{(runtime.get('proof') or {}).get('trusted_seed_ready')}`",
        f"- Backend: `{report['stack'].get('backend', {}).get('mode')}` at `{report['backend_url']}`",
        f"- Frontend: `{report['stack'].get('frontend', {}).get('mode')}` at `{report['frontend_url']}`",
        "",
        "## Gates",
        "",
    ]
    for step in report["steps"]:
        duration = step.get("duration_seconds")
        duration_text = f" ({duration}s)" if duration is not None else ""
        lines.append(f"- `{step['status']}` {step['name']}{duration_text}")
    lines.extend(["", "## Artifacts", ""])
    artifacts = report.get("artifacts") or {}
    for label, path in artifacts.items():
        if path:
            lines.append(f"- {label}: `{_display_path(Path(path))}`")
    if report.get("failure"):
        lines.extend(["", "## Failure", "", report["failure"], ""])
    else:
        lines.extend(["", "All proof gates passed.", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def run_proof(args: argparse.Namespace, report_stamp: str | None = None) -> dict[str, Any]:
    report_stamp = report_stamp or _stamp()
    db_path = args.db.resolve()
    env = _proof_env(db_path)
    steps: list[dict[str, Any]] = []
    started_processes: list[ManagedProcess] = []
    stack: dict[str, Any] = {}
    artifacts: dict[str, str | None] = {}
    runtime_context: dict[str, Any] | None = None
    runtime_identity: dict[str, Any] | None = None
    status = "PASS"
    failure: str | None = None

    try:
        seed_proc = _run_command(
            name="reseed trusted DB",
            command=[sys.executable, str(ROOT / "scripts" / "seed_dummy_data.py")],
            cwd=ROOT,
            env=env,
            timeout=args.seed_timeout,
            steps=steps,
        )
        if "database_fingerprint" not in seed_proc.stdout + seed_proc.stderr:
            raise ProofFailure("Seeder completed but did not print a database fingerprint")

        manifest = _load_manifest(db_path)

        _ensure_backend(
            backend_url=args.backend_url,
            env=env,
            report_stamp=report_stamp,
            started=started_processes,
            stack=stack,
            steps=steps,
            timeout_seconds=args.stack_timeout,
        )
        _ensure_frontend(
            frontend_url=args.frontend_url,
            env=env,
            report_stamp=report_stamp,
            started=started_processes,
            stack=stack,
            steps=steps,
            timeout_seconds=args.stack_timeout,
        )

        runtime_context, runtime_identity = _verify_runtime_identity(
            db_path=db_path,
            backend_url=args.backend_url,
            manifest=manifest,
            steps=steps,
        )

        api_proc = _run_command(
            name="API/oracle audit",
            command=[sys.executable, str(ROOT / "scripts" / "audit_number_trust.py"), "--db", str(db_path)],
            cwd=ROOT,
            env=env,
            timeout=args.audit_timeout,
            steps=steps,
        )
        artifacts["api_audit_markdown"] = _extract_report_path(api_proc.stdout, "Markdown report")
        artifacts["api_audit_json"] = _extract_report_path(api_proc.stdout, "JSON report")

        dom_proc = _run_command(
            name="DOM/browser audit",
            command=[
                sys.executable,
                str(ROOT / "scripts" / "audit_number_trust_dom.py"),
                "--db",
                str(db_path),
                "--frontend-url",
                args.frontend_url,
                "--timeout-ms",
                str(args.dom_timeout_ms),
                "--settle-ms",
                str(args.dom_settle_ms),
            ],
            cwd=ROOT,
            env=env,
            timeout=args.dom_command_timeout,
            steps=steps,
        )
        artifacts["dom_audit_markdown"] = _extract_report_path(dom_proc.stdout, "Markdown report")
        artifacts["dom_audit_json"] = _extract_report_path(dom_proc.stdout, "JSON report")

        _run_command(
            name="frontend build",
            command=[_npm_command(), "run", "build"],
            cwd=ROOT / "frontend",
            env=env,
            timeout=args.build_timeout,
            steps=steps,
        )
        _run_command(
            name="audit vocabulary tests",
            command=[sys.executable, "-m", "pytest", "tests/test_audit_vocabulary.py", "-q"],
            cwd=ROOT,
            env=env,
            timeout=args.test_timeout,
            steps=steps,
        )
        _run_command(
            name="trusted seed tests",
            command=[sys.executable, "-m", "pytest", "tests/test_trusted_seed.py", "-q"],
            cwd=ROOT,
            env=env,
            timeout=args.trusted_seed_test_timeout,
            steps=steps,
        )
    except Exception as exc:
        status = "FAIL"
        failure = str(exc)
    finally:
        if not args.keep_started_stack:
            for process in reversed(started_processes):
                _stop_process(process)

    return {
        "status": status,
        "failure": failure,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "db_path": str(db_path),
        "backend_url": args.backend_url,
        "frontend_url": args.frontend_url,
        "stack": stack,
        "runtime_context": runtime_context,
        "runtime_identity": runtime_identity,
        "steps": steps,
        "artifacts": artifacts,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full trusted number-trust proof gate")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--frontend-url", default=DEFAULT_FRONTEND_URL)
    parser.add_argument("--keep-started-stack", action="store_true")
    parser.add_argument("--stack-timeout", type=int, default=90)
    parser.add_argument("--seed-timeout", type=int, default=240)
    parser.add_argument("--audit-timeout", type=int, default=180)
    parser.add_argument("--dom-command-timeout", type=int, default=240)
    parser.add_argument("--dom-timeout-ms", type=int, default=20_000)
    parser.add_argument("--dom-settle-ms", type=int, default=1_000)
    parser.add_argument("--build-timeout", type=int, default=180)
    parser.add_argument("--test-timeout", type=int, default=120)
    parser.add_argument("--trusted-seed-test-timeout", type=int, default=480)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report_stamp = _stamp()
    report = run_proof(args, report_stamp=report_stamp)
    json_path, md_path = _write_final_report(report, report_stamp)
    print(f"JSON proof report: {json_path}")
    print(f"Markdown proof report: {md_path}")
    print(f"Proof status: {report['status']}")
    if report["failure"]:
        print(f"Failure: {report['failure']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
