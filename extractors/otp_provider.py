"""
extractors/otp_provider.py — OTP provider abstraction for connectors.

Some institutions (myPay/DFAS) deliver second-factor codes by email
rather than SMS. The current implementation is the manual MFA bridge:
the user types the code into the dashboard. Gmail OAuth automation
plugs in here when explicitly enabled.

The abstraction is intentionally small: one method,
`wait_for_code(institution, *, challenge_started_at, hint, timeout_seconds)`,
returning the code string or `None` on timeout. Connectors don't care
how the code arrived — only that they got one.

Why a separate file (and not inlined in mypay_connector.py): the manual
bridge is reused; the Gmail OAuth follow-on (P17 follow-on) replaces
exactly the provider, leaving connector login / navigation / download
logic untouched. Keeping the seam shallow now makes the swap clean.

Gmail OAuth provider notes:

  * Use least-privilege Gmail scope (gmail.readonly).
  * Persist OAuth client/token in keyring or a gitignored local file
    under `secrets/` — never committed.
  * Filter by myPay/DFAS sender + subject hints + a sliding window
    starting at `challenge_started_at`. Discard older messages.
  * Extract OTP via a tight regex over the message body; do not
    keep the body around once the code is captured.
  * Redact OTP and any account identifiers in logs.
  * Fall back to `ManualMFABridgeOTPProvider` on OAuth failure,
    no matching email, ambiguous (>1) codes, or timeout.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

log = logging.getLogger("sentry.extractors.otp_provider")


class OTPProvider(ABC):
    """Abstract source of one-time passcodes for a connector."""

    @abstractmethod
    def wait_for_code(
        self,
        institution: str,
        *,
        challenge_started_at: datetime,
        hint: str | None = None,
        timeout_seconds: int = 300,
    ) -> Optional[str]:
        """Block until a code is available or the timeout elapses.

        Args:
            institution: e.g. "mypay" — used to scope the request and
                (in providers that filter by sender) to pick the right
                inbox window.
            challenge_started_at: When the connector triggered the
                second-factor send. Email/inbox-based providers must
                ignore messages older than this to avoid replaying a
                previous code.
            hint: Provider-specific hint for filtering (e.g.
                "dfas.mil"). May be ignored.
            timeout_seconds: Max time to wait before returning None.

        Returns the code as a string, or None on timeout / failure.
        Implementations MUST NOT raise on timeout — return None so the
        connector can record a clean error state.
        """
        ...


class ManualMFABridgeOTPProvider(OTPProvider):
    """Provider backed by the dashboard MFA bridge.

    Routes through the existing `backend.mfa_bridge.wait_for_code`
    pathway and broadcasts the `MFA_REQUIRED` SSE topic so the frontend
    MFA modal opens. The user types the code into the dashboard; the
    bridge unblocks and we return it to the connector.
    """

    def wait_for_code(
        self,
        institution: str,
        *,
        challenge_started_at: datetime,
        hint: str | None = None,
        timeout_seconds: int = 300,
    ) -> Optional[str]:
        # Local imports keep this module importable without FastAPI
        # being initialized (tests can stub the backend events bus).
        from backend.events import broadcast_event
        from backend import sse_topics
        from backend.mfa_bridge import wait_for_code as _bridge_wait

        prompt = (
            f"Enter your {institution} verification code to continue."
            if not hint
            else f"Enter the {hint} verification code from your email."
        )
        broadcast_event(
            sse_topics.MFA_REQUIRED,
            {"institution": institution, "prompt": prompt},
        )
        log.info(
            "OTP bridge: awaiting %s code via dashboard (timeout=%ds)",
            institution,
            timeout_seconds,
        )
        # The bridge already redacts the code itself in its log line;
        # do NOT log `code` here.
        return _bridge_wait(institution, timeout_seconds=timeout_seconds)


def default_provider() -> OTPProvider:
    """Return the OTP provider used when the connector doesn't override.

    Manual remains the default. Gmail OAuth is opt-in via
    `MYPAY_OTP_PROVIDER=gmail` so missing local OAuth setup never
    surprises connector runs.
    """
    provider_name = (
        os.environ.get("MYPAY_OTP_PROVIDER")
        or os.environ.get("SENTRY_MYPAY_OTP_PROVIDER")
        or ""
    ).strip().lower()
    if provider_name == "gmail":
        try:
            from extractors.gmail_otp_provider import GmailOAuthOTPProvider

            return GmailOAuthOTPProvider(fallback=ManualMFABridgeOTPProvider())
        except Exception as exc:
            log.warning(
                "Gmail OTP provider unavailable; falling back to manual MFA: %s",
                exc,
            )
    return ManualMFABridgeOTPProvider()
