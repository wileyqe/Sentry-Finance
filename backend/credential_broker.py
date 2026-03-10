"""
backend/credential_broker.py — Elevated credential retrieval via Windows
Credential Manager.

This script is designed to run as a short-lived elevated subprocess.
It reads a JSON request from stdin, retrieves credentials from Windows
Credential Manager via the `keyring` library, and writes the response
to stdout.

Security invariants:
  - NEVER logs credential values
  - NEVER writes credentials to disk
  - Exits immediately after responding
  - Runs elevated via UAC to gate access behind Windows Hello / PIN

Usage (called by ipc.py, not directly):
    echo '{"action":"get_credentials","institutions":["nfcu"]}' |
        python credential_broker.py

First-time setup:
    python credential_broker.py --store nfcu
    python credential_broker.py --store chase
"""

import argparse
import getpass
import json
import sys
import logging

log = logging.getLogger("sentry.backend.broker")

# Credential Manager target prefix
_TARGET_PREFIX = "SentryFinance:"


def _get_keyring():
    """Import keyring lazily to avoid import cost for the main process."""
    try:
        import keyring

        return keyring
    except ImportError:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": "keyring package not installed. Run: pip install keyring",
                }
            )
        )
        sys.exit(1)


def _target(institution_id: str) -> str:
    """Build the Windows Credential Manager target name."""
    return f"{_TARGET_PREFIX}{institution_id}"


def get_credentials(institution_ids: list[str]) -> dict:
    """Retrieve credentials from Windows Credential Manager.

    Returns:
        {"nfcu": {"kind": "password", "username": "...", "password": "..."}, ...}
    """
    kr = _get_keyring()
    result = {}

    for inst_id in institution_ids:
        target = _target(inst_id)

        # Try new explicitly typed JSON schema
        payload_str = kr.get_password(target, "__auth_payload__")
        if payload_str:
            try:
                payload = json.loads(payload_str)
                result[inst_id] = payload
                log.debug("Retrieved typed credentials for %s", inst_id)
                continue
            except json.JSONDecodeError:
                log.warning("Corrupt auth payload for %s", inst_id)

        # Fallback to legacy schema
        username = kr.get_password(target, "username")
        password = kr.get_password(target, "password")

        if username and password:
            if username == inst_id:
                # Stored via legacy store_url_secret()
                result[inst_id] = {
                    "kind": "token",
                    "token": password,
                    "password": password,  # Legacy fallback representation
                }
            else:
                result[inst_id] = {
                    "kind": "password",
                    "username": username,
                    "password": password,
                }
            log.debug("Retrieved legacy credentials for %s", inst_id)
        else:
            log.warning(
                "No credentials found for %s in Windows Credential Manager", inst_id
            )

    return result


def store_credentials(institution_id: str) -> None:
    """Interactive helper to store explicitly typed credentials
    in Windows Credential Manager.
    """
    kr = _get_keyring()
    target = _target(institution_id)

    print(f"\n  🔐  Store credentials for: {institution_id}")
    print(f"      Target: {target}")
    print()
    print("  Select credential type:")
    print("    1) Username and Password (Default)")
    print("    2) Phone Number (for SMS OTP)")
    print("    3) Token / URL Secret")
    print()
    choice = input("  Choice [1]: ").strip() or "1"

    payload = {}

    if choice == "2":
        payload["kind"] = "phone_otp"
        phone = input("  Phone Number: ").strip()
        if not phone:
            print("  ✗  Aborted: phone number required")
            sys.exit(1)
        payload["phone"] = phone
        payload["username"] = phone  # Fallback

    elif choice == "3":
        payload["kind"] = "token"
        token = getpass.getpass("  Secret Token / URL: ").strip()
        if not token:
            print("  ✗  Aborted: token cannot be empty")
            sys.exit(1)
        payload["token"] = token
        payload["password"] = token  # Fallback

    else:
        payload["kind"] = "password"
        username = input("  Username: ").strip()
        password = getpass.getpass("  Password: ").strip()
        if not username or not password:
            print("  ✗  Aborted: both username and password required")
            sys.exit(1)
        payload["username"] = username
        payload["password"] = password

    # Clear old legacy fields if they exist to prevent confusion
    try:
        kr.delete_password(target, "username")
    except Exception:
        pass
    try:
        kr.delete_password(target, "password")
    except Exception:
        pass

    # Store new payload
    kr.set_password(target, "__auth_payload__", json.dumps(payload))

    print(f"  ✔  {payload['kind'].upper()} credentials stored for {institution_id}")
    print("      They are now available to the Credential Broker")
    print()


def _handle_stdin_request() -> None:
    """Process a credential request from stdin (legacy / non-Windows)."""
    raw = sys.stdin.read()
    if not raw.strip():
        print(json.dumps({"status": "error", "error": "No input received"}))
        sys.exit(1)

    try:
        request = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"status": "error", "error": f"Invalid JSON: {e}"}))
        sys.exit(1)

    action = request.get("action")

    if action == "get_credentials":
        institutions = request.get("institutions", [])
        creds = get_credentials(institutions)

        missing = [i for i in institutions if i not in creds]
        if missing:
            log.warning("Missing credentials for: %s", missing)

        print(
            json.dumps(
                {
                    "status": "ok",
                    "credentials": creds,
                    "missing": missing,
                }
            )
        )
    else:
        print(json.dumps({"status": "error", "error": f"Unknown action: {action}"}))
        sys.exit(1)


def _handle_file_request(request_path: str, response_path: str) -> None:
    """Process a credential request via temp files (elevated IPC mode).

    Reads JSON request from request_path, retrieves credentials,
    writes JSON response to response_path.
    """
    from pathlib import Path

    req_file = Path(request_path)
    resp_file = Path(response_path)

    if not req_file.exists():
        resp_file.write_text(
            json.dumps(
                {"status": "error", "error": f"Request file not found: {request_path}"}
            ),
            encoding="utf-8",
        )
        sys.exit(1)

    try:
        raw = req_file.read_text(encoding="utf-8")
        request = json.loads(raw)
    except (json.JSONDecodeError, IOError) as e:
        resp_file.write_text(
            json.dumps({"status": "error", "error": f"Failed to read request: {e}"}),
            encoding="utf-8",
        )
        sys.exit(1)

    action = request.get("action")

    if action == "get_credentials":
        institutions = request.get("institutions", [])
        creds = get_credentials(institutions)

        missing = [i for i in institutions if i not in creds]
        if missing:
            log.warning("Missing credentials for: %s", missing)

        resp_file.write_text(
            json.dumps(
                {
                    "status": "ok",
                    "credentials": creds,
                    "missing": missing,
                }
            ),
            encoding="utf-8",
        )
    else:
        resp_file.write_text(
            json.dumps({"status": "error", "error": f"Unknown action: {action}"}),
            encoding="utf-8",
        )
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Sentry Finance Credential Broker")
    parser.add_argument(
        "--store",
        metavar="INSTITUTION",
        help="Interactively store credentials (password/token/OTP) for an institution",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_creds",
        help="List stored credential targets (no values shown)",
    )
    parser.add_argument(
        "--ipc-request",
        metavar="FILE",
        dest="ipc_request",
        help="Read JSON request from this file (elevated IPC mode)",
    )
    parser.add_argument(
        "--ipc-response",
        metavar="FILE",
        dest="ipc_response",
        help="Write JSON response to this file (elevated IPC mode)",
    )
    args = parser.parse_args()

    if args.store:
        store_credentials(args.store)
    elif args.list_creds:
        kr = _get_keyring()
        print("\n  📋  Stored credential targets:")
        for inst_id in [
            "nfcu",
            "chase",
            "fidelity",
            "tsp",
            "acorns",
            "affirm",
        ]:
            target = _target(inst_id)
            has_payload = kr.get_password(target, "__auth_payload__") is not None
            has_user = kr.get_password(target, "username") is not None
            has_pass = kr.get_password(target, "password") is not None

            if has_payload:
                status = "✔ (v2 payload)"
            elif has_user and has_pass:
                status = "✔ (legacy)"
            else:
                status = "✗"

            print(f"    {status}  {inst_id} ({target})")
        print()
    elif args.ipc_request and args.ipc_response:
        # Elevated IPC mode — read/write via temp files
        _handle_file_request(args.ipc_request, args.ipc_response)
    else:
        # Legacy stdin mode (for non-Windows or testing)
        _handle_stdin_request()


if __name__ == "__main__":
    main()
