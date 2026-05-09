"""
tests/test_mypay_connector.py — myPay browser-connector foundation (P17-T25).

Covers the unit surface that does not require a live myPay session:

  a. Connector registration / instantiation contract.
  b. Manual MFA bridge wiring through the OTP-provider abstraction
     (filling the code field and submitting it).
  c. MFA timeout path returns False and stays out of the post-login
     branch.
  d. result_writer.persist_connector_result skips PDF-suffixed entries
     (regression guard against AI-040 / CSV-vs-PDF routing drift).
  e. Manual document drop continues to work through the new shared
     helper without changing observable behavior.

A live download / ingest run is not in scope here — that is exercised
by `tests/test_document_connector_ingest.py`.
"""

from __future__ import annotations

import base64
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from extractors import CONNECTOR_REGISTRY
from extractors.mypay_connector import MyPayConnector
from extractors.otp_provider import (
    ManualMFABridgeOTPProvider,
    OTPProvider,
    default_provider,
)


# ── a. Connector registration ────────────────────────────────────────────────


def test_mypay_in_connector_registry():
    """`mypay` must be discoverable via the canonical connector registry."""
    assert "mypay" in CONNECTOR_REGISTRY


def test_mypay_factory_returns_my_pay_connector():
    """Factory lambda must return a MyPayConnector instance."""
    inst = CONNECTOR_REGISTRY["mypay"]()
    try:
        assert isinstance(inst, MyPayConnector)
        assert inst.institution == "mypay"
        assert inst.display_name == "myPay (DFAS)"
        # Login URL must point at the DFAS host, not a placeholder.
        assert "dfas.mil" in inst.login_url
    finally:
        # Connector __init__ creates raw_exports/mypay/ — leave it
        # but don't hold any browser handles (none have been opened
        # yet at this point).
        pass


def test_default_otp_provider_is_manual_bridge():
    """The default OTPProvider for new connectors is the manual MFA bridge."""
    with patch.dict(
        "os.environ",
        {"MYPAY_OTP_PROVIDER": "", "SENTRY_MYPAY_OTP_PROVIDER": ""},
        clear=False,
    ):
        provider = default_provider()
    assert isinstance(provider, ManualMFABridgeOTPProvider)


# ── F1 regression: auth-state detection ──────────────────────────────────────


def _build_unauthenticated_landing_page():
    """Construct a Page mock that mimics the public mypay.dfas.mil landing.

    The base-class `_is_post_login` would treat this as authenticated
    because the URL has no login keywords and the body talks about
    "Account" / "Welcome" in marketing copy. The myPay-specific
    override must reject it because no logout / RAS link is visible.
    """
    page = MagicMock()
    page.url = "https://mypay.dfas.mil/"
    page.query_selector = MagicMock(return_value=None)  # no logout / RAS link
    page.inner_text = MagicMock(
        return_value=(
            "myPay\nWelcome to myPay\n"
            "Login or Register\n"
            "Account information for active duty, retirees, and DoD civilians.\n"
        )
    )
    return page


def test_is_post_login_rejects_public_landing_page():
    """F1 regression: the public landing page must NOT register as post-login."""
    connector = MyPayConnector()
    page = _build_unauthenticated_landing_page()
    assert connector._is_post_login(page) is False


def test_is_post_login_rejects_login_url_even_with_dashboard_text():
    """A URL that matches an unauth hint short-circuits even if positive markers exist."""
    connector = MyPayConnector()
    page = MagicMock()
    page.url = "https://mypay.dfas.mil/login/challenge"
    # Even if a (rogue) Logout selector matches, the URL hint wins.
    visible_logout = MagicMock()
    visible_logout.is_visible = MagicMock(return_value=True)
    page.query_selector = MagicMock(return_value=visible_logout)
    page.inner_text = MagicMock(return_value="")
    assert connector._is_post_login(page) is False


def test_is_post_login_accepts_post_login_url():
    """A URL on a known post-login route passes without DOM probing."""
    connector = MyPayConnector()
    page = MagicMock()
    page.url = "https://mypay.dfas.mil/RetireePay/Statement"
    # query_selector deliberately raises to prove URL alone is enough.
    page.query_selector = MagicMock(side_effect=AssertionError(
        "DOM probe must not run when URL hint matches"
    ))
    page.inner_text = MagicMock(return_value="")
    assert connector._is_post_login(page) is True


def test_is_post_login_accepts_visible_logout_link():
    """When the URL is ambiguous, a visible logout/RAS link is the positive marker."""
    connector = MyPayConnector()
    page = MagicMock()
    page.url = "https://mypay.dfas.mil/portal/home"

    visible_logout = MagicMock()
    visible_logout.is_visible = MagicMock(return_value=True)

    def _query(selector):
        # Only "Logout" / RAS-style selectors return a visible element.
        s = (selector or "").lower()
        if "logout" in s or "log out" in s or "sign out" in s or "ras" in s or "retiree" in s:
            return visible_logout
        return None

    page.query_selector = MagicMock(side_effect=_query)
    page.inner_text = MagicMock(return_value="")
    assert connector._is_post_login(page) is True


def test_is_session_valid_rejects_public_landing_page():
    """F1 regression: _is_session_valid must NOT skip login for the public landing."""
    connector = MyPayConnector()
    page = _build_unauthenticated_landing_page()

    response = MagicMock()
    response.status = 200
    page.goto = MagicMock(return_value=response)
    page.wait_for_load_state = MagicMock(return_value=None)

    assert connector._is_session_valid(page) is False
    page.goto.assert_called_once()


def test_is_session_valid_accepts_authenticated_session():
    """Session-valid path must hold when post-login markers ARE present."""
    connector = MyPayConnector()

    page = MagicMock()
    page.url = "https://mypay.dfas.mil/RetireePay/Home"
    response = MagicMock()
    response.status = 200
    page.goto = MagicMock(return_value=response)
    page.wait_for_load_state = MagicMock(return_value=None)
    page.query_selector = MagicMock(return_value=None)
    page.inner_text = MagicMock(return_value="")

    assert connector._is_session_valid(page) is True


def test_dismiss_post_login_interstitial_clicks_continue():
    """Observed live myPay path can land on #/message before the RAS menu."""
    connector = MyPayConnector()
    page = MagicMock()
    page.url = "https://mypay.dfas.mil/#/message"
    page.wait_for_timeout = MagicMock(return_value=None)
    page.wait_for_load_state = MagicMock(return_value=None)

    continue_button = MagicMock()
    continue_button.is_visible = MagicMock(return_value=True)
    continue_button.click = MagicMock()
    page.query_selector = MagicMock(
        side_effect=lambda selector: (
            continue_button if "Continue" in (selector or "") else None
        )
    )

    connector._dismiss_post_login_interstitial(page)

    continue_button.click.assert_called_once()
    page.wait_for_timeout.assert_called_once_with(2500)


def test_dismiss_post_login_interstitial_ignores_regular_page():
    """The interstitial helper should be inert once already on normal pages."""
    connector = MyPayConnector()
    page = MagicMock()
    page.url = "https://mypay.dfas.mil/#/retiree"

    connector._dismiss_post_login_interstitial(page)

    page.query_selector.assert_not_called()


# ── F3 regression: push-approval MFA broadcasts MFA_REQUIRED ────────────────


def test_navigate_to_ras_opens_hamburger_menu_for_hidden_eras_link():
    """Live myPay landing can hide the eRAS link behind the hamburger menu."""
    connector = MyPayConnector()
    page = MagicMock()
    page.wait_for_timeout = MagicMock(return_value=None)
    page.wait_for_load_state = MagicMock(return_value=None)
    menu_open = {"value": False}

    menu = MagicMock()
    menu.is_visible = MagicMock(return_value=True)

    def click_menu(*_args, **_kwargs):
        menu_open["value"] = True

    menu.click = MagicMock(side_effect=click_menu)

    eras_link = MagicMock()
    eras_link.is_visible = MagicMock(return_value=True)
    eras_link.click = MagicMock()

    def query_selector(selector):
        if 'button[aria-label*="menu"' in selector:
            return menu
        if "eRAS" in selector and menu_open["value"]:
            return eras_link
        return None

    page.query_selector = MagicMock(side_effect=query_selector)
    page.query_selector_all = MagicMock(return_value=[])

    with patch.object(connector, "_dismiss_password_change_prompt"), \
         patch.object(connector, "_dismiss_post_login_interstitial"), \
         patch.object(connector, "_is_on_ras_page", return_value=True):
        assert connector._navigate_to_ras(page) is True

    menu.click.assert_called_once()
    eras_link.click.assert_called_once()


def test_navigate_to_ras_opens_overflow_menu_for_hidden_eras_link():
    """Some myPay links hide behind the top-right overflow menu."""
    connector = MyPayConnector()
    page = MagicMock()
    page.wait_for_timeout = MagicMock(return_value=None)
    page.wait_for_load_state = MagicMock(return_value=None)
    overflow_open = {"value": False}

    overflow = MagicMock()
    overflow.is_visible = MagicMock(return_value=True)

    def click_overflow(*_args, **_kwargs):
        overflow_open["value"] = True

    overflow.click = MagicMock(side_effect=click_overflow)

    eras_link = MagicMock()
    eras_link.is_visible = MagicMock(return_value=True)
    eras_link.click = MagicMock()

    def query_selector(selector):
        if 'button[aria-label*="more"' in selector:
            return overflow
        if "eRAS" in selector and overflow_open["value"]:
            return eras_link
        return None

    page.query_selector = MagicMock(side_effect=query_selector)
    page.query_selector_all = MagicMock(return_value=[])

    with patch.object(connector, "_dismiss_password_change_prompt"), \
         patch.object(connector, "_dismiss_post_login_interstitial"), \
         patch.object(connector, "_is_on_ras_page", side_effect=[False, True]):
        assert connector._navigate_to_ras(page) is True

    overflow.click.assert_called_once()
    eras_link.click.assert_called_once()


def test_dismiss_password_change_prompt_clicks_later_and_notifies():
    """myPay's 90-day password prompt should be deferred but surfaced in-app."""
    connector = MyPayConnector()
    page = MagicMock()
    page.wait_for_timeout = MagicMock(return_value=None)
    page.wait_for_load_state = MagicMock(return_value=None)

    remind = MagicMock()
    remind.is_visible = MagicMock(return_value=True)
    remind.click = MagicMock()
    page.query_selector = MagicMock(
        side_effect=lambda selector: remind if "Remind Me Later" in selector else None
    )

    with patch.object(connector, "_record_password_change_notification") as notify:
        assert connector._dismiss_password_change_prompt(page) is True

    remind.click.assert_called_once()
    notify.assert_called_once()
    page.wait_for_timeout.assert_called_once_with(2500)


def test_dismiss_password_change_prompt_change_now_opens_change_flow():
    """Change-now clicks myPay's action, waits, and avoids deferral."""
    connector = MyPayConnector()
    page = MagicMock()
    page.wait_for_timeout = MagicMock(return_value=None)
    page.wait_for_load_state = MagicMock(return_value=None)

    remind = MagicMock()
    remind.is_visible = MagicMock(return_value=True)
    change = MagicMock()
    change.is_visible = MagicMock(return_value=True)

    def query_selector(selector):
        if "Remind Me Later" in selector:
            return remind
        if "Change Password" in selector:
            return change
        return None

    page.query_selector = MagicMock(side_effect=query_selector)

    with patch.object(
        connector, "_choose_password_change_action", return_value="change_now"
    ), patch.object(
        connector, "_wait_for_password_change_completion", return_value=True
    ) as wait_done, patch.object(
        connector, "_record_password_change_notification"
    ) as notify:
        assert connector._dismiss_password_change_prompt(page) is True

    change.click.assert_called_once()
    wait_done.assert_called_once_with(page)
    remind.click.assert_not_called()
    notify.assert_not_called()


def test_dismiss_password_change_prompt_change_now_timeout_falls_back_to_later():
    """If live rotation stalls, the connector tries the safe default."""
    connector = MyPayConnector()
    page = MagicMock()
    page.wait_for_timeout = MagicMock(return_value=None)
    page.wait_for_load_state = MagicMock(return_value=None)

    remind = MagicMock()
    remind.is_visible = MagicMock(return_value=True)
    remind.click = MagicMock()
    page.query_selector = MagicMock(
        side_effect=lambda selector: remind if "Remind Me Later" in selector else None
    )

    with patch.object(
        connector, "_choose_password_change_action", return_value="change_now"
    ), patch.object(
        connector, "_wait_for_password_change_completion", return_value=False
    ), patch.object(
        connector, "_record_password_change_notification"
    ) as notify:
        assert connector._dismiss_password_change_prompt(page) is True

    remind.click.assert_called_once()
    notify.assert_called_once()


def test_dismiss_password_change_prompt_change_now_waits_if_click_not_found():
    """If myPay changes labels, still wait for the user instead of deferring."""
    connector = MyPayConnector()
    page = MagicMock()

    remind = MagicMock()
    remind.is_visible = MagicMock(return_value=True)
    page.query_selector = MagicMock(
        side_effect=lambda selector: remind if "Remind Me Later" in selector else None
    )

    with patch.object(
        connector, "_choose_password_change_action", return_value="change_now"
    ), patch.object(
        connector, "_wait_for_password_change_completion", return_value=True
    ) as wait_done, patch.object(
        connector, "_record_password_change_notification"
    ) as notify:
        assert connector._dismiss_password_change_prompt(page) is True

    wait_done.assert_called_once_with(page)
    remind.click.assert_not_called()
    notify.assert_not_called()


def test_wait_for_password_change_completion_requires_no_password_form():
    """The wait should not finish while a password form is still visible."""
    connector = MyPayConnector()
    page = MagicMock()
    page.wait_for_timeout = MagicMock(return_value=None)

    form_visible = [True, True, False, False, False]

    def has_form(_page):
        return form_visible.pop(0) if form_visible else False

    with patch.object(connector, "_has_password_change_prompt", return_value=False), \
         patch.object(connector, "_has_password_update_form", side_effect=has_form), \
         patch.object(connector, "_is_post_login", return_value=True):
        assert connector._wait_for_password_change_completion(
            page,
            timeout_seconds=1,
        ) is True

    assert page.wait_for_timeout.call_count >= 4


def test_is_on_ras_page_accepts_live_mras_route():
    """Live myPay retired-pay eRAS route is #/militaryretired/mras."""
    connector = MyPayConnector()
    page = MagicMock()
    page.url = "https://mypay.dfas.mil/#/militaryretired/mras"

    assert connector._is_on_ras_page(page) is True
    page.inner_text.assert_not_called()


def test_first_visible_skips_hidden_duplicate_elements():
    """myPay can render hidden duplicates before the visible action."""
    connector = MyPayConnector()
    page = MagicMock()

    hidden = MagicMock()
    hidden.is_visible = MagicMock(return_value=False)
    visible = MagicMock()
    visible.is_visible = MagicMock(return_value=True)
    page.query_selector_all = MagicMock(return_value=[hidden, visible])

    assert connector._first_visible(page, "button") is visible


def test_download_printable_mras_pdf_saves_blob_bytes(tmp_path: Path):
    """Observed eRAS download opens a modal iframe with blob-backed PDF bytes."""
    connector = MyPayConnector()
    page = MagicMock()

    trigger = MagicMock()
    trigger.is_visible = MagicMock(return_value=True)
    page.query_selector_all = MagicMock(return_value=[trigger])
    page.wait_for_selector = MagicMock(return_value=None)

    pdf_bytes = b"%PDF-1.4\nfake eRAS\n"
    page.evaluate = MagicMock(return_value=base64.b64encode(pdf_bytes).decode("ascii"))

    with patch("extractors.mypay_connector.RAW_DIR", tmp_path):
        path = connector._download_printable_mras_pdf(page)

    assert path is not None
    assert path.parent == tmp_path
    assert path.name.startswith("mypay_ras_unknown_")
    assert path.read_bytes() == pdf_bytes
    trigger.click.assert_called_once()


def test_mypay_dev_mode_does_not_preserve_browser_session():
    connector = MyPayConnector()
    assert connector._preserve_browser_session_in_dev_mode() is False


def test_perform_logout_closes_pdf_logs_out_and_declines_survey():
    connector = MyPayConnector()
    page = MagicMock()
    page.wait_for_timeout = MagicMock(return_value=None)
    page.wait_for_load_state = MagicMock(return_value=None)

    modal_close = MagicMock()
    modal_close.is_visible = MagicMock(return_value=True)
    logout = MagicMock()
    logout.is_visible = MagicMock(return_value=True)
    survey_decline = MagicMock()
    survey_decline.is_visible = MagicMock(return_value=True)

    def query_selector_all(selector):
        if selector == '#pdfModal button[aria-label="Close"]':
            return [modal_close]
        if selector == 'a:has-text("Logout")':
            return [logout]
        if selector == 'button:has-text("No Thanks")':
            return [survey_decline]
        return []

    page.query_selector_all = MagicMock(side_effect=query_selector_all)

    connector._perform_logout(page)

    modal_close.click.assert_called_once()
    logout.click.assert_called_once()
    survey_decline.click.assert_called_once()


def test_wait_for_mfa_no_code_field_broadcasts_push_approval():
    """No code-input rendered → still broadcast MFA_REQUIRED + set _mfa_prompted."""
    connector = MyPayConnector()

    page = MagicMock()
    page.url = "https://mypay.dfas.mil/auth/callback"
    page.wait_for_timeout = MagicMock(return_value=None)
    page.wait_for_load_state = MagicMock(return_value=None)
    page.query_selector = MagicMock(return_value=None)
    page.inner_text = MagicMock(return_value="")
    # Code-input wait_for_selector raises PlaywrightTimeout so the
    # connector takes the no-code-field branch.
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    page.wait_for_selector = MagicMock(side_effect=PlaywrightTimeout("no code field"))

    # _is_post_login: False for the first three calls, then True (the
    # base-class polling loop catches the user's eventual approval).
    state = {"calls": 0}

    def _post_login_check(self, _page):
        state["calls"] += 1
        return state["calls"] > 3

    received: list[dict] = []

    def fake_broadcast(topic, payload):
        received.append({"topic": topic, "payload": payload})

    with patch.object(MyPayConnector, "_is_post_login", _post_login_check), \
         patch("backend.events.broadcast_event", side_effect=fake_broadcast):
        ok = connector._wait_for_mfa(page, timeout_seconds=10)

    assert ok is True
    # _mfa_prompted MUST be set even though no code was filled.
    assert connector._mfa_prompted is True
    # Exactly one push-approval MFA_REQUIRED event was broadcast.
    mfa_events = [e for e in received if e["topic"] == "mfa_required"]
    assert len(mfa_events) == 1
    payload = mfa_events[0]["payload"]
    assert payload["institution"] == "mypay"
    # Prompt should clearly tell the user to approve in browser/app.
    prompt = payload["prompt"].lower()
    assert "approve" in prompt
    assert "browser" in prompt or "app" in prompt


# ── b. Manual MFA bridge wiring ──────────────────────────────────────────────


def test_select_email_mfa_factor_clicks_next():
    """Live myPay presents a factor menu before the email OTP field."""
    connector = MyPayConnector()
    page = MagicMock()
    page.evaluate = MagicMock(return_value=True)
    page.wait_for_timeout = MagicMock(return_value=None)
    page.wait_for_load_state = MagicMock(return_value=None)

    next_button = MagicMock()
    next_button.is_visible = MagicMock(return_value=True)
    next_button.click = MagicMock()
    page.query_selector = MagicMock(
        side_effect=lambda selector: (
            next_button if "Next" in (selector or "") else None
        )
    )

    assert connector._select_email_mfa_factor(page) is True
    page.evaluate.assert_called_once()
    next_button.click.assert_called_once()


def test_select_email_mfa_factor_returns_false_without_email_option():
    """If no email factor is visible, push/app polling remains the fallback."""
    connector = MyPayConnector()
    page = MagicMock()
    page.evaluate = MagicMock(return_value=False)

    assert connector._select_email_mfa_factor(page) is False
    page.query_selector.assert_not_called()


class _StubProvider(OTPProvider):
    """Test double — returns a preconfigured code without touching the SSE bus."""

    def __init__(self, code):
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
                "hint": hint,
                "timeout_seconds": timeout_seconds,
                "challenge_started_at": challenge_started_at,
            }
        )
        return self.code


class _BlockingProvider(OTPProvider):
    """Test double that never returns a code during the direct-browser path."""

    def wait_for_code(
        self,
        institution,
        *,
        challenge_started_at,
        hint=None,
        timeout_seconds=300,
    ):
        threading.Event().wait(timeout_seconds)
        return None


def _build_page_with_mfa_field(code_input_visible=True, post_login_after_submit=True):
    """Construct a Playwright Page-like MagicMock for the MFA flow.

    Models:
      - `wait_for_selector` resolving when the code field renders
      - `query_selector` returning a fillable input element
      - `_is_post_login` flipping to True after the submit click
    """
    page = MagicMock()
    page.url = "https://mypay.dfas.mil/login/challenge"

    # Code input element: fill() and press() both succeed; is_visible=True
    code_input = MagicMock()
    code_input.is_visible.return_value = code_input_visible
    code_input.fill = MagicMock()
    code_input.press = MagicMock()

    # Submit button: clickable, is_visible=True
    submit_button = MagicMock()
    submit_button.is_visible.return_value = True
    submit_button.click = MagicMock()

    # First call resolves to the code input (used for fill_first); the
    # last call after fill is for press fallback. We don't strictly
    # care — return the code_input for any code-input selector match.
    def _query_selector(selector):
        s = (selector or "").lower()
        if "code" in s or "otp" in s or "passcode" in s or "one-time-code" in s:
            return code_input
        if "submit" in s or "verify" in s or "continue" in s:
            return submit_button
        return None

    page.query_selector = MagicMock(side_effect=_query_selector)
    page.wait_for_selector = MagicMock(return_value=None)
    page.wait_for_timeout = MagicMock(return_value=None)
    page.wait_for_load_state = MagicMock(return_value=None)
    page.inner_text = MagicMock(return_value="")
    return page, code_input, submit_button


def test_wait_for_mfa_fills_code_via_provider():
    """Manual-bridge path: provider returns a code, connector fills + submits."""
    stub = _StubProvider(code="987654")
    connector = MyPayConnector(otp_provider=stub)

    page, code_input, submit_button = _build_page_with_mfa_field()

    # Stub _is_post_login to return False initially, True after submit.
    state = {"post_login": False}

    def _post_login_check(self, _page):  # bound method form
        return state["post_login"]

    # Make the click flip the state
    def _click_side_effect(*_args, **_kwargs):
        state["post_login"] = True
    submit_button.click.side_effect = _click_side_effect

    with patch.object(MyPayConnector, "_is_post_login", _post_login_check):
        ok = connector._wait_for_mfa(page, timeout_seconds=5)

    assert ok is True
    code_input.fill.assert_called_once_with("987654")
    submit_button.click.assert_called()
    # Provider was invoked once with institution="mypay" and a non-None
    # challenge_started_at.
    assert len(stub.calls) == 1
    assert stub.calls[0]["institution"] == "mypay"
    assert stub.calls[0]["timeout_seconds"] == 5
    assert isinstance(stub.calls[0]["challenge_started_at"], datetime)
    # _mfa_prompted must be set so refresh_events records this attempt.
    assert connector._mfa_prompted is True


def test_wait_for_mfa_via_real_bridge_dashboard_path():
    """Manual MFA bridge: dashboard submit_code() unblocks wait_for_code()."""
    # Use the real ManualMFABridgeOTPProvider so we exercise the actual
    # backend.mfa_bridge.wait_for_code path. Patch broadcast_event so
    # we don't need a running SSE bus.
    from backend import mfa_bridge

    connector = MyPayConnector(otp_provider=ManualMFABridgeOTPProvider())
    page, code_input, submit_button = _build_page_with_mfa_field()
    state = {"post_login": False}

    def _post_login_check(self, _page):  # bound method form
        return state["post_login"]

    submit_button.click.side_effect = lambda *_a, **_k: state.update(post_login=True)

    received_events: list[dict] = []

    def fake_broadcast(topic, payload):
        received_events.append({"topic": topic, "payload": payload})

    # Drive the dashboard side: a separate thread submits the code
    # shortly after wait_for_mfa starts blocking.
    def submit_after_delay():
        # Poll until the bridge is actually waiting before submitting.
        for _ in range(50):
            if mfa_bridge.is_pending("mypay"):
                mfa_bridge.submit_code("mypay", "246810")
                return
            threading.Event().wait(0.05)

    submitter = threading.Thread(target=submit_after_delay, daemon=True)

    with patch.object(MyPayConnector, "_is_post_login", _post_login_check), \
         patch("backend.events.broadcast_event", side_effect=fake_broadcast):
        submitter.start()
        ok = connector._wait_for_mfa(page, timeout_seconds=5)
        submitter.join(timeout=2)

    assert ok is True
    code_input.fill.assert_called_once_with("246810")
    # Exactly one MFA_REQUIRED event should have been broadcast for myPay.
    mfa_events = [e for e in received_events if e["topic"] == "mfa_required"]
    assert len(mfa_events) == 1
    assert mfa_events[0]["payload"]["institution"] == "mypay"


# ── c. MFA timeout path ──────────────────────────────────────────────────────


def test_wait_for_mfa_accepts_direct_browser_otp_entry():
    """If the user enters OTP in myPay itself, connector should stop waiting."""
    connector = MyPayConnector(otp_provider=_BlockingProvider())
    page, code_input, submit_button = _build_page_with_mfa_field()
    state = {"polls": 0}

    def wait_for_timeout(_ms):
        state["polls"] += 1

    page.wait_for_timeout = MagicMock(side_effect=wait_for_timeout)

    def password_prompt_after_user_submit(self, _page):
        return state["polls"] >= 1

    with patch.object(MyPayConnector, "_is_post_login", lambda self, p: False), \
         patch.object(
             MyPayConnector,
             "_has_password_change_prompt",
             password_prompt_after_user_submit,
         ), \
         patch.object(connector, "_cancel_pending_mfa_bridge") as cancel:
        ok = connector._fill_and_submit_mfa_code(
            page,
            ["input#onetimepin"],
            timeout_seconds=2,
        )

    assert ok is True
    code_input.fill.assert_not_called()
    submit_button.click.assert_not_called()
    cancel.assert_called_once()


def test_wait_for_mfa_timeout_returns_false():
    """Provider returns None on timeout — connector must report failure."""
    stub = _StubProvider(code=None)
    connector = MyPayConnector(otp_provider=stub)

    page, *_ = _build_page_with_mfa_field()

    with patch.object(MyPayConnector, "_is_post_login", lambda self, p: False):
        ok = connector._wait_for_mfa(page, timeout_seconds=2)

    assert ok is False
    # Even on timeout, _mfa_prompted must be set so the orchestrator
    # records that this attempt asked the user for action.
    assert connector._mfa_prompted is True


def test_wait_for_mfa_session_reuse_skips_provider():
    """If the page is already post-login, no MFA bridge call should fire."""
    stub = _StubProvider(code="111222")
    connector = MyPayConnector(otp_provider=stub)

    page, *_ = _build_page_with_mfa_field()

    with patch.object(MyPayConnector, "_is_post_login", lambda self, p: True):
        ok = connector._wait_for_mfa(page, timeout_seconds=5)

    assert ok is True
    assert stub.calls == []
    # Session-reuse path must not flip _mfa_prompted.
    assert connector._mfa_prompted is False


# ── d. result_writer skips non-CSV connector files ──────────────────────────


def test_result_writer_skips_pdf_files(tmp_path: Path, caplog):
    """A PDF in result.files must NOT be routed through pd.read_csv.

    Regression guard: previously `persist_connector_result` walked
    every entry in `result.files` and called `pd.read_csv` on it.
    Feeding a PDF would explode the pandas reader and surface as a
    `failed_csvs` notification. After P17-T25 we filter to .csv.
    """
    from backend.result_writer import persist_connector_result

    # Drop a file with a .pdf extension. We do NOT want pandas to be
    # called on this; reading would either fail outright or emit a
    # csv_parse_failure notification.
    pdf_path = tmp_path / "mypay_ras_2026-02_test.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%not-a-csv\n")

    result = MagicMock()
    result.balances = {}
    result.loan_details = {}
    result.investment_details = {}
    result.files = [pdf_path]

    # Wire an in-memory connection through get_db so the function runs
    # end-to-end without touching the real database.
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    with patch("backend.result_writer.get_db") as mock_get_db, \
         patch("backend.result_writer.pd", create=True) as mock_pd:
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=conn)
        ctx.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = ctx
        # Sentinel so any accidental pd.read_csv() call would blow up.
        mock_pd.read_csv.side_effect = AssertionError(
            "pd.read_csv must not be invoked on a non-CSV connector file"
        )

        summary = persist_connector_result("mypay", result, conn=conn)

    # No failure should have been logged because pd.read_csv was never
    # called — the .pdf file was filtered out before the loop.
    assert "failed_csvs" not in summary
    assert summary["txn_inserted"] == 0
    assert summary["accounts_processed"] == 0


def test_result_writer_processes_csv_files(tmp_path: Path):
    """Sibling-of-test_result_writer_skips_pdf_files: real .csv path still works."""
    from backend.result_writer import persist_connector_result

    csv_path = tmp_path / "1234_transactions.csv"
    csv_path.write_text(
        "Posting Date,Amount,Description,Credit Debit Indicator\n"
        "2026-04-15,12.50,Test merchant,Debit\n"
    )

    result = MagicMock()
    result.balances = {}
    result.loan_details = {}
    result.investment_details = {}
    result.files = [csv_path]

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT,
            institution_id TEXT,
            posting_date TEXT,
            transaction_date TEXT,
            amount REAL,
            signed_amount REAL,
            direction TEXT,
            description TEXT,
            category TEXT,
            status TEXT,
            raw_description TEXT,
            sequence_index INTEGER,
            merchant TEXT,
            transfer_tag TEXT,
            effective_month TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)

    # Patch upsert_transactions so we don't depend on the full schema.
    fake_stats = {"inserted": 1, "updated": 0, "unchanged": 0, "deleted": 0}
    with patch("backend.result_writer.get_db") as mock_get_db, \
         patch("backend.result_writer.upsert_transactions", return_value=fake_stats):
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=conn)
        ctx.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = ctx

        summary = persist_connector_result("nfcu", result, conn=conn)

    assert summary["txn_inserted"] == 1


# ── e. Synthetic _marker_* balances are filtered ────────────────────────────


def test_result_writer_skips_marker_balances():
    """`_marker_*` balance entries (no-new-RAS sentinel) must not write rows."""
    from backend.result_writer import persist_connector_result

    result = MagicMock()
    result.balances = {
        "_marker_no_new_ras": {"name": "myPay (no new RAS)", "balance": "$0.00"},
    }
    result.loan_details = {}
    result.investment_details = {}
    result.files = []

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    with patch("backend.result_writer.get_db") as mock_get_db, \
         patch("backend.result_writer.record_balance") as mock_record, \
         patch("backend.result_writer.get_latest_balances", return_value={}):
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=conn)
        ctx.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = ctx

        summary = persist_connector_result("mypay", result, conn=conn)

    mock_record.assert_not_called()
    assert summary["balances_recorded"] == 0
