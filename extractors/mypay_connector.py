"""
extractors/mypay_connector.py — myPay (DFAS) RAS document connector.

P17-T25 foundation slice. The connector logs into mypay.dfas.mil with
broker-supplied credentials, waits for an email-delivered second-factor
code via the OTP-provider abstraction (manual MFA bridge today, Gmail
OAuth in a follow-on), navigates to the Retiree Account Statement
section, downloads the latest RAS PDF, and ingests it through the
existing `MyPayRASParser` document-drop pipeline.

Why this connector exists alongside the manual /api/documents/* path:

  * RAS PDFs change once a month and often arrive a day or two after
    payday — a manual drop turns into a recurring chore.
  * The parser, owner attribution, document_drops provenance row, and
    payroll_snapshots write are unchanged. The connector is purely a
    retrieval-and-ingest wrapper around the same parser path.

Manual document drop (`POST /api/documents/upload` +
`POST /api/documents/commit`) remains the fallback. Both paths now go
through `backend.document_ingest`, so a manually-dropped RAS and a
connector-ingested RAS produce identical `document_drops` and
`payroll_snapshots` rows.

What this slice deliberately does NOT do:

  * Implement Gmail OAuth, IMAP polling, or any inbox access. The
    `OTPProvider` abstraction in `extractors.otp_provider` is the
    seam where the next slice plugs in.
  * Pin live myPay selectors that haven't been validated against a
    real session — selectors are seeded conservatively in
    `selector_registry.yaml` and will harden once a real login run
    captures the DOM.
  * Promote myPay from tier-3 (document drop) to tier-2 in
    `dal/freshness.py`. Tier promotion follows successful live runs.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from skills.institution_connector import AccountConfig, InstitutionConnector
from extractors.otp_provider import OTPProvider, default_provider

log = logging.getLogger("sentry.extractors.mypay")

# Public landing page for myPay. The actual login form may live behind
# a redirect to a DFAS SSO host; the connector follows whatever the
# session lands on.
MYPAY_LOGIN_URL = "https://mypay.dfas.mil/"
# After login, the RAS document area is generally one of these. Resolved
# at runtime via _navigate_to_ras() since DFAS rotates URL paths.
MYPAY_RAS_URL_HINTS = (
    "RetireePay",
    "retiree",
    "ras",
    "Statement",
)

# Filenames are written into raw_exports/mypay/. We do NOT commit any
# real RAS PDFs (raw_exports/ is gitignored).
RAW_DIR = Path(__file__).resolve().parent.parent / "raw_exports" / "mypay"


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


class MyPayConnector(InstitutionConnector):
    """DFAS myPay RAS document connector."""

    def __init__(
        self,
        headless: bool = False,
        otp_provider: OTPProvider | None = None,
        **kwargs,
    ):
        # OTP provider is the seam between this connector and whatever
        # delivers the second-factor code. Default = manual MFA bridge.
        # P17 follow-on will pass a Gmail-OAuth provider here.
        self._otp_provider = otp_provider or default_provider()
        # Ingest outcome of the last successful run. Populated by
        # `_trigger_export` so callers (and tests) can assert that
        # commit went through without scraping log lines.
        self._last_ingest_summary: dict | None = None
        # Pre-create export dir before super().__init__ so the
        # base-class _export_dir.mkdir is idempotent for our
        # raw_exports/mypay path.
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        super().__init__(headless=headless, **kwargs)

    # ── Identity ──────────────────────────────────────────────────────────

    @property
    def institution(self) -> str:
        return "mypay"

    @property
    def display_name(self) -> str:
        return "myPay (DFAS)"

    @property
    def export_url(self) -> str:
        # myPay routes everything through the same landing page
        # post-login; subroutes are link-driven, not URL-driven.
        return MYPAY_LOGIN_URL

    @property
    def login_url(self) -> str:
        return MYPAY_LOGIN_URL

    # ── Auth-state detection ─────────────────────────────────────────────

    # Positive markers: the DOM contains at least one of these post-login
    # surfaces. The base class default is "URL has no login keywords +
    # the body has dashboard-like words" — that's too permissive for
    # myPay because the public landing page at https://mypay.dfas.mil/
    # has no login keywords in the URL, talks about "Account" and
    # "Welcome" in marketing copy, and would falsely register as
    # post-login. The selectors below only match content rendered after
    # a successful login.
    _POST_LOGIN_SELECTORS: tuple[str, ...] = (
        'a:has-text("Logout")',
        'a:has-text("Log Out")',
        'a:has-text("Sign Out")',
        'button:has-text("Logout")',
        'a[href*="logout" i]',
        'a:has-text("Retiree Account Statement")',
        'a:has-text("View RAS")',
        'a[href*="RetireePay" i]',
        'a[href*="RAS" i]',
        'select[aria-label="MRAS History Select"]',
    )

    # URL fragments that, when present, indicate the page is on a known
    # post-login route. Used as a corroborating signal alongside the
    # selector check.
    _POST_LOGIN_URL_HINTS: tuple[str, ...] = (
        "/retireepay",
        "/ras",
        "/myaccount",
        "/dashboard",
        "#/message",
        "#/militaryretired",
    )

    # URL fragments that mean the page is unauthenticated regardless of
    # what else is rendered (login / challenge / password-reset flow).
    _UNAUTH_URL_HINTS: tuple[str, ...] = (
        "/login",
        "/signin",
        "/sign-in",
        "/challenge",
        "/mfa",
        "/verify",
        "/otp",
        "/passwordreset",
        "/forgot",
        "/register",
    )

    def _is_post_login(self, page: Page) -> bool:
        """Strict myPay post-login detection — positive markers required.

        Returns True only if BOTH:

          1. The URL is not on a known login / challenge / reset path.
          2. EITHER the URL is on a known post-login route, OR a
             logout / RAS-link element is visible.

        The unauthenticated landing page at https://mypay.dfas.mil/
        passes (1) but fails (2), so it correctly returns False.
        Subclasses of the base check that rely on "URL has no login
        keywords" alone are too permissive here.
        """
        url = (page.url or "").lower()

        if any(hint in url for hint in self._UNAUTH_URL_HINTS):
            return False

        if any(hint in url for hint in self._POST_LOGIN_URL_HINTS):
            # URL alone is enough — no need to scan the DOM.
            return True

        try:
            for sel in self._POST_LOGIN_SELECTORS:
                el = self._first_visible(page, sel)
                if el is None:
                    continue
                return True
        except Exception as e:
            log.debug("[mypay] post-login DOM probe failed: %s", e)

        return False

    def _is_session_valid(self, page: Page) -> bool:
        """myPay-specific session check — refuses public landing as valid.

        Navigates to `export_url` (the myPay landing page), waits for
        load, and applies the strict `_is_post_login` check. Without
        this override, the base implementation would treat the public
        landing page (which has no login keywords in its URL) as a
        valid session and skip the login step entirely.
        """
        try:
            response = page.goto(
                self.export_url, wait_until="domcontentloaded", timeout=30000
            )
        except PlaywrightTimeout:
            log.warning("[mypay] session-check navigation timed out")
            return False
        except Exception as e:
            log.warning("[mypay] session-check navigation failed: %s", e)
            return False

        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception as e:
            log.debug("[mypay] networkidle wait skipped: %s", e)

        if response is not None and response.status >= 400:
            log.info(
                "[mypay] session check got HTTP %d — treating as invalid",
                response.status,
            )
            return False

        if self._is_post_login(page):
            log.info("[mypay] session valid — post-login markers detected")
            return True

        log.info("[mypay] session invalid — no post-login markers visible")
        return False

    # ── Login ────────────────────────────────────────────────────────────

    def _perform_login(
        self, page: Page, credentials: dict | None = None
    ) -> bool:
        """Navigate to myPay login and submit credentials.

        Selectors are seeded conservatively in selector_registry.yaml.
        Real selectors firm up once a live walkthrough captures the
        DOM; today the connector tries common DFAS form ids before
        falling back to Password Manager autofill (the same pattern
        every other connector uses).
        """
        log.info("[mypay] Navigating to login URL")
        try:
            page.goto(self.login_url, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightTimeout:
            log.warning("[mypay] login URL never reached domcontentloaded")
            return False

        username_selectors = [
            "input#LoginUserName",
            "input#username",
            'input[name="username"]',
            'input[name="UserName"]',
            'input[autocomplete="username"]',
        ]
        password_selectors = [
            "input#LoginPassword",
            "input#password",
            'input[name="password"]',
            'input[type="password"]',
        ]
        submit_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            "#LoginButton",
            'button:has-text("Login")',
            'button:has-text("Sign In")',
        ]

        # Wait for the form to render. If we never see a username field,
        # something fundamental is off (URL changed, redirect failed).
        try:
            self._wait_for_first(page, username_selectors, timeout_ms=15000)
        except PlaywrightTimeout:
            log.warning("[mypay] login form did not appear")
            return False

        if (
            not credentials
            or "username" not in credentials
            or "password" not in credentials
        ):
            # No broker creds — let Password Manager autofill, then
            # click submit. This is the same fallback every other
            # connector uses; the user finishes the flow manually if
            # autofill misses.
            log.info("[mypay] No broker credentials — relying on Password Manager")
            page.wait_for_timeout(3000)
            self._click_first(page, submit_selectors, timeout_ms=5000)
            return True

        # Fill from broker. Do NOT log username or password.
        log.info("[mypay] Filling credentials from broker")
        if not self._fill_first(page, username_selectors, credentials["username"]):
            log.warning("[mypay] could not locate username field")
            return False
        if not self._fill_first(page, password_selectors, credentials["password"]):
            log.warning("[mypay] could not locate password field")
            return False
        page.wait_for_timeout(500)
        self._click_first(page, submit_selectors, timeout_ms=5000)
        return True

    # ── MFA ──────────────────────────────────────────────────────────────

    def _wait_for_mfa(self, page: Page, timeout_seconds: int = 300) -> bool:
        """Detect myPay's second-factor screen and route via OTPProvider.

        myPay sends an email code by default. The connector:

          1. Looks for a code-entry field after login.
          2. If absent and the page already looks post-login, returns
             True (session reuse / no challenge issued).
          3. Otherwise broadcasts MFA_REQUIRED via the OTP provider,
             waits for a code, fills it, and submits.

          The provider may also represent a push-approval factor; in
          that case it returns None and the connector polls for
          post-login state instead.
        """
        if self._is_post_login(page):
            return True

        page.wait_for_timeout(2500)
        if self._is_post_login(page):
            return True

        code_selectors = [
            "input#onetimepin",
            'input[aria-label*="One-Time PIN" i]',
            'input[aria-label*="One Time PIN" i]',
            'input[autocomplete="one-time-code"]',
            'input[name="code"]',
            'input[name="otp"]',
            'input[name="passcode"]',
            'input[name="securityCode"]',
            'input[id*="code" i]',
            'input[id*="otp" i]',
        ]
        try:
            page.wait_for_selector(", ".join(code_selectors), timeout=10000)
        except PlaywrightTimeout:
            if self._select_email_mfa_factor(page):
                try:
                    page.wait_for_selector(", ".join(code_selectors), timeout=20000)
                except PlaywrightTimeout:
                    pass
                else:
                    return self._fill_and_submit_mfa_code(
                        page,
                        code_selectors,
                        timeout_seconds=timeout_seconds,
                    )
            # No code field rendered. If the page is already past
            # login (session reuse, instant pass-through), nothing
            # to do.
            if self._is_post_login(page):
                return True
            # Otherwise this is a push-approval / phone-app /
            # browser-confirmation factor: the user still has to act,
            # but they act outside the connector — the dashboard MFA
            # modal won't have a code field to fill, so we surface a
            # plain "approve in your browser/app" prompt and poll for
            # post-login state.
            log.info(
                "[mypay] no email-code field after login — broadcasting "
                "push-approval prompt and polling for post-login"
            )
            self._mfa_prompted = True
            try:
                from backend.events import broadcast_event
                from backend import sse_topics

                broadcast_event(
                    sse_topics.MFA_REQUIRED,
                    {
                        "institution": self.institution,
                        "prompt": (
                            "Approve the myPay sign-in in the browser tab or "
                            "your authenticator app. The connector will "
                            "continue automatically once you confirm."
                        ),
                    },
                )
            except Exception as e:
                # SSE bus is best-effort — log and keep polling. The
                # base wait still works without the broadcast.
                log.debug("[mypay] MFA_REQUIRED broadcast failed: %s", e)
            return super()._wait_for_mfa(page, timeout_seconds=timeout_seconds)

        return self._fill_and_submit_mfa_code(
            page,
            code_selectors,
            timeout_seconds=timeout_seconds,
        )

    def _select_email_mfa_factor(self, page: Page) -> bool:
        """Pick myPay's email MFA factor when the factor menu is shown."""
        try:
            selected = page.evaluate(
                """
                () => {
                  const visible = (el) =>
                    !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
                  const labelText = (el) => {
                    const bits = [
                      el.getAttribute("id"),
                      el.getAttribute("name"),
                      el.getAttribute("value"),
                      el.getAttribute("aria-label"),
                    ];
                    if (el.id) {
                      const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                      if (label) bits.push(label.innerText);
                    }
                    const closestLabel = el.closest("label");
                    if (closestLabel) bits.push(closestLabel.innerText);
                    const parent = el.parentElement;
                    if (parent) bits.push(parent.innerText);
                    return bits.filter(Boolean).join(" ").toLowerCase();
                  };
                  const radios = Array.from(
                    document.querySelectorAll('input[type="radio"], [role="radio"]')
                  ).filter(visible);
                  const emailRadio = radios.find((el) => labelText(el).includes("email"));
                  if (!emailRadio) return false;
                  emailRadio.click();
                  return true;
                }
                """
            )
        except Exception as e:
            log.debug("[mypay] email MFA factor probe failed: %s", e)
            return False

        if not selected:
            return False

        next_selectors = [
            'button:has-text("Next")',
            'input[type="submit"][value*="Next" i]',
            'button[type="submit"]',
        ]
        if not self._click_first(page, next_selectors, timeout_ms=5000):
            return False

        page.wait_for_timeout(2500)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except PlaywrightTimeout:
            pass
        return True

    def _fill_and_submit_mfa_code(
        self,
        page: Page,
        code_selectors: list[str],
        *,
        timeout_seconds: int,
    ) -> bool:
        # Email-code path. Mark MFA prompted BEFORE blocking on the
        # provider so refresh_events.mfa_prompted records this attempt
        # even if the wait times out.
        self._mfa_prompted = True
        challenge_started_at = datetime.now()
        log.info(
            "[mypay] MFA challenge detected — awaiting code (timeout=%ds)",
            timeout_seconds,
        )
        code = self._wait_for_code_or_direct_browser_mfa(
            page,
            challenge_started_at=challenge_started_at,
            timeout_seconds=timeout_seconds,
        )
        if code == "__BROWSER_ADVANCED__":
            log.info("[mypay] MFA completed directly in browser")
            return True
        if code is None:
            log.error("[mypay] OTP provider returned no code (timeout)")
            return False

        if not self._fill_first(page, code_selectors, code):
            log.error("[mypay] code field disappeared after code arrived")
            return False

        submit_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Verify")',
            'button:has-text("Submit")',
            'button:has-text("Continue")',
        ]
        if not self._click_first(page, submit_selectors, timeout_ms=5000):
            # Some forms accept Enter on the input.
            try:
                el = page.query_selector(", ".join(code_selectors))
                if el:
                    el.press("Enter")
            except Exception as e:
                log.debug("[mypay] Enter press fallback failed: %s", e)

        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except PlaywrightTimeout:
            pass
        page.wait_for_timeout(2000)
        return self._is_post_login(page) or self._has_password_change_prompt(page)

    def _wait_for_code_or_direct_browser_mfa(
        self,
        page: Page,
        *,
        challenge_started_at: datetime,
        timeout_seconds: int,
    ) -> str | None:
        """Wait for dashboard OTP while accepting direct entry in myPay."""
        result = {"done": False, "code": None}

        def _provider_wait() -> None:
            try:
                result["code"] = self._otp_provider.wait_for_code(
                    self.institution,
                    challenge_started_at=challenge_started_at,
                    hint="dfas.mil",
                    timeout_seconds=timeout_seconds,
                )
            finally:
                result["done"] = True

        waiter = threading.Thread(target=_provider_wait, daemon=True)
        waiter.start()

        deadline = datetime.now().timestamp() + timeout_seconds
        while datetime.now().timestamp() < deadline:
            if result["done"]:
                return result["code"]
            if self._is_post_login(page) or self._has_password_change_prompt(page):
                self._cancel_pending_mfa_bridge()
                return "__BROWSER_ADVANCED__"
            try:
                page.wait_for_timeout(500)
            except Exception:
                threading.Event().wait(0.5)

        self._cancel_pending_mfa_bridge()
        return result["code"] if result["done"] else None

    def _cancel_pending_mfa_bridge(self) -> None:
        """Best-effort cleanup when the user completed MFA in the browser tab."""
        try:
            from backend.mfa_bridge import cancel_wait

            cancel_wait(self.institution)
        except Exception as e:
            log.debug("[mypay] MFA bridge cancel skipped: %s", e)

    # ── Export (download + ingest) ───────────────────────────────────────

    def _trigger_export(
        self, page: Page, accounts: list[AccountConfig]
    ) -> list[Path]:
        """Navigate to the RAS area, download the latest PDF, ingest it.

        Returns the downloaded PDF path so the connector lifecycle's
        "no data collected" branch passes. The returned path is NOT a
        CSV — `backend.result_writer.persist_connector_result` filters
        non-CSV files out of its DataFrame loop, so the PDF cannot
        accidentally enter the transaction-CSV path.

        Raises if the RAS section can't be reached. Returns [] if the
        section was reached but no new RAS is available — that's a
        clean "nothing changed" success, distinct from a failure.
        """
        if not self._navigate_to_ras(page):
            raise RuntimeError(
                "myPay RAS section unreachable — login may have completed "
                "but the RAS link did not appear (UI redesign?)."
            )

        download_path = self._download_latest_ras(page)
        if download_path is None:
            log.info("[mypay] No new RAS available")
            # Mark a synthetic balance entry so the lifecycle's "no
            # data" branch doesn't treat this as an error. The
            # result_writer skips entries whose key starts with
            # "_marker" so no real balance row is written.
            self._result_balances["_marker_no_new_ras"] = {
                "name": "myPay (no new RAS)",
                "balance": "$0.00",
            }
            return []

        # Ingest the downloaded PDF through the shared document-drop
        # path. This writes payroll_snapshots + a committed
        # document_drops row using the same code path the manual
        # `/api/documents/commit` endpoint uses.
        try:
            content = download_path.read_bytes()
        except OSError as e:
            raise RuntimeError(f"Could not read downloaded RAS at {download_path}: {e}")

        summary = ingest_ras_pdf(download_path.name, content)
        self._last_ingest_summary = summary
        log.info(
            "[mypay] Ingested RAS pay_period=%s gross_pay=%s net_pay=%s",
            summary.get("pay_period"),
            _redact_dollar(summary.get("gross_pay")),
            _redact_dollar(summary.get("net_pay")),
        )

        return [download_path]

    # ── Navigation helpers ───────────────────────────────────────────────

    def _navigate_to_ras(self, page: Page) -> bool:
        """Click into the RAS section after login.

        myPay surfaces RAS under a link whose text varies between
        "Retiree Account Statement", "RAS", or "View RAS". Try the
        text variants in order; if a direct link works, follow it.
        """
        self._dismiss_password_change_prompt(page)
        self._dismiss_post_login_interstitial(page)
        candidates = [
            'a[href="#/militaryretired/mras"]',
            'a:has-text("Monthly Retiree Account Statement")',
            'a:has-text("eRAS")',
            'a:has-text("Retiree Account Statement")',
            'a:has-text("View RAS")',
            'a:has-text("RAS")',
            'button:has-text("Retiree Account Statement")',
            'a[href*="RetireePay" i]',
            'a[href*="RAS" i]',
        ]
        for sel in candidates:
            try:
                el = self._first_visible(page, sel)
                if el and el.is_visible():
                    el.click()
                    page.wait_for_timeout(2500)
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=15000)
                    except PlaywrightTimeout:
                        pass
                    return self._is_on_ras_page(page)
            except Exception as e:
                log.debug("[mypay] RAS link probe failed: %s -> %s", sel, e)
        # Maybe we already landed on the RAS page automatically
        return self._is_on_ras_page(page)

    def _dismiss_password_change_prompt(self, page: Page) -> bool:
        """Handle myPay's periodic password-change prompt."""
        if not self._has_password_change_prompt(page):
            return False

        choice = self._choose_password_change_action()
        if choice == "change_now":
            log.info("[mypay] password-change prompt left for user action")
            if self._wait_for_password_change_completion(page):
                log.info("[mypay] password-change flow completed in browser")
                return True
            log.warning(
                "[mypay] password-change wait timed out; trying Remind Me Later"
            )

        return self._click_remind_later_password_change(page)

    def _choose_password_change_action(self) -> str:
        """Ask the dashboard whether to rotate now or defer safely."""
        timeout_seconds = _env_int(
            "MYPAY_PASSWORD_CHANGE_ACTION_TIMEOUT_SECONDS",
            45,
        )
        try:
            from backend.credential_action_bridge import request_action

            return request_action(
                institution=self.institution,
                action="password_change",
                title="myPay password change requested",
                prompt=(
                    "myPay is asking for a password change. Change it now in "
                    "the browser, or choose Remind me later to continue this "
                    "refresh."
                ),
                timeout_seconds=timeout_seconds,
                default_choice="remind_later",
            )
        except Exception as e:
            log.debug("[mypay] credential action prompt failed: %s", e)
            return "remind_later"

    def _click_remind_later_password_change(self, page: Page) -> bool:
        """Click Remind Me Later and record a durable app notification."""
        candidates = [
            'button:has-text("Remind Me Later")',
            'input[type="button"][value*="Remind Me Later" i]',
            'a:has-text("Remind Me Later")',
        ]
        for sel in candidates:
            try:
                el = self._first_visible(page, sel)
                if el and el.is_visible():
                    log.info("[mypay] deferring password-change prompt")
                    try:
                        el.scroll_into_view_if_needed(timeout=5000)
                    except Exception:
                        pass
                    el.click()
                    self._record_password_change_notification()
                    page.wait_for_timeout(2500)
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=15000)
                    except PlaywrightTimeout:
                        pass
                    return True
            except Exception as e:
                log.debug(
                    "[mypay] password-change prompt probe failed: %s -> %s",
                    sel,
                    e,
                )
        return False

    def _wait_for_password_change_completion(
        self,
        page: Page,
        timeout_seconds: int | None = None,
    ) -> bool:
        """Wait until the user finishes the live myPay password-change flow."""
        timeout = (
            _env_int("MYPAY_PASSWORD_CHANGE_COMPLETION_TIMEOUT_SECONDS", 900)
            if timeout_seconds is None
            else max(0, timeout_seconds)
        )
        deadline = time.monotonic() + timeout
        stable_post_login = 0

        while time.monotonic() < deadline:
            try:
                blocked_on_password = (
                    self._has_password_change_prompt(page)
                    or self._has_password_update_form(page)
                )
                if blocked_on_password:
                    stable_post_login = 0
                elif self._is_post_login(page):
                    stable_post_login += 1
                    if stable_post_login >= 3:
                        return True
                else:
                    stable_post_login = 0
                page.wait_for_timeout(1000)
            except Exception:
                threading.Event().wait(1)

        return False

    def _has_password_update_form(self, page: Page) -> bool:
        """Return True when a password-update form is visible."""
        candidates = [
            'input[autocomplete="current-password"]',
            'input[autocomplete="new-password"]',
            'input[name*="current" i][type="password"]',
            'input[name*="new" i][type="password"]',
            'input[id*="current" i][type="password"]',
            'input[id*="new" i][type="password"]',
            'input[type="password"]',
            'button:has-text("Change Password")',
            'button:has-text("Update Password")',
            'input[type="submit"][value*="Change Password" i]',
            'input[type="submit"][value*="Update Password" i]',
        ]
        for sel in candidates:
            try:
                if self._first_visible(page, sel):
                    return True
            except Exception:
                continue
        return False

    def _has_password_change_prompt(self, page: Page) -> bool:
        """Return True when myPay has advanced to its password-change prompt."""
        candidates = [
            'button:has-text("Remind Me Later")',
            'input[type="button"][value*="Remind Me Later" i]',
            'a:has-text("Remind Me Later")',
        ]
        for sel in candidates:
            try:
                if self._first_visible(page, sel):
                    return True
            except Exception:
                continue
        return False

    def _record_password_change_notification(self) -> None:
        """Surface deferred myPay password rotation in the app notification feed."""
        try:
            from dal.database import get_db
            from dal.notifications import record_notification

            now = datetime.now(timezone.utc)
            with get_db() as conn:
                record_notification(
                    conn,
                    type="credential_action_needed",
                    severity="warning",
                    title="myPay password change deferred",
                    body=(
                        "myPay asked for a password change during refresh. "
                        "The connector selected Remind Me Later; update it "
                        "manually before the site requires it."
                    ),
                    payload={"institution": self.institution, "action": "password_change"},
                    dedup_key=f"credential_action_needed:mypay:password_change:{now:%Y-%m}",
                    link="/settings",
                )
                conn.commit()
        except Exception as e:
            log.debug("[mypay] password-change notification failed: %s", e)

    def _dismiss_post_login_interstitial(self, page: Page) -> None:
        """Advance through myPay's post-login message page when present."""
        url = (page.url or "").lower()
        if "#/message" not in url and "/message" not in url:
            return

        candidates = [
            'button:has-text("I agree to the terms of the User Agreement")',
            'button:has-text("Continue")',
            'button:has-text("Accept")',
            'button:has-text("I Agree")',
            'button:has-text("Agree")',
            'button:has-text("OK")',
            'a:has-text("Continue")',
            'a:has-text("Accept")',
            'input[type="submit"]',
        ]
        for sel in candidates:
            try:
                el = self._first_visible(page, sel)
                if el and el.is_visible():
                    log.info("[mypay] dismissing post-login message interstitial")
                    try:
                        el.scroll_into_view_if_needed(timeout=5000)
                    except Exception:
                        pass
                    el.click(force=True)
                    page.wait_for_timeout(2500)
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=15000)
                    except PlaywrightTimeout:
                        pass
                    return
            except Exception as e:
                log.debug("[mypay] message interstitial probe failed: %s -> %s", sel, e)

    def _is_on_ras_page(self, page: Page) -> bool:
        """Heuristic: the RAS page has a "Download" link or RAS in the URL."""
        url = page.url.lower()
        if "#/militaryretired/mras" in url:
            return True
        if any(hint.lower() in url for hint in MYPAY_RAS_URL_HINTS):
            return True
        try:
            if self._first_visible(page, 'select[aria-label="MRAS History Select"]'):
                return True
        except Exception:
            pass
        try:
            body = page.inner_text("body").lower()
        except Exception:
            return False
        return "retiree account statement" in body or "ras" in body[:2000]

    def _download_latest_ras(self, page: Page) -> Optional[Path]:
        """Click the latest RAS link and return the saved PDF path.

        myPay typically lists statements newest-first. We click the
        first PDF link / Download button on the page.
        """
        # Try a download-button trigger first (preferred — Playwright's
        # expect_download captures the response without depending on
        # redirect URLs).
        modal_path = self._download_printable_mras_pdf(page)
        if modal_path is not None:
            return modal_path

        download_triggers = [
            'a:has-text("Download")',
            'button:has-text("Download")',
            'a[href*=".pdf" i]',
            'a:has-text("PDF")',
            'a:has-text("View")',
        ]
        for sel in download_triggers:
            el = self._first_visible(page, sel)
            if el is None or not el.is_visible():
                continue
            try:
                with page.expect_download(timeout=30000) as dl:
                    el.click()
                download = dl.value
            except PlaywrightTimeout:
                log.debug("[mypay] download trigger %s did not produce a download", sel)
                continue
            except Exception as e:
                log.debug("[mypay] download click failed for %s: %s", sel, e)
                continue

            target = self._save_download(download)
            return target
        return None

    def _download_printable_mras_pdf(self, page: Page) -> Optional[Path]:
        """Open myPay's eRAS PDF modal and save its blob-backed PDF bytes."""
        triggers = [
            'button:has-text("Printer Friendly eRAS")',
            'button[data-target="#pdfModal"]',
            "button.mp-print-btn-header",
        ]
        opened = False
        for sel in triggers:
            try:
                el = self._first_visible(page, sel)
                if el and el.is_visible():
                    try:
                        el.scroll_into_view_if_needed(timeout=5000)
                    except Exception:
                        pass
                    el.click()
                    opened = True
                    break
            except Exception as e:
                log.debug("[mypay] printable eRAS trigger failed: %s -> %s", sel, e)
        if not opened:
            return None

        try:
            page.wait_for_selector(
                '#pdfModal iframe[title="MRAS PDF"], #pdfModal iframe[type="application/pdf"]',
                state="visible",
                timeout=15000,
            )
        except PlaywrightTimeout:
            log.debug("[mypay] printable eRAS modal did not expose a PDF iframe")
            return None

        try:
            encoded = page.evaluate(
                """
                async () => {
                  const iframe =
                    document.querySelector('#pdfModal iframe[title="MRAS PDF"]') ||
                    document.querySelector('#pdfModal iframe[type="application/pdf"]');
                  if (!iframe || !iframe.src) return null;
                  const response = await fetch(iframe.src);
                  const buffer = await response.arrayBuffer();
                  let binary = "";
                  const bytes = new Uint8Array(buffer);
                  const chunk = 0x8000;
                  for (let i = 0; i < bytes.length; i += chunk) {
                    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
                  }
                  return btoa(binary);
                }
                """
            )
        except Exception as e:
            log.debug("[mypay] printable eRAS PDF fetch failed: %s", e)
            return None

        if not encoded:
            return None

        try:
            content = base64.b64decode(encoded)
        except Exception as e:
            log.debug("[mypay] printable eRAS PDF decode failed: %s", e)
            return None

        if not content.startswith(b"%PDF"):
            log.debug("[mypay] printable eRAS blob did not look like a PDF")
            return None

        return self._save_pdf_bytes(content)

    def _save_download(self, download) -> Path:
        """Persist a Playwright Download to RAW_DIR with a sanitized name."""
        # Naming: prefer the suggested filename from the site, but
        # always sanitize to a safe ascii-only stem. If we can derive
        # a YYYY-MM from the suggested name, embed it.
        suggested = download.suggested_filename or "ras.pdf"
        suggested_lower = suggested.lower()
        m = re.search(r"(20\d{2})[-_]?(0[1-9]|1[0-2])", suggested_lower)
        period = f"{m.group(1)}-{m.group(2)}" if m else "unknown"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_stem = f"mypay_ras_{period}_{ts}.pdf"
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        target = RAW_DIR / safe_stem
        download.save_as(str(target))
        return target

    # ── Logout ───────────────────────────────────────────────────────────

    def _save_pdf_bytes(self, content: bytes, *, period: str = "unknown") -> Path:
        """Persist PDF bytes captured from an in-page myPay blob."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        target = RAW_DIR / f"mypay_ras_{period}_{ts}.pdf"
        target.write_bytes(content)
        return target

    def _preserve_browser_session_in_dev_mode(self) -> bool:
        """myPay must log out and close its tab even during manual dev runs."""
        return False

    def _perform_logout(self, page: Page) -> None:
        """Close eRAS surfaces, log out, and decline myPay's exit survey."""
        self._close_pdf_modal(page)
        for sel in (
            'a:has-text("Logout")',
            'a:has-text("Log Out")',
            'a:has-text("Sign Out")',
            'button:has-text("Logout")',
            'a[href*="logout" i]',
        ):
            try:
                el = self._first_visible(page, sel)
                if el and el.is_visible():
                    el.click()
                    page.wait_for_timeout(1500)
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except PlaywrightTimeout:
                        pass
                    self._decline_exit_survey(page)
                    return
            except Exception:
                continue
        self._decline_exit_survey(page)

    def _close_pdf_modal(self, page: Page) -> None:
        """Close the eRAS PDF modal if the print-friendly view is still open."""
        for sel in (
            '#pdfModal button[aria-label="Close"]',
            "#pdfModal button.close",
            'button[aria-label="Close"]',
            'button:has-text("Close")',
        ):
            try:
                el = self._first_visible(page, sel)
                if el:
                    el.click(timeout=5000)
                    page.wait_for_timeout(500)
                    return
            except Exception:
                continue

    def _decline_exit_survey(self, page: Page) -> None:
        """Decline myPay's optional logout survey when it appears."""
        try:
            page.wait_for_timeout(1000)
        except Exception:
            pass

        for sel in (
            'button:has-text("No Thanks")',
            'button:has-text("No, Thanks")',
            'button:has-text("No thank you")',
            'button:has-text("No, thank you")',
            'button:has-text("Decline")',
            'button:has-text("Skip")',
            'button:has-text("Not Now")',
            'a:has-text("No Thanks")',
            'a:has-text("No, Thanks")',
            'a:has-text("Decline")',
            'a:has-text("Skip")',
            'input[type="button"][value*="No" i]',
            'input[type="button"][value*="Decline" i]',
        ):
            try:
                el = self._first_visible(page, sel)
                if el:
                    el.click(timeout=5000)
                    page.wait_for_timeout(500)
                    return
            except Exception:
                continue

    # ── Selector helpers ─────────────────────────────────────────────────

    def _wait_for_first(
        self, page: Page, selectors: list[str], *, timeout_ms: int
    ) -> None:
        """Wait until any of the selectors becomes visible. Raises on timeout."""
        page.wait_for_selector(", ".join(selectors), state="visible", timeout=timeout_ms)

    def _fill_first(self, page: Page, selectors: list[str], value: str) -> bool:
        for sel in selectors:
            try:
                el = self._first_visible(page, sel)
                if el and el.is_visible():
                    el.fill(value)
                    return True
            except Exception:
                continue
        return False

    def _click_first(
        self, page: Page, selectors: list[str], *, timeout_ms: int = 5000
    ) -> bool:
        for sel in selectors:
            try:
                el = self._first_visible(page, sel)
                if el and el.is_visible():
                    el.click(timeout=timeout_ms)
                    return True
            except Exception:
                continue
        return False

    def _first_visible(self, page: Page, selector: str):
        """Return the first visible match, tolerating hidden duplicate nodes."""
        elements = []
        try:
            queried = page.query_selector_all(selector)
            if isinstance(queried, (list, tuple)):
                elements = list(queried)
        except Exception:
            elements = []

        if not elements:
            try:
                first = page.query_selector(selector)
                if first is not None:
                    elements = [first]
            except Exception:
                elements = []

        for el in elements:
            try:
                if el and el.is_visible():
                    return el
            except Exception:
                continue
        return None


# ── Module-level ingest entry point ──────────────────────────────────────────


def ingest_ras_pdf(filename: str, content: bytes) -> dict:
    """Ingest a myPay RAS PDF via the shared document-drop helper.

    Exposed as a module-level function so tests can exercise the ingest
    routing without instantiating Playwright. Returns the parser's
    commit summary dict (`{pay_period, gross_pay, net_pay,
    fields_extracted}`).

    The `expected_parser_type="mypay_ras"` guard is enforced inside
    the shared `ingest_document` helper BEFORE any DB write, so a
    non-RAS document that happens to be recognized by another parser
    (e.g. a `tsp_statement` PDF) is refused without ever inserting a
    `document_drops` row, calling `parser.commit`, or dispatching the
    post-commit pipeline.

    Raises `backend.document_ingest.ParseBlockedError` if the parser
    silent-failure guard tripped, or
    `backend.document_ingest.RecognitionError` if recognition failed
    or produced a non-RAS parser_type.
    """
    # Local import keeps this module importable in environments without
    # a database (some unit tests mock get_db).
    from backend.document_ingest import ingest_document

    outcome = ingest_document(
        filename,
        content,
        run_pipeline=True,
        expected_parser_type="mypay_ras",
    )
    return outcome.summary


def _redact_dollar(value) -> str:
    """Render a dollar amount as a redacted log token. Logs see scale, not amount."""
    if value is None:
        return "<none>"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "<unparseable>"
    if amount <= 0:
        return "$0.xx"
    digits = len(str(int(amount)))
    return f"${'9' * digits}.xx"
