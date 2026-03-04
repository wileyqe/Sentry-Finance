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

The --store-url mode stores a single URL/token secret (not username+password).
The value is stored as the 'password' field under the institution's keyring target.
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
        {"nfcu": {"username": "...", "password": "..."}, ...}
    """
    kr = _get_keyring()
    result = {}

    for inst_id in institution_ids:
        target = _target(inst_id)
        username = kr.get_password(target, "username")
        password = kr.get_password(target, "password")

        if username and password:
            result[inst_id] = {
                "username": username,
                "password": password,
            }
            log.debug("Retrieved credentials for %s", inst_id)
        else:
            log.warning(
                "No credentials found for %s in Windows Credential Manager", inst_id
            )

    return result


def store_credentials(institution_id: str) -> None:
    """Interactive helper to store username+password in Windows Credential
    Manager.

    Prompts for username and password, then stores them under the
    Antigravity: target prefix.
    """
    kr = _get_keyring()
    target = _target(institution_id)

    print(f"\n  🔐  Store credentials for: {institution_id}")
    print(f"      Target: {target}")
    print()

    username = input("  Username: ").strip()
    password = getpass.getpass("  Password: ").strip()

    if not username or not password:
        print("  ✗  Aborted: both username and password required")
        sys.exit(1)

    kr.set_password(target, "username", username)
    kr.set_password(target, "password", password)

    print(f"  ✔  Credentials stored for {institution_id}")
    print(f"      They are now available to the Credential Broker")
    print()


def store_url_secret(institution_id: str) -> None:
    """Interactive helper to store a single URL/token secret.

    Used for services where the secret is a single access URL or token
    (not username+password). Stored as the 'password' field under the
    institution's keyring target.

    Usage:
        python credential_broker.py --store-url <institution>
    """
    kr = _get_keyring()
    target = _target(institution_id)

    print(f"\n  🔐  Store URL secret for: {institution_id}")
    print(f"      Target: {target}")
    print(f"      (The value will be stored as the 'password' field)")
    print()

    secret = getpass.getpass("  Secret URL / Token: ").strip()

    if not secret:
        print("  ✗  Aborted: secret cannot be empty")
        sys.exit(1)

    # Store with a sentinel username so get_credentials() can find it
    kr.set_password(target, "username", institution_id)
    kr.set_password(target, "password", secret)

    print(f"  ✔  Secret stored for {institution_id}")
    print(
        f"      Retrieve via: credential_broker.get_credentials(['{institution_id}'])"
    )
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
        help="Interactively store username+password for an institution",
    )
    parser.add_argument(
        "--store-url",
        metavar="INSTITUTION",
        dest="store_url",
        help="Store a single URL/token secret for an institution",
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

    if args.store_url:
        store_url_secret(args.store_url)
    elif args.store:
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
            has_user = kr.get_password(target, "username") is not None
            has_pass = kr.get_password(target, "password") is not None
            status = "✔" if (has_user and has_pass) else "✗"
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
