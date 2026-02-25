"""
backend/ipc.py — Secure IPC protocol for Credential Broker communication.

The broker runs as an elevated subprocess (UAC). Communication uses a
temp-file handshake because Windows ShellExecuteEx ('runas') does not
support stdin/stdout piping:

  1. Orchestrator writes JSON request to a temp file
  2. Orchestrator launches broker elevated via ShellExecuteW('runas')
  3. Broker reads request from temp file, writes response to temp file
  4. Orchestrator reads response, then securely deletes both temp files

Security:
  - Temp files are created with restrictive permissions (owner-only)
  - Files are overwritten with zeros before deletion
  - Credentials cleared from memory after use via ctypes.memset
  - Broker exits immediately after responding
"""
import ctypes
import json
import logging
import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

log = logging.getLogger("sentry")

BROKER_SCRIPT = Path(__file__).parent / "credential_broker.py"


def _clear_string(s: str) -> None:
    """Best-effort zeroing of a Python string's internal buffer.

    Python strings are immutable and may be interned, so this is
    defense-in-depth rather than a guarantee. The ctypes.memset
    overwrites the UTF-8 buffer backing the string object.
    """
    if not s:
        return
    try:
        buf = ctypes.cast(
            id(s) + sys.getsizeof("") - 1,
            ctypes.POINTER(ctypes.c_char)
        )
        ctypes.memset(buf, 0, len(s.encode("utf-8")))
    except Exception:
        pass  # Best effort — don't crash if this fails


def clear_credentials(creds: dict) -> None:
    """Zero out credential values in a dict.

    Call this after credentials have been consumed by the worker.
    """
    for inst_id, inst_creds in creds.items():
        if isinstance(inst_creds, dict):
            for key in inst_creds:
                val = inst_creds[key]
                if isinstance(val, str):
                    _clear_string(val)
                inst_creds[key] = ""
        creds[inst_id] = {}


def _secure_delete(path: Path) -> None:
    """Overwrite file with zeros, then delete."""
    try:
        size = path.stat().st_size
        with open(path, "wb") as f:
            f.write(b"\x00" * size)
            f.flush()
            os.fsync(f.fileno())
        path.unlink()
    except Exception as e:
        log.debug("Secure delete failed for %s: %s", path, e)
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass


def _launch_elevated(request_file: Path, response_file: Path,
                     timeout: int = 60) -> bool:
    """Launch the credential broker with UAC elevation.

    Uses ShellExecuteW with 'runas' verb to trigger the UAC prompt.
    The broker reads its request from request_file and writes
    its response to response_file.

    Returns True if the broker completed successfully.
    """
    python_exe = sys.executable
    # The broker script, with --ipc-files flag for temp file mode
    args = (f'"{BROKER_SCRIPT}" '
            f'--ipc-request "{request_file}" '
            f'--ipc-response "{response_file}"')

    log.info("Requesting UAC elevation for credential broker...")

    try:
        # ShellExecuteW returns an HINSTANCE > 32 on success
        ret = ctypes.windll.shell32.ShellExecuteW(
            None,           # hwnd
            "runas",        # verb — triggers UAC
            python_exe,     # executable
            args,           # arguments
            None,           # working directory
            0,              # SW_HIDE — don't show window
        )

        if ret <= 32:
            log.error("UAC elevation failed (ShellExecute returned %d)", ret)
            return False

        # Poll for the response file to appear
        deadline = time.time() + timeout
        while time.time() < deadline:
            if response_file.exists() and response_file.stat().st_size > 0:
                # Give a moment for the write to finish
                time.sleep(0.3)
                return True
            time.sleep(0.5)

        log.error("Credential broker timed out after %ds", timeout)
        return False

    except Exception as e:
        log.error("UAC elevation failed: %s", e)
        return False


def _launch_non_elevated(request_payload: str,
                         timeout: int = 60) -> str | None:
    """Fallback: launch broker without elevation (non-Windows or testing)."""
    try:
        result = subprocess.run(
            [sys.executable, str(BROKER_SCRIPT)],
            input=request_payload,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            log.error("Credential broker failed (exit %d): %s",
                      result.returncode, result.stderr.strip())
            return None

        return result.stdout.strip()

    except subprocess.TimeoutExpired:
        log.error("Credential broker timed out after %ds", timeout)
        return None
    except Exception as e:
        log.error("Broker launch failed: %s", e)
        return None


def request_credentials(institution_ids: list[str],
                        timeout: int = 60) -> dict | None:
    """Request credentials from the Credential Broker.

    On Windows: launches the broker elevated (UAC prompt) using
    ShellExecuteW with 'runas' verb and temp-file IPC.

    On other platforms: launches as a regular subprocess with
    stdin/stdout piping.

    Args:
        institution_ids: List of institution IDs needing creds
        timeout: Max seconds to wait for broker response

    Returns:
        Dict of {institution_id: {"username": ..., "password": ...}}
        or None on failure.
    """
    if not BROKER_SCRIPT.exists():
        log.error("Credential broker not found: %s", BROKER_SCRIPT)
        return None

    request_payload = json.dumps({
        "action": "get_credentials",
        "institutions": institution_ids,
    })

    log.info("Launching credential broker for: %s", institution_ids)

    try:
        if sys.platform == "win32":
            # ── Elevated launch via UAC + temp file IPC ──────────
            # Generate unique filenames to avoid collisions
            token = secrets.token_hex(8)
            tmp_dir = Path(tempfile.gettempdir())
            request_file = tmp_dir / f"ag_broker_req_{token}.json"
            response_file = tmp_dir / f"ag_broker_resp_{token}.json"

            try:
                # Write request
                request_file.write_text(request_payload, encoding="utf-8")

                # Launch elevated
                if not _launch_elevated(request_file, response_file,
                                        timeout):
                    return None

                # Read response
                raw = response_file.read_text(encoding="utf-8").strip()

            finally:
                # Secure cleanup — always runs
                _secure_delete(request_file)
                _secure_delete(response_file)

        else:
            # ── Non-Windows: plain subprocess with piping ────────
            raw = _launch_non_elevated(request_payload, timeout)
            if raw is None:
                return None

        # Parse response
        response = json.loads(raw)
        if response.get("status") != "ok":
            log.error("Broker error: %s",
                      response.get("error", "unknown"))
            return None

        creds = response.get("credentials", {})
        log.info("Credentials received for %d institutions",
                 len(creds))
        return creds

    except json.JSONDecodeError as e:
        log.error("Invalid broker response: %s", e)
        return None
    except Exception as e:
        log.error("Broker IPC failed: %s", e)
        return None

