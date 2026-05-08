from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from extractors.gmail_otp_provider import (
    DEFAULT_GMAIL_POLL_SECONDS,
    GmailOAuthOTPProvider,
)
from extractors.otp_provider import ManualMFABridgeOTPProvider, default_provider


class _Execute:
    def __init__(self, value):
        self._value = value

    def execute(self):
        return self._value


class _FakeMessages:
    def __init__(self, messages: dict[str, dict], calls: list[dict]):
        self._messages = messages
        self._calls = calls

    def list(self, **kwargs):
        self._calls.append({"method": "list", "kwargs": kwargs})
        return _Execute({"messages": [{"id": msg_id} for msg_id in self._messages]})

    def get(self, **kwargs):
        self._calls.append({"method": "get", "kwargs": kwargs})
        return _Execute(self._messages[kwargs["id"]])


class _FakeUsers:
    def __init__(self, messages: _FakeMessages):
        self._messages = messages

    def messages(self):
        return self._messages


class _FakeGmailService:
    def __init__(self, messages: dict[str, dict]):
        self.calls: list[dict] = []
        self._messages = _FakeMessages(messages, self.calls)
        self._users = _FakeUsers(self._messages)

    def users(self):
        return self._users


class _Fallback:
    def __init__(self, code: str | None = "manual-code"):
        self.code = code
        self.calls: list[dict] = []

    def wait_for_code(
        self,
        institution,
        *,
        challenge_started_at,
        hint=None,
        timeout_seconds=300,
    ):
        self.calls.append(
            {
                "institution": institution,
                "challenge_started_at": challenge_started_at,
                "hint": hint,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.code


class _EmptyTokenStore:
    def load(self):
        return None

    def save(self, _token_json: str) -> None:
        raise AssertionError("token save should not run in config-failure path")


def _message(
    *,
    when: datetime,
    sender: str = "myPay <noreply@dfas.mil>",
    subject: str = "DFAS myPay One-Time PIN",
    body: str = "Your myPay one-time PIN is 123456.",
) -> dict:
    encoded = base64.urlsafe_b64encode(body.encode("utf-8")).decode("ascii").rstrip("=")
    return {
        "internalDate": str(int(when.timestamp() * 1000)),
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
            ],
            "mimeType": "text/plain",
            "body": {"data": encoded},
        },
    }


def _provider(service, fallback=None, **kwargs):
    return GmailOAuthOTPProvider(
        fallback=fallback if fallback is not None else _Fallback(),
        service_factory=lambda: service,
        gmail_poll_seconds=0,
        poll_interval_seconds=0,
        **kwargs,
    )


def test_returns_single_recent_mypay_code_without_logging_it(caplog):
    challenge = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    service = _FakeGmailService(
        {"m1": _message(when=challenge + timedelta(seconds=5))}
    )
    fallback = _Fallback()
    provider = _provider(service, fallback=fallback)

    caplog.set_level(logging.INFO, logger="sentry.extractors.gmail_otp_provider")
    code = provider.wait_for_code(
        "mypay",
        challenge_started_at=challenge,
        hint="dfas.mil",
        timeout_seconds=300,
    )

    assert code == "123456"
    assert fallback.calls == []
    assert "123456" not in caplog.text
    assert "one-time PIN" not in caplog.text
    list_call = next(call for call in service.calls if call["method"] == "list")
    assert list_call["kwargs"]["userId"] == "me"
    assert "newer_than:1d" in list_call["kwargs"]["q"]


def test_ignores_messages_older_than_challenge_start():
    challenge = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    service = _FakeGmailService(
        {"m1": _message(when=challenge - timedelta(seconds=1))}
    )
    fallback = _Fallback(code="manual-after-old")
    provider = _provider(service, fallback=fallback)

    code = provider.wait_for_code(
        "mypay",
        challenge_started_at=challenge,
        hint="dfas.mil",
        timeout_seconds=300,
    )

    assert code == "manual-after-old"
    assert len(fallback.calls) == 1


def test_rejects_unrelated_messages_even_when_they_have_six_digits():
    challenge = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    service = _FakeGmailService(
        {
            "m1": _message(
                when=challenge + timedelta(seconds=5),
                sender="Newsletter <news@example.com>",
                subject="Weekly update",
                body="Your reservation number is 123456.",
            )
        }
    )
    fallback = _Fallback(code="manual-after-unrelated")
    provider = _provider(service, fallback=fallback)

    code = provider.wait_for_code(
        "mypay",
        challenge_started_at=challenge,
        hint="dfas.mil",
        timeout_seconds=300,
    )

    assert code == "manual-after-unrelated"
    assert len(fallback.calls) == 1


def test_accepts_dfas_smartdocs_mail_mil_sender():
    challenge = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    service = _FakeGmailService(
        {
            "m1": _message(
                when=challenge + timedelta(seconds=5),
                sender="DFAS-SmartDocs@mail.mil",
                subject="Login Verification Code",
                body="Your verification code is 123456.",
            )
        }
    )
    fallback = _Fallback()
    provider = _provider(service, fallback=fallback)

    code = provider.wait_for_code(
        "mypay",
        challenge_started_at=challenge,
        hint="dfas.mil",
        timeout_seconds=300,
    )

    assert code == "123456"
    assert fallback.calls == []


def test_multiple_plausible_codes_fall_back_to_manual():
    challenge = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    service = _FakeGmailService(
        {
            "m1": _message(
                when=challenge + timedelta(seconds=5),
                body="Your myPay one-time PIN is 123456.",
            ),
            "m2": _message(
                when=challenge + timedelta(seconds=10),
                body="Your myPay one-time PIN is 654321.",
            ),
        }
    )
    fallback = _Fallback(code="manual-after-ambiguous")
    provider = _provider(service, fallback=fallback)

    code = provider.wait_for_code(
        "mypay",
        challenge_started_at=challenge,
        hint="dfas.mil",
        timeout_seconds=300,
    )

    assert code == "manual-after-ambiguous"
    assert len(fallback.calls) == 1


def test_gmail_setup_failure_falls_back_to_manual(tmp_path):
    challenge = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    fallback = _Fallback(code="manual-after-config")
    provider = GmailOAuthOTPProvider(
        fallback=fallback,
        client_config_path=tmp_path / "missing-client.json",
        token_store=_EmptyTokenStore(),
        gmail_poll_seconds=0,
    )

    code = provider.wait_for_code(
        "mypay",
        challenge_started_at=challenge,
        hint="dfas.mil",
        timeout_seconds=300,
    )

    assert code == "manual-after-config"
    assert len(fallback.calls) == 1


def test_timeout_without_match_uses_manual_fallback():
    challenge = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    service = _FakeGmailService({})
    fallback = _Fallback(code="manual-after-timeout")
    provider = _provider(service, fallback=fallback)

    code = provider.wait_for_code(
        "mypay",
        challenge_started_at=challenge,
        hint="dfas.mil",
        timeout_seconds=300,
    )

    assert code == "manual-after-timeout"
    assert len(fallback.calls) == 1
    assert fallback.calls[0]["timeout_seconds"] <= 300


def test_default_gmail_poll_window_covers_delayed_smartdocs_delivery():
    provider = GmailOAuthOTPProvider()

    assert DEFAULT_GMAIL_POLL_SECONDS >= 120
    assert provider._effective_gmail_poll_seconds(300) == DEFAULT_GMAIL_POLL_SECONDS
    assert provider._effective_gmail_poll_seconds(90) == 90


def test_provider_does_not_keep_raw_message_body_or_code_on_instance():
    challenge = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    body = "Your myPay one-time PIN is 123456."
    provider = _provider(
        _FakeGmailService({"m1": _message(when=challenge, body=body)})
    )

    assert (
        provider.wait_for_code(
            "mypay",
            challenge_started_at=challenge,
            hint="dfas.mil",
            timeout_seconds=300,
        )
        == "123456"
    )

    provider_state = repr(provider.__dict__)
    assert body not in provider_state
    assert "123456" not in provider_state


def test_default_provider_remains_manual_unless_opted_in():
    with patch.dict(
        "os.environ",
        {"MYPAY_OTP_PROVIDER": "", "SENTRY_MYPAY_OTP_PROVIDER": ""},
        clear=False,
    ):
        assert isinstance(default_provider(), ManualMFABridgeOTPProvider)


def test_default_provider_uses_gmail_when_opted_in():
    with patch.dict("os.environ", {"MYPAY_OTP_PROVIDER": "gmail"}, clear=False):
        provider = default_provider()

    assert isinstance(provider, GmailOAuthOTPProvider)
    assert isinstance(provider.fallback, ManualMFABridgeOTPProvider)
