"""
extractors/gmail_otp_provider.py - Gmail OAuth OTP provider for myPay.

This module is deliberately narrow: it reads recent Gmail messages through
the official Gmail API, extracts a single myPay/DFAS one-time code, and
falls back to the manual MFA bridge whenever anything is missing, ambiguous,
or unsafe. It does not store message bodies, subjects, senders, or OTPs.
"""

from __future__ import annotations

import base64
import html
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from extractors.otp_provider import ManualMFABridgeOTPProvider, OTPProvider

log = logging.getLogger("sentry.extractors.gmail_otp_provider")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CLIENT_CONFIG_PATH = (
    PROJECT_ROOT / "secrets" / "google" / "mypay_gmail_oauth_client.json"
)
DEFAULT_TOKEN_PATH = PROJECT_ROOT / "secrets" / "google" / "mypay_gmail_oauth_token.json"
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
SCOPES = (GMAIL_READONLY_SCOPE,)
KEYRING_SERVICE = "sentry-finance"
KEYRING_USERNAME = "mypay:gmail_oauth_token"

OTP_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
HTML_TAG_RE = re.compile(r"<[^>]+>")
MY_PAY_SENDER_HINTS = ("dfas", "dfas-smartdocs", "mail.mil", "mypay")
MY_PAY_BODY_HINTS = (
    "dfas",
    "mypay",
    "one-time",
    "one time",
    "pin",
    "code",
    "verification",
)

ServiceFactory = Callable[[], Any]


class GmailOTPError(RuntimeError):
    """Base exception for expected Gmail OTP provider setup/read failures."""


@dataclass(frozen=True)
class _LookupResult:
    code: str | None = None
    ambiguous: bool = False


class _LocalOAuthTokenStore:
    """Load/save OAuth token JSON from keyring, then a gitignored file."""

    def __init__(self, token_path: Path = DEFAULT_TOKEN_PATH) -> None:
        self._token_path = token_path

    def load(self) -> str | None:
        token_json = self._load_from_keyring()
        if token_json:
            return token_json
        try:
            if self._token_path.exists():
                return self._token_path.read_text(encoding="utf-8")
        except OSError as exc:
            log.info("Gmail OTP: token file could not be read; using manual fallback")
            log.debug("Gmail OTP token read failure: %s", exc)
        return None

    def save(self, token_json: str) -> None:
        if self._save_to_keyring(token_json):
            return
        try:
            self._token_path.parent.mkdir(parents=True, exist_ok=True)
            self._token_path.write_text(token_json, encoding="utf-8")
        except OSError as exc:
            raise GmailOTPError("Could not persist Gmail OAuth token") from exc

    def _load_from_keyring(self) -> str | None:
        try:
            import keyring

            return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        except Exception as exc:
            log.debug("Gmail OTP keyring load unavailable: %s", exc)
            return None

    def _save_to_keyring(self, token_json: str) -> bool:
        try:
            import keyring

            keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, token_json)
            return True
        except Exception as exc:
            log.debug("Gmail OTP keyring save unavailable: %s", exc)
            return False


class GmailOAuthOTPProvider(OTPProvider):
    """OTP provider that polls Gmail through local OAuth and falls back safely."""

    def __init__(
        self,
        *,
        fallback: OTPProvider | None = None,
        client_config_path: Path | str = DEFAULT_CLIENT_CONFIG_PATH,
        token_store: _LocalOAuthTokenStore | None = None,
        service_factory: ServiceFactory | None = None,
        gmail_poll_seconds: int | float | None = None,
        poll_interval_seconds: int | float = 5,
        max_messages: int = 10,
    ) -> None:
        self.fallback = fallback if fallback is not None else ManualMFABridgeOTPProvider()
        self.client_config_path = Path(client_config_path)
        self._token_store = token_store or _LocalOAuthTokenStore()
        self._service_factory = service_factory
        self._gmail_poll_seconds = gmail_poll_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._max_messages = max_messages

    def wait_for_code(
        self,
        institution: str,
        *,
        challenge_started_at: datetime,
        hint: str | None = None,
        timeout_seconds: int = 300,
    ) -> Optional[str]:
        if institution.lower() != "mypay":
            return self._fallback(
                institution,
                challenge_started_at=challenge_started_at,
                hint=hint,
                timeout_seconds=timeout_seconds,
            )

        started_monotonic = time.monotonic()
        try:
            service = self._service_factory() if self._service_factory else self._build_service()
            result = self._poll_for_code(
                service,
                challenge_started_at=challenge_started_at,
                hint=hint,
                timeout_seconds=timeout_seconds,
            )
        except GmailOTPError as exc:
            log.info("Gmail OTP: setup/read unavailable; using manual MFA fallback")
            log.debug("Gmail OTP setup/read failure: %s", exc)
            return self._fallback_with_remaining(
                institution,
                challenge_started_at=challenge_started_at,
                hint=hint,
                timeout_seconds=timeout_seconds,
                started_monotonic=started_monotonic,
            )
        except Exception as exc:
            log.info("Gmail OTP: unexpected read failure; using manual MFA fallback")
            log.debug("Gmail OTP unexpected failure: %s", exc)
            return self._fallback_with_remaining(
                institution,
                challenge_started_at=challenge_started_at,
                hint=hint,
                timeout_seconds=timeout_seconds,
                started_monotonic=started_monotonic,
            )

        if result.code is not None:
            log.info("Gmail OTP: captured one recent myPay code")
            return result.code

        if result.ambiguous:
            log.info("Gmail OTP: ambiguous recent myPay codes; using manual MFA fallback")
        else:
            log.info("Gmail OTP: no recent myPay code found; using manual MFA fallback")

        return self._fallback_with_remaining(
            institution,
            challenge_started_at=challenge_started_at,
            hint=hint,
            timeout_seconds=timeout_seconds,
            started_monotonic=started_monotonic,
        )

    def ensure_authorized(self) -> None:
        """Run/refresh OAuth and perform a minimal Gmail profile read."""
        service = self._build_service()
        try:
            service.users().getProfile(userId="me").execute()
        except Exception as exc:
            raise GmailOTPError("Gmail profile check failed") from exc

    def _build_service(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except Exception as exc:
            raise GmailOTPError(
                "Google Gmail OAuth dependencies are not installed"
            ) from exc

        creds = None
        token_json = self._token_store.load()
        if token_json:
            try:
                creds = Credentials.from_authorized_user_info(
                    info=_json_loads(token_json),
                    scopes=list(SCOPES),
                )
            except Exception as exc:
                log.debug("Gmail OTP token parse failed: %s", exc)
                creds = None

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._token_store.save(creds.to_json())
            except Exception as exc:
                raise GmailOTPError("Gmail OAuth token refresh failed") from exc

        if not creds or not creds.valid:
            if not self.client_config_path.exists():
                raise GmailOTPError("Gmail OAuth client configuration is missing")
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.client_config_path),
                    scopes=list(SCOPES),
                )
                creds = flow.run_local_server(port=0)
                self._token_store.save(creds.to_json())
            except Exception as exc:
                raise GmailOTPError("Gmail OAuth authorization failed") from exc

        try:
            return build("gmail", "v1", credentials=creds, cache_discovery=False)
        except Exception as exc:
            raise GmailOTPError("Gmail API client could not be built") from exc

    def _poll_for_code(
        self,
        service,
        *,
        challenge_started_at: datetime,
        hint: str | None,
        timeout_seconds: int,
    ) -> _LookupResult:
        poll_seconds = self._effective_gmail_poll_seconds(timeout_seconds)
        deadline = time.monotonic() + poll_seconds

        while True:
            result = self._find_recent_code(
                service,
                challenge_started_at=challenge_started_at,
                hint=hint,
            )
            if result.code is not None or result.ambiguous:
                return result
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return result
            time.sleep(max(0.0, min(float(self._poll_interval_seconds), remaining)))

    def _find_recent_code(
        self,
        service,
        *,
        challenge_started_at: datetime,
        hint: str | None,
    ) -> _LookupResult:
        challenge_epoch_ms = _datetime_to_epoch_ms(challenge_started_at)
        query = _gmail_query()
        try:
            listed = (
                service.users()
                .messages()
                .list(userId="me", q=query, maxResults=self._max_messages)
                .execute()
            )
        except Exception as exc:
            raise GmailOTPError("Gmail message list failed") from exc

        message_refs = listed.get("messages") or []
        codes: set[str] = set()

        for ref in message_refs:
            message_id = ref.get("id")
            if not message_id:
                continue
            try:
                message = (
                    service.users()
                    .messages()
                    .get(userId="me", id=message_id, format="full")
                    .execute()
                )
            except Exception as exc:
                raise GmailOTPError("Gmail message read failed") from exc

            if _message_epoch_ms(message) < challenge_epoch_ms:
                continue

            headers = _headers(message)
            sender = headers.get("from", "")
            subject = headers.get("subject", "")
            body = _message_text(message)
            try:
                if not _looks_like_mypay_code_message(sender, subject, body, hint):
                    continue
                codes.update(OTP_RE.findall(body))
            finally:
                body = ""

            if len(codes) > 1:
                return _LookupResult(ambiguous=True)

        if len(codes) == 1:
            return _LookupResult(code=next(iter(codes)))
        if len(codes) > 1:
            return _LookupResult(ambiguous=True)
        return _LookupResult()

    def _effective_gmail_poll_seconds(self, timeout_seconds: int) -> float:
        if self._gmail_poll_seconds is not None:
            return max(0.0, float(self._gmail_poll_seconds))
        env_value = os.environ.get("MYPAY_GMAIL_OTP_POLL_SECONDS")
        if env_value:
            try:
                return max(0.0, min(float(env_value), float(timeout_seconds)))
            except ValueError:
                log.debug("Invalid MYPAY_GMAIL_OTP_POLL_SECONDS=%r", env_value)
        return max(0.0, min(45.0, float(timeout_seconds)))

    def _fallback_with_remaining(
        self,
        institution: str,
        *,
        challenge_started_at: datetime,
        hint: str | None,
        timeout_seconds: int,
        started_monotonic: float,
    ) -> Optional[str]:
        elapsed = max(0, int(time.monotonic() - started_monotonic))
        remaining = max(1, timeout_seconds - elapsed)
        return self._fallback(
            institution,
            challenge_started_at=challenge_started_at,
            hint=hint,
            timeout_seconds=remaining,
        )

    def _fallback(
        self,
        institution: str,
        *,
        challenge_started_at: datetime,
        hint: str | None,
        timeout_seconds: int,
    ) -> Optional[str]:
        if self.fallback is None:
            return None
        return self.fallback.wait_for_code(
            institution,
            challenge_started_at=challenge_started_at,
            hint=hint,
            timeout_seconds=timeout_seconds,
        )


def _json_loads(raw: str) -> dict:
    import json

    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise ValueError("OAuth token JSON must be an object")
    return loaded


def _datetime_to_epoch_ms(value: datetime) -> int:
    if value.tzinfo is None:
        return int(value.timestamp() * 1000)
    return int(value.astimezone(timezone.utc).timestamp() * 1000)


def _message_epoch_ms(message: dict) -> int:
    try:
        return int(message.get("internalDate") or 0)
    except (TypeError, ValueError):
        return 0


def _gmail_query() -> str:
    return (
        "newer_than:1d "
        "("
        "from:DFAS-SmartDocs@mail.mil OR "
        "from:mail.mil OR "
        "from:dfas.mil OR "
        "from:mypay.dfas.mil OR "
        "subject:DFAS OR "
        "subject:myPay"
        ")"
    )


def _headers(message: dict) -> dict[str, str]:
    raw_headers = (message.get("payload") or {}).get("headers") or []
    headers: dict[str, str] = {}
    for header in raw_headers:
        name = str(header.get("name") or "").lower()
        value = str(header.get("value") or "")
        if name in {"from", "subject"}:
            headers[name] = value
    return headers


def _message_text(message: dict) -> str:
    payload = message.get("payload") or {}
    parts: list[str] = []
    _collect_payload_text(payload, parts)
    text = "\n".join(parts)
    return html.unescape(HTML_TAG_RE.sub(" ", text))


def _collect_payload_text(payload: dict, parts: list[str]) -> None:
    mime_type = str(payload.get("mimeType") or "").lower()
    body = payload.get("body") or {}
    data = body.get("data")
    if data and (not mime_type or mime_type.startswith("text/")):
        decoded = _decode_body(data)
        if decoded:
            parts.append(decoded)

    for child in payload.get("parts") or []:
        if isinstance(child, dict):
            _collect_payload_text(child, parts)


def _decode_body(data: str) -> str:
    try:
        padding = "=" * (-len(data) % 4)
        decoded = base64.urlsafe_b64decode((data + padding).encode("ascii"))
        return decoded.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _looks_like_mypay_code_message(
    sender: str,
    subject: str,
    body: str,
    hint: str | None,
) -> bool:
    sender_l = sender.lower()
    subject_l = subject.lower()
    body_l = body.lower()

    sender_hints = set(MY_PAY_SENDER_HINTS)
    if hint:
        sender_hints.add(hint.lower())

    sender_ok = any(token in sender_l for token in sender_hints)
    body_ok = any(token in subject_l or token in body_l for token in MY_PAY_BODY_HINTS)
    return sender_ok and body_ok
