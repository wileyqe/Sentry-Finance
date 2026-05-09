"""
Bootstrap local Gmail OAuth for the myPay OTP provider.

Run this after saving the OAuth desktop-client JSON at:

    secrets/google/mypay_gmail_oauth_client.json

The resulting refresh token is stored in the OS keyring when available, or in
the gitignored file secrets/google/mypay_gmail_oauth_token.json.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extractors.gmail_otp_provider import (
    DEFAULT_CLIENT_CONFIG_PATH,
    DEFAULT_TOKEN_PATH,
    GMAIL_READONLY_SCOPE,
    GmailOAuthOTPProvider,
)


def main() -> int:
    provider = GmailOAuthOTPProvider(fallback=None)
    provider.ensure_authorized()
    print("Gmail OAuth is ready for myPay OTP capture.")
    print(f"Scope: {GMAIL_READONLY_SCOPE}")
    print(f"Client JSON: {DEFAULT_CLIENT_CONFIG_PATH}")
    print(f"Token fallback file: {DEFAULT_TOKEN_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
