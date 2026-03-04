"""
extractors/chase_connector.py — Chase Bank connector.

Concrete InstitutionConnector subclass implementing the Chase-specific
login flow, balance scraping, and transaction CSV download.

Uses the user's actual Chrome instance via CDP. Google Password Manager
handles credential autofill; the script only clicks submit and waits
for MFA. No plaintext credentials are handled in code.

Usage:
    from extractors.chase_connector import ChaseConnector

    connector = ChaseConnector(headless=False)
    result = connector.run(force=True)
    print(result)
"""

import re
import time
import random
import logging
from datetime import datetime
from pathlib import Path

from skills.institution_connector import (
    InstitutionConnector,
    AccountConfig,
)
from extractors.sms_otp import wait_for_otp
from extractors.ai_backstop import (
    resilient_find,
    resilient_click,
    resilient_fill,
    load_selectors,
    get_selector_group,
    reset_ai_counter,
)

log = logging.getLogger("sentry.extractors.chase")


class ChaseConnector(InstitutionConnector):
    """Chase Bank connector.

    Implements a 2-phase export process:
      Phase 1: Scrape balances from the accounts dashboard
      Phase 2: Download transaction CSVs for each configured account
    """

    # ── Required Properties ──────────────────────────────────────────────

    @property
    def institution(self) -> str:
        return "chase"

    @property
    def display_name(self) -> str:
        return "Chase"

    @property
    def export_url(self) -> str:
        return "https://secure.chase.com/web/auth/#/dashboard"

    @property
    def login_url(self) -> str:
        return "https://secure.chase.com"

    # NOTE: No _launch override needed. The base class connects to the
    # user's real Chrome via CDP. Chrome handles its own sessions,
    # cookies, and Password Manager — no Playwright profile needed.

    # ── Session Validation Override ──────────────────────────────────────

    def _is_session_valid(self, page) -> bool:
        """Check if the Chase session is still authenticated.

        Override needed because Chase's dashboard URL contains '/auth/'
        which the base class interprets as a login redirect.
        """
        try:
            response = page.goto(
                self.export_url, wait_until="domcontentloaded", timeout=30000
            )
            # Wait for Chase redirects to settle
            try:
                # We do not wait for a full networkidle because Chase's SPA constantly streams metrics
                page.wait_for_timeout(2000)
            except Exception as e:
                log.debug("Wait timed out: %s", e)

            current = page.url.lower()
            print(f"  🔍  Session check landed on: {current[:80]}")
            self._screenshot(page, "session_check")

            # If we landed on the system requirements page or main site,
            # session is invalid
            if "system-requirements" in current:
                log.info(
                    "[%s] Redirected to system requirements — session invalid",
                    self.institution,
                )
                return False

            if current.startswith("https://www.chase.com"):
                # Redirected away from secure.chase.com — not authenticated
                if "secure.chase.com" not in current:
                    log.info(
                        "[%s] Redirected to public site — session invalid",
                        self.institution,
                    )
                    return False

            # If we end up on a login/signin page (not the dashboard)
            # Chase uses /logon/ for their actual signin SPA
            if any(kw in current for kw in ("signin", "login", "sso", "logon")):
                log.info("[%s] Session expired — redirected to login", self.institution)
                return False

            # HTTP error status
            if response and response.status >= 400:
                log.info(
                    "[%s] Session check got HTTP %d", self.institution, response.status
                )
                return False

            # If we're on secure.chase.com with dashboard in the URL,
            # verify the SPA has actually rendered account content.
            # (A blank page means no auth tokens — session is invalid.)
            if "secure.chase.com" in current and "dashboard" in current:
                # Wait up to 10s for content to appear
                for _ in range(5):
                    try:
                        body = page.inner_text("body").strip()
                        if re.search(r"\$[\d,]+\.\d{2}", body) or len(body) > 500:
                            log.info(
                                "[%s] Session valid — skipping login", self.institution
                            )
                            return True
                    except Exception as e:
                        log.debug("Ignored exception: %s", e)
                    page.wait_for_timeout(2000)

                # Page stayed blank — session is invalid
                log.info(
                    "[%s] Dashboard URL valid but page blank — session invalid",
                    self.institution,
                )
                self._screenshot(page, "session_blank")
                return False

            # Otherwise, assume invalid
            log.info(
                "[%s] Unexpected URL after session check: %s", self.institution, current
            )
            return False

        except Exception as e:
            log.warning("[%s] Session check failed: %s", self.institution, e)
            return False

    # ── Login ────────────────────────────────────────────────────────────

    def _perform_login(self, page, credentials: dict | None = None) -> bool:
        """Navigate to Chase login and authenticate.

        Two credential paths:
          A) Broker credentials (credentials dict provided):
             Fill username/password fields directly, then submit.
          B) Password Manager autofill (credentials=None):
             Wait for Google Password Manager to autofill, then submit.

        In both cases, MFA is handled by the lifecycle's _wait_for_mfa.
        """
        reset_ai_counter()
        reg = load_selectors()

        # Check if we're already on a page with login fields
        form_group = get_selector_group(reg, "chase.login.form_detect")
        has_login_form = False
        if form_group:
            el = resilient_find(page, form_group, timeout=2)
            if el:
                has_login_form = True
                print("       \u2714 Login form found on current page")

        if not has_login_form:
            # No login form - navigate to chase.com
            print("  \U0001f310  Navigating to Chase...")
            page.goto(self.login_url, wait_until="domcontentloaded", timeout=30000)
            try:
                # Instead of networkidle, just wait for DOM to be ready
                pass
            except Exception as e:
                log.debug("Wait timed out: %s", e)

        # Dismiss popups (cookie banners, etc.)
        self._dismiss_popups(page)
        self._screenshot(page, "login_page")
        self._human_jitter(0.5, 1.0)

        # Click "Sign in" button if the username field isn't visible
        username_group = get_selector_group(reg, "chase.login.username")
        el = resilient_find(page, username_group, timeout=2) if username_group else None
        if not el:
            signin_group = get_selector_group(reg, "chase.login.signin_button")
            if signin_group:
                resilient_click(page, signin_group)
                try:
                    if username_group and username_group["selectors"]:
                        page.wait_for_selector(
                            username_group["selectors"][0],
                            state="visible",
                            timeout=10000,
                        )
                except Exception as e:
                    log.debug("Wait for username visible timed out: %s", e)

        # ── Path A: Broker credentials ─────────────────────────────
        if credentials and credentials.get("username") and credentials.get("password"):
            self._current_password = credentials.get(
                "password"
            )  # Store for MFA dual-field prompt
            print("  🔑  Filling credentials from broker...")
            filled = self._fill_credentials(page, reg, credentials)
            if not filled:
                log.warning(
                    "[%s] Broker credential fill failed, falling back to autofill",
                    self.institution,
                )
                # Fall through to Path B
            else:
                # Check "Remember me"
                self._check_remember_me(page, reg)
                # Submit
                submit_group = get_selector_group(reg, "chase.login.submit")
                if submit_group:
                    resilient_click(page, submit_group, allow_ai=False)
                    print("  \u2714  Login submitted (broker)")

                # Wait for the login form to disappear instead of waiting unconditionally
                try:
                    # Explicit wait for a post-login state (either dashboard or MFA screen)
                    page.wait_for_function(
                        """() => {
                            const url = window.location.href;
                            const hasPassword = document.querySelector('input[type="password"]');
                            const hasOtp = document.querySelector('input[id*="password_input_abc"], input[id="password_input-input-field"], input[name*="otp"], input[type="number"]:visible');
                            const hasPush = document.querySelector('a:has-text("Confirm using our mobile app")');
                            return url.includes("dashboard") || hasPassword || hasOtp || hasPush;
                        }""",
                        timeout=15000,
                    )
                except Exception as e:
                    log.debug("Wait for post-login state timed out: %s", e)

                self._screenshot(page, "after_submit")
                return True  # MFA handled by lifecycle

        # ── Path B: Password Manager autofill ──────────────────────
        print("  \u23f3  Waiting for Password Manager autofill...")
        autofill_ok = self._wait_for_autofill(page, reg)

        if autofill_ok:
            self._check_remember_me(page, reg)
            # Submit via registry
            submit_group = get_selector_group(reg, "chase.login.submit")
            if submit_group:
                resilient_click(page, submit_group, allow_ai=False)
                print("  \u2714  Login submitted (autofill)")
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception as e:
                log.debug("Wait timed out: %s", e)
            self._screenshot(page, "after_submit")
        else:
            print("  \u26a0  Autofill not detected \u2014 please log in manually")
            self._screenshot(page, "autofill_not_detected")

        return True  # MFA handled by _wait_for_mfa

    def _check_remember_me(self, page, reg: dict):
        """Check the 'Remember me' checkbox if present."""
        remember_group = get_selector_group(reg, "chase.login.remember_me")
        if remember_group:
            for sel in remember_group["selectors"]:
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        if not el.is_checked():
                            el.click()
                            print("       \u2714 Checked 'Remember me'")
                        break
                except Exception as e:
                    log.debug("Remember me selector %s failed: %s", sel, e)
                    continue

    def _fill_credentials(self, page, reg: dict, credentials: dict) -> bool:
        """Fill username and password fields from broker-provided credentials.

        Uses the same selector registry as autofill detection.
        Returns True if both fields were filled successfully.
        """
        try:
            # Fill username
            user_group = get_selector_group(reg, "chase.login.username")
            if user_group:
                el = resilient_find(page, user_group, timeout=5)
                if el:
                    el.click()
                    el.fill(credentials["username"])
                    log.info("[%s] Username field filled", self.institution)
                else:
                    log.warning("[%s] Username field not found", self.institution)
                    return False

            # Fill password
            pw_group = get_selector_group(reg, "chase.login.password")
            if pw_group:
                el = resilient_find(page, pw_group, timeout=5)
                if el:
                    el.click()
                    el.fill(credentials["password"])
                    log.info("[%s] Password field filled", self.institution)
                else:
                    log.warning("[%s] Password field not found", self.institution)
                    return False

            return True
        except Exception as e:
            log.error("[%s] Credential fill failed: %s", self.institution, e)
            return False

    def _wait_for_autofill(self, page, reg: dict, timeout: int = 30) -> bool:
        """Poll login form fields until Password Manager fills them.

        Returns True if both username and password fields have values.
        Also checks iframes (Chase may embed login in an iframe).
        """
        username_group = get_selector_group(reg, "chase.login.username")
        password_group = get_selector_group(reg, "chase.login.password")

        if not username_group or not password_group:
            log.warning("Login selector groups not found in registry")
            return False

        for _ in range(timeout):
            page.wait_for_timeout(1000)
            try:
                # Check main page first
                u_el = resilient_find(page, username_group, timeout=0)
                p_el = resilient_find(page, password_group, timeout=0)

                # If not on main page, try iframes
                if not u_el or not p_el:
                    for frame in page.frames:
                        if frame == page.main_frame:
                            continue
                        if not u_el:
                            u_el = resilient_find(frame, username_group, timeout=0)
                        if not p_el:
                            p_el = resilient_find(frame, password_group, timeout=0)

                u_val = u_el.input_value() if u_el else ""
                p_val = p_el.input_value() if p_el else ""

                if u_val and p_val:
                    log.info("Password Manager autofill detected")
                    return True
            except Exception as e:
                log.debug("Autofill check failed: %s", e)

        return False

    def _wait_for_mfa(self, page, timeout_seconds: int = 300):
        """Auto-detect login/MFA completion for Chase.

        Override the base class because Chase uses '/auth/' in its
        dashboard URL which would confuse the generic keyword check.
        We specifically look for the secure dashboard instead.
        """
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception as e:
            log.debug("Wait timed out: %s", e)

        # If already on the authenticated dashboard, no MFA needed
        current = page.url.lower()
        if "secure.chase.com" in current and "dashboard" in current:
            try:
                body = page.inner_text("body").strip()
                if re.search(r"\$[\d,]+\.\d{2}", body) or len(body) > 500:
                    log.info(
                        "[%s] Already on dashboard \u2014 no MFA needed",
                        self.institution,
                    )
                    return
            except Exception as e:
                log.debug("Ignored exception: %s", e)

        # Not on dashboard yet - wait for user to complete MFA
        print()
        print(
            "  \u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510"
        )
        print("  \u2502  [Chase] Waiting for login/MFA...              \u2502")
        print("  \u2502                                                  \u2502")
        print("  \u2502  Complete authentication in the browser.         \u2502")
        print("  \u2502  The script will continue automatically.         \u2502")
        print(
            "  \u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518"
        )
        print()

        polls = timeout_seconds // 2
        otp_requested = False
        sms_selection_clicked = False

        for i in range(polls):
            page.wait_for_timeout(2000)
            try:
                # ── SMS Selection Phase (Chase asks HOW to send the code) ──
                if not sms_selection_clicked:
                    sms_radio = None
                    sms_parent = None

                    # Search for radio buttons
                    radios = page.query_selector_all('input[type="radio"]')
                    for r in radios:
                        try:
                            parent = r.evaluate_handle("el => el.parentElement")
                            text = parent.inner_text().lower()
                            # Prioritize "text" and "1459"
                            if "text" in text and "1459" in text:
                                sms_radio = r
                                sms_parent = parent.as_element()
                                break
                            # Fallback: just "text" if we can't find 1459
                            elif "text" in text and not sms_radio:
                                sms_radio = r
                                sms_parent = parent.as_element()
                        except Exception:
                            continue

                    # If no radio button found, check for a Select dropdown
                    sms_dropdown_selected = False
                    if not sms_radio:
                        dropdowns = page.query_selector_all("select")
                        for dropdown in dropdowns:
                            try:
                                options = dropdown.query_selector_all("option")
                                for opt in options:
                                    text = opt.inner_text().lower()
                                    if "text" in text and "1459" in text:
                                        value = opt.get_attribute("value")
                                        if value:
                                            dropdown.select_option(value=value)
                                            sms_dropdown_selected = True
                                            log.info(
                                                "[%s] SMS delivery selection found via Dropdown. Selected.",
                                                self.institution,
                                            )
                                            break
                            except Exception:
                                continue
                            if sms_dropdown_selected:
                                break

                    # Check for Chase's custom div dropdown menu (listbox)
                    if not sms_radio and not sms_dropdown_selected:
                        # 1. First, we must expand the dropdown menu
                        # Playwright codegen observed this as a button: "Tell us how: Choose one"
                        dropdown_btn = page.query_selector(
                            'button:has-text("Choose one"), button:has-text("Tell us how")'
                        )
                        if dropdown_btn and dropdown_btn.is_visible():
                            try:
                                dropdown_btn.click(force=True)
                                page.wait_for_timeout(1000)
                            except Exception as e:
                                log.debug("Failed opening custom dropdown: %s", e)

                        custom_dropdown = page.query_selector(
                            'div[id*="dropdownoptions"]'
                        )
                        if custom_dropdown and custom_dropdown.is_visible():
                            try:
                                custom_dropdown.click(force=True)
                                page.wait_for_timeout(1000)

                                # Find options containing 1459
                                # The first 1459 we encounter is usually under "TEXT ME"
                                listbox_opts = page.query_selector_all(
                                    'ul[role="listbox"] a, ul[role="listbox"] li'
                                )
                                for opt in listbox_opts:
                                    if opt.is_visible():
                                        try:
                                            text = opt.inner_text().lower()
                                            if "1459" in text:
                                                opt.click(force=True)
                                                sms_dropdown_selected = True
                                                log.info(
                                                    "[%s] SMS delivery selection found via custom Listbox. Selected.",
                                                    self.institution,
                                                )
                                                page.wait_for_timeout(500)
                                                break
                                        except Exception:
                                            continue
                            except Exception as e:
                                log.debug("Failed checking custom dropdown: %s", e)
                    # Check for "Confirm using our mobile app" Push Notification fallback
                    if not sms_radio and not sms_dropdown_selected:
                        push_link = page.query_selector(
                            'a:has-text("Confirm using our mobile app"), button:has-text("Confirm using our mobile app"), label:has-text("Confirm using our mobile app")'
                        )
                        if push_link and push_link.is_visible():
                            log.info(
                                "[%s] SMS option not found. Selecting Push Notification...",
                                self.institution,
                            )
                            push_link.click()
                            page.wait_for_timeout(2000)

                            # Select specific device if present, or generic radio
                            device_select = page.query_selector(
                                'text="Samsung Galaxy S23 Ultra"'
                            )
                            if device_select and device_select.is_visible():
                                device_select.click()
                            else:
                                dev_radio = page.query_selector('input[type="radio"]')
                                if dev_radio:
                                    try:
                                        dev_radio.click(force=True)
                                    except Exception:
                                        pass

                            next_btn = page.query_selector(
                                'button[type="submit"]:has-text("Next"), button:has-text("Next")'
                            )
                            if next_btn:
                                next_btn.click()

                            log.info(
                                "[%s] Push notification sent. Please approve it on your phone.",
                                self.institution,
                            )
                            # Wait for the next screen (dashboard or success message) rather than a fixed 3s delay
                            try:
                                page.wait_for_load_state("networkidle", timeout=15000)
                            except Exception as e:
                                log.debug("Wait for push approval timeout: %s", e)
                            self._human_jitter()
                            sms_selection_clicked = True
                            otp_requested = True  # Skip OTP interception block since push is passive

                    if sms_radio or sms_dropdown_selected:
                        log.info(
                            "[%s] SMS delivery selection found. Selecting SMS.",
                            self.institution,
                        )
                        try:
                            if sms_radio:
                                # Try clicking the radio directly first
                                try:
                                    sms_radio.click(force=True, timeout=1000)
                                except Exception:
                                    # If the input isn't clickable, click the parent label container
                                    if sms_parent:
                                        sms_parent.click(force=True)

                            page.wait_for_timeout(500)

                            # Click the Next/Request code button
                            next_btn = page.query_selector(
                                'button[type="submit"]:has-text("Next"), button[type="submit"]:has-text("Request")'
                            )
                            if next_btn:
                                next_btn.click()
                                log.info(
                                    "[%s] Clicked to request SMS. Waiting for input field.",
                                    self.institution,
                                )
                                sms_selection_clicked = True

                                # Wait specifically for the OTP field to appear instead of a arbitrary 3s delay
                                try:
                                    # Use the known spinbutton locator to wait for the field
                                    spin_locator = page.get_by_role(
                                        "spinbutton", name="One-time code"
                                    )
                                    # Or fallback to network idle if that specific role doesn't appear
                                    if not spin_locator.is_visible(timeout=5000):
                                        page.wait_for_load_state(
                                            "networkidle", timeout=10000
                                        )
                                except Exception as e:
                                    log.debug("Wait for OTP field timeout: %s", e)

                                self._human_jitter(0.5, 1.0)
                        except Exception as e:
                            log.debug("Failed to click SMS selection: %s", e)

                # ── SMS OTP Interception Phase ──
                # If we haven't already tried to fill an OTP and the page has the code field:
                if not otp_requested:
                    # Chase's OTP field id is often password_input-input-field or similar
                    # Note: We do not restrict by type="tel" because Chase sometimes renders it as type="password"
                    # Playwright codegen observed this as a spinbutton
                    otp_field = page.query_selector(
                        'input[id*="password_input_abc"], input[id="password_input-input-field"], input[name*="otp"], input[type="number"]:visible'
                    )

                    if not otp_field:
                        try:
                            # Fallback to the Playwright codegen exact locator
                            spin_btn = page.get_by_role(
                                "spinbutton", name="One-time code"
                            )
                            if spin_btn.is_visible(timeout=500):
                                otp_field = spin_btn.element_handle()
                        except Exception:
                            pass

                    if otp_field and otp_field.is_visible():
                        log.info(
                            "[%s] SMS OTP prompt detected. Intercepting via Phone Link...",
                            self.institution,
                        )
                        otp_requested = True

                        # Wait for the toast via sms_otp.py
                        # Increased timeout to 120 seconds to give Phone Link more time to sync
                        code = wait_for_otp(timeout=120, hint="Chase")

                        if code:
                            log.info(
                                "[%s] Filling intercepted OTP: %s***",
                                self.institution,
                                code[:2],
                            )
                            # We MUST force the value using keyboard to mimic human typing
                            try:
                                otp_field.focus()
                                otp_field.fill("")
                                page.keyboard.type(code, delay=50)
                                page.wait_for_timeout(500)
                            except Exception as e:
                                log.debug("Failed to type OTP: %s", e)

                            # Check if Chase also requires the password again (dual-field prompt)
                            password_field = None

                            try:
                                otp_box = otp_field.bounding_box()
                                # Chase sometimes renders the OTP field as type="password" or type="text".
                                # Check all visible inputs that could be the password field.
                                candidates = page.query_selector_all(
                                    'input[type="password"]:visible, input[name*="assword"]:visible, input[aria-label*="assword"]:visible'
                                )

                                for cand in candidates:
                                    box = cand.bounding_box()
                                    # Skip if it perfectly overlaps the OTP field
                                    if (
                                        box
                                        and otp_box
                                        and abs(box["x"] - otp_box["x"]) < 2
                                        and abs(box["y"] - otp_box["y"]) < 2
                                    ):
                                        continue

                                    # It's a distinct field that looks like a password input
                                    password_field = cand
                                    break

                                if not password_field:
                                    # Fallback to the Playwright codegen locator
                                    pw_btn = page.get_by_role(
                                        "textbox",
                                        name=re.compile("password", re.IGNORECASE),
                                    )
                                    if pw_btn.count() > 0 and pw_btn.first.is_visible(
                                        timeout=500
                                    ):
                                        cand = pw_btn.first.element_handle()
                                        box = cand.bounding_box()
                                        if (
                                            box
                                            and otp_box
                                            and abs(box["x"] - otp_box["x"]) < 2
                                            and abs(box["y"] - otp_box["y"]) < 2
                                        ):
                                            pass
                                        else:
                                            password_field = cand

                            except Exception as e:
                                log.debug("Password field check failed: %s", e)

                            if (
                                password_field
                                and hasattr(self, "_current_password")
                                and self._current_password
                            ):
                                log.info(
                                    "[%s] Additional password field detected. Typing password...",
                                    self.institution,
                                )
                                # Fill via keyboard type so React natively picks it up
                                try:
                                    password_field.focus()
                                    password_field.fill("")
                                    page.keyboard.type(self._current_password, delay=30)
                                except Exception as e:
                                    log.debug("Failed to type password: %s", e)

                                page.wait_for_timeout(1000)
                                # Deliberately DO NOT clean up the password variable here.
                                # If the submit click fails or the page rejects the OTP, the loop will retry,
                                # but `otp_requested` will block the retry logic. We might need it later, or it'll securely dump when object dies.

                            # Click the Next / Submit button
                            submit = page.query_selector(
                                'button[id="log_on_to_landing_page-sm"], '
                                'button[type="submit"]:has-text("Next"), '
                                'button[type="submit"]:has-text("Sign in"), '
                                'button[id="requestIdentificationCode"], '
                                'button:has-text("Next")'
                            )
                            # Add an aggressive check for the Sign in button which appears on the dual field screen
                            if not submit and password_field:
                                submit = page.query_selector(
                                    'button[type="submit"], button#signin-button'
                                )

                            self._human_jitter(0.5, 1.0)
                            if submit and submit.is_visible():
                                submit.click()
                                log.info(
                                    "[%s] Clicked submit button after OTP/Password",
                                    self.institution,
                                )
                                # Reset otp_requested if we fail, so the script can try again. Wait to reset it until after we check for success.
                                page.wait_for_timeout(2000)
                                if page.query_selector(
                                    'input[type="password"]:visible, input[id*="password_input_abc"]:visible'
                                ):
                                    log.debug(
                                        "Submit seems to have failed or page refreshed. Allowing retry."
                                    )
                                    otp_requested = False
                            else:
                                if password_field:
                                    log.debug(
                                        "[%s] Next button not visible, pressing Enter on Password field",
                                        self.institution,
                                    )
                                    password_field.press("Enter")
                                else:
                                    log.debug(
                                        "[%s] Next button not visible, pressing Enter on OTP field",
                                        self.institution,
                                    )
                                    otp_field.press("Enter")

                                page.wait_for_timeout(2000)
                                if page.query_selector(
                                    'input[type="password"]:visible, input[id*="password_input_abc"]:visible'
                                ):
                                    otp_requested = False

                            # Give the SPA a fraction of a second to lock the fields before waiting on network
                            self._human_jitter(0.5, 1.0)
                            try:
                                page.wait_for_load_state("networkidle", timeout=15000)
                            except Exception as e:
                                log.debug("Wait for OTP submission timeout: %s", e)

                current = page.url.lower()

                # Chase URL structure: secure.chase.com/web/auth/#/{fragment}
                # Login/MFA pages: #/logon/..., #/logon/processStatus/...
                # Dashboard/post-auth: #/dashboard/..., #/index/...
                # Strategy: extract the hash fragment and check if it
                # still starts with a login-related path.

                # Check 1: URL has 'dashboard' — definitely post-MFA
                if "secure.chase.com" in current and "dashboard" in current:
                    log.info("[%s] Login/MFA completed (dashboard)", self.institution)
                    self._screenshot(page, "after_mfa")
                    return

                # Check 2: URL is on secure.chase.com but NOT on a
                # login/MFA path fragment
                if "secure.chase.com" in current:
                    # Extract the hash fragment (after #/)
                    hash_idx = current.find("#/")
                    fragment = current[hash_idx + 2 :] if hash_idx >= 0 else ""

                    # These are the login/MFA path prefixes
                    login_fragments = (
                        "logon/",
                        "signin/",
                        "login/",
                        "challenge/",
                        "otp/",
                        "verify/",
                    )

                    if fragment and not any(
                        fragment.startswith(frag) for frag in login_fragments
                    ):
                        log.info(
                            "[%s] Login/MFA completed (URL: %s)",
                            self.institution,
                            current[:80],
                        )
                        self._screenshot(page, "after_mfa")
                        return

                # Check 3: DOM-based — login form is gone and page
                # has account-like content
                if "secure.chase.com" in current:
                    try:
                        pw_visible = page.query_selector(
                            'input[type="password"]:visible'
                        )
                        if not pw_visible:
                            body = page.inner_text("body").strip()
                            if len(body) > 500 and re.search(r"\$[\d,]+\.\d{2}", body):
                                log.info(
                                    "[%s] Login/MFA completed (DOM)", self.institution
                                )
                                self._screenshot(page, "after_mfa")
                                return
                    except Exception as e:
                        log.debug("Ignored exception: %s", e)

            except Exception as e:
                log.debug("URL poll failed: %s", e)

            if i > 0 and i % 15 == 0:
                elapsed = i * 2
                print(f"  ⏳  Still waiting... ({elapsed}s / {timeout_seconds}s)")

        log.warning(
            "[%s] MFA wait timed out after %ds", self.institution, timeout_seconds
        )
        self._screenshot(page, "mfa_timeout")

    # ── Logout ────────────────────────────────────────────────────────────

    def _perform_logout(self, page) -> None:
        """Log out of Chase after export.

        Strategy:
          1. Navigate to the sign-out hash fragment
          2. Verify redirect to login/landing page
          3. Fallback: click the profile menu → Log Out
        """
        log.info("[%s] Logging out...", self.institution)

        try:
            # Strategy 1: Navigate to the sign-out route
            # Chase's SPA uses #/dashboard/signOut as the sign-out route
            page.goto(
                "https://secure.chase.com/web/auth/#/dashboard/signOut",
                wait_until="domcontentloaded",
                timeout=15000,
            )
            page.wait_for_timeout(3000)

            # Verify we landed on a signed-out page
            current = page.url.lower()
            if (
                "secure.chase.com" not in current
                or "logon" in current
                or "www.chase.com" in current
            ):
                print("  🔓  Logged out of Chase")
                log.info("[%s] Logout complete (sign-out URL)", self.institution)
                return

            # Strategy 2: Click the Log Out link in the UI
            signout_selectors = [
                'a:has-text("Log Out")',
                'button:has-text("Log Out")',
                'a:has-text("Sign Out")',
                'a[href*="signOut"]',
                '[data-testid="signout"]',
            ]
            for sel in signout_selectors:
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        page.wait_for_timeout(2000)
                        print("  🔓  Logged out of Chase")
                        log.info("[%s] Logout complete (UI click)", self.institution)
                        return
                except Exception:
                    continue

            # If nothing worked, log a warning but don't fail
            log.warning(
                "[%s] Could not confirm logout, session may persist", self.institution
            )
            print("  🔓  Logged out of Chase (unconfirmed)")

        except Exception as e:
            raise RuntimeError(f"Chase logout failed: {e}") from e

    def _trigger_export(self, page, accounts: list[AccountConfig]) -> list[Path]:
        """Execute the full Chase export process."""

        downloaded_files = []
        self._account_ids: dict[str, str] = {}  # last4 -> internal Chase account ID

        # Randomize the processing order to defeat behavioral footprinting
        # of traversing accounts in the exact same array sequence every time.
        accounts = list(accounts)  # clone the list
        random.shuffle(accounts)

        # Capture the dashboard URL — this is where we land post-login.
        self._dashboard_url = page.url
        print(f"  📍  Dashboard URL: {self._dashboard_url}")

        # Intercept Chase API responses to discover internal account IDs.
        # Chase's SPA fetches account data via XHR; we capture last4 -> ID mapping.
        def _on_response(response):
            try:
                url = response.url
                if (
                    "gateway.chase.com" in url
                    or "api.chase.com" in url
                    or "accountSummary" in url
                    or "/accounts" in url
                ):
                    try:
                        body = response.json()
                        self._extract_account_ids(body)
                    except Exception as e:
                        log.debug("Ignored exception: %s", e)
            except Exception as e:
                log.debug("Ignored exception: %s", e)

        page.on("response", _on_response)

        # Wait for the SPA to render account content.
        # Chase uses client-side rendering; the page body may be empty
        # for several seconds after navigation.
        self._wait_for_dashboard_content(page)

        # Give API calls a moment to complete
        page.wait_for_timeout(2000)
        page.remove_listener("response", _on_response)

        if self._account_ids:
            log.info("[chase] Discovered account IDs: %s", self._account_ids)
        else:
            log.info("[chase] No account IDs via network — will use DOM navigation")

        self._screenshot(page, "dashboard")

        # Diagnostic: dump page structure to help debug selectors
        self._dump_page_diagnostics(page)

        # ── Phase 1: Balances ────────────────────────────────────────
        balance_accounts = [a for a in accounts if a.balance]
        if balance_accounts:
            print(f"\n  ── Phase 1: Balances ({len(balance_accounts)} accounts) ──")
            self._scrape_balances(page, balance_accounts)

        # ── Phase 2: Transaction CSVs ────────────────────────────────
        txn_accounts = [a for a in accounts if a.transactions]
        if txn_accounts:
            print(f"\n  ── Phase 2: Transactions ({len(txn_accounts)} accounts) ──")
            for acct in txn_accounts:
                csv_path = self._download_account_csv(page, acct)
                if csv_path:
                    downloaded_files.append(csv_path)

        return downloaded_files

    def _extract_account_ids(self, data, depth: int = 0):
        """Recursively search a JSON response for account last4 -> ID mappings."""
        if depth > 6 or not data:
            return
        if isinstance(data, dict):
            acct_id = (
                data.get("accountId") or data.get("id") or data.get("accountNumber")
            )
            last4 = None
            for key in (
                "last4",
                "lastFour",
                "maskedAccountNumber",
                "accountNumberLast4",
                "displayAccountNumber",
            ):
                val = data.get(key, "")
                if val and len(str(val)) >= 4:
                    last4 = str(val)[-4:]
                    break
            if acct_id and last4 and last4.isdigit():
                self._account_ids[last4] = str(acct_id)
            for v in data.values():
                self._extract_account_ids(v, depth + 1)
        elif isinstance(data, list):
            for item in data:
                self._extract_account_ids(item, depth + 1)

    # ── Phase 1: Balance Scraping ─────────────────────────────────────────

    def _scrape_balances(self, page, accounts: list[AccountConfig]):
        """Scrape balance values from the Chase dashboard."""
        self._ensure_overview_page(page)

        # Scroll to the bottom and back to trigger lazy-loaded tiles
        # (credit card tiles like Slate Edge load after the fold)
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1000)
        except Exception as e:
            log.debug("Ignored exception: %s", e)

        for acct in accounts:
            balance, avail_credit = self._find_balance(page, acct)
            if balance is not None:
                result = {
                    "name": acct.name,
                    "last4": acct.last4,
                    "type": acct.type,
                    "balance": balance,
                    "scraped_at": datetime.now().isoformat(),
                }
                if avail_credit:
                    result["available_credit"] = avail_credit
                self._result_balances[acct.last4] = result

                credit_info = f" (avail credit: {avail_credit})" if avail_credit else ""
                print(f"       ✔ [{acct.last4}] {acct.name}: {balance}{credit_info}")
            else:
                print(f"       ✗ [{acct.last4}] {acct.name}: balance not found")

    def _find_balance(self, page, acct: AccountConfig) -> tuple[str | None, str | None]:
        """Find the balance (and available credit) for an account.

        Uses JavaScript to extract the innerHTML of all account tiles,
        then uses Python regex to find the matching last4 and extract
        the associated balance. This bypasses issues where checking account
        names are hidden inside Shadow DOMs (<mds-button text="...8973">).
        """
        try:
            # Extract raw HTML from all account tiles
            tiles_html = page.evaluate("""() => {
                const tiles = Array.from(document.querySelectorAll('[data-testid="accountTile"]'));
                return tiles.map(t => t.innerHTML);
            }""")

            for html in tiles_html:
                # Check if this tile belongs to the target account
                if acct.last4 not in html:
                    continue

                # Fallback: Sometimes Chase puts the balance in a sibling tile or slightly different format.
                # However, the standard `accountTile` wraps the whole row.

                # Extract the primary balance
                balance_match = re.search(r"\$[\d,]+\.\d{2}", html)
                balance = balance_match.group(0) if balance_match else None

                # Extract available credit if present
                avail_credit = None
                credit_match = re.search(
                    r"(\$[\d,]+\.\d{2})\s*Available credit", html, re.IGNORECASE
                )
                if credit_match:
                    avail_credit = credit_match.group(1)
                elif "Available credit" in html:
                    # Look for the last dollar amount in the HTML if the structure changed
                    amounts = re.findall(r"\$[\d,]+\.\d{2}", html)
                    if len(amounts) >= 2:
                        avail_credit = amounts[-1]

                if balance:
                    log.info(
                        "[%s] Regex found tile for %s: balance=%s",
                        self.institution,
                        acct.last4,
                        balance,
                    )
                    return balance, avail_credit

            log.warning(
                "[%s] Could not find account tile containing %s",
                self.institution,
                acct.last4,
            )

        except Exception as e:
            print(f"       ⚠ Error finding balance for {acct.last4}: {e}")

        return None, None

    # ── Phase 2: Transaction CSV Download ─────────────────────────────────

    def _download_account_csv(self, page, acct: AccountConfig) -> Path | None:
        """Navigate to an account and download its transaction CSV.

        Chase download flow (observed from screenshots):
        1. From account activity page, click the download icon (↓)
        2. This navigates to a "Download account activity" form page
        3. The form has 3 dropdowns (Account, File type, Activity)
           — all pre-populated correctly (File type = "Spreadsheet Excel, CSV")
        4. Click the blue "Download" button to trigger CSV download
        """
        print(f"\n       [{acct.last4}] {acct.name}...")

        # Navigate to the account page
        self._ensure_overview_page(page)
        if not self._click_account(page, acct):
            log.warning(
                "[%s] Could not find account link for %s — using download form directly",
                self.institution,
                acct.last4,
            )
            # Take a screenshot NOW (before try) so we always see what page we're on
            self._screenshot(page, f"before_direct_form_{acct.last4}")
            try:
                return self._navigate_to_download_form(page, acct)
            except Exception as nav_err:
                log.exception(
                    "[%s] _navigate_to_download_form failed for %s",
                    self.institution,
                    acct.last4,
                )
                self._screenshot(page, f"form_nav_error_{acct.last4}")
                print(
                    f"       ✗ [{acct.last4}] Skipping — download form navigation failed"
                )
                return None

        # Wait for account detail page to load
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception as e:
            log.debug("Wait timed out: %s", e)
        page.wait_for_timeout(3000)

        self._screenshot(page, f"account_{acct.last4}")
        self._dismiss_popups(page)

        # ── Step 1: Expand date range to "Last 90 days" before downloading ──
        # The default "Activity since last statement" may show no transactions
        # for cards with zero recent activity. Expanding the range ensures we
        # capture any historical transactions.
        try:
            expanded = page.evaluate("""() => {
                // Find the "Showing" dropdown and select a broader range
                const selects = document.querySelectorAll('select');
                for (const sel of selects) {
                    for (const opt of sel.options) {
                        const t = opt.text.toLowerCase();
                        if (t.includes('90') || t.includes('all') || t.includes('year')) {
                            sel.value = opt.value;
                            sel.dispatchEvent(new Event('change', {bubbles: true}));
                            return opt.text;
                        }
                    }
                }
                return null;
            }""")
            if expanded:
                log.info("[%s] Expanded date range to: %s", self.institution, expanded)
                page.wait_for_timeout(2000)
        except Exception as e:
            log.debug("Ignored exception: %s", e)

        # ── Step 2: Find and click the download icon on the activity page ──
        download_icon = None
        icon_selectors = [
            'button[aria-label*="download" i]',
            'button[aria-label*="export" i]',
            'a:has-text("Download account activity")',
            'button:has-text("Download account activity")',
        ]
        for sel in icon_selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    download_icon = el
                    print(f"       ✔ Found download icon: {sel}")
                    break
            except Exception:
                continue

        if not download_icon:
            log.warning(
                "[%s] No download icon found for %s — skipping",
                self.institution,
                acct.last4,
            )
            self._screenshot(page, f"no_download_{acct.last4}")
            print(f"       ✗ [{acct.last4}] No download icon found — skipped")
            return None

        # Check if the download icon is disabled (no activity to download)
        # Chase doesn't set the 'disabled' DOM attribute — instead it shows a
        # tooltip and doesn't navigate. We detect this by checking the URL
        # after clicking.

        # Click the download icon — should navigate to download form page
        download_icon.click()
        page.wait_for_timeout(3000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception as e:
            log.debug("Wait timed out: %s", e)

        self._screenshot(page, f"download_form_{acct.last4}")

        # ── Step 2: Verify we navigated to the download form ──
        # If the URL didn't change to the download form, Chase showed the
        # "no activity to download" tooltip and didn't navigate.
        url_after = page.url
        if "confirmdownload" not in url_after.lower():
            log.info(
                "[%s] Download icon click didn't navigate for %s — no activity (URL: %s)",
                self.institution,
                acct.last4,
                url_after[:80],
            )
            print(
                f"       ℹ [{acct.last4}] No activity to download — skipped (card may be unused)"
            )
            return None

        # ── Step 3: Click the Download button and capture the file ──
        return self._click_download_button(page, acct)

    # ── Shared Helpers ────────────────────────────────────────────────────

    def _human_jitter(self, min_sec: float = 0.8, max_sec: float = 2.5):
        """Sleep for a random interval to disguise precise robotic cadences."""
        time.sleep(random.uniform(min_sec, max_sec))

    def _navigate_to_download_form(self, page, acct: AccountConfig) -> Path | None:
        """Navigate directly to the Chase download form and download the CSV.

        Used as a fallback when _click_account can't find the account tile
        (e.g. credit cards that don't appear as individual tiles on the dashboard).

        Strategy:
          1. Navigate to the base dashboard URL first (resets SPA state)
          2. Wait for the SPA to stabilise
          3. Navigate to the download form hash fragment
          4. Select the correct account in the Account dropdown
          5. Click Download
        """
        base_url = getattr(self, "_dashboard_url", None) or self.export_url

        # Step 1: Go to base dashboard to reset SPA state
        log.info(
            "[%s] Navigating to base dashboard before download form", self.institution
        )
        page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception as e:
            log.debug("Wait timed out: %s", e)

        # Step 2: Navigate to the download form using page.goto with full URL+hash
        # Chase's SPA uses hash routing — window.location.hash assignment alone
        # doesn't trigger the router. We must use a full page.goto.
        form_url = base_url.split("#")[0] + "#/dashboard/confirmdownloadaccountactivity"
        log.info("[%s] Navigating to download form: %s", self.institution, form_url)
        page.goto(form_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception as e:
            log.debug("Wait timed out: %s", e)

        self._screenshot(page, f"download_form_direct_{acct.last4}")
        log.info("[%s] Current URL after form nav: %s", self.institution, page.url)

        # Step 3: Select the correct account in the dropdown
        # Chase uses a native <select> or a custom mds-select web component
        selected = page.evaluate(f"""() => {{
            // Try native <select> first
            const selects = document.querySelectorAll('select');
            for (const sel of selects) {{
                for (const opt of sel.options) {{
                    if (opt.text.includes('{acct.last4}') ||
                        opt.value.includes('{acct.last4}')) {{
                        sel.value = opt.value;
                        sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                        sel.dispatchEvent(new Event('input', {{bubbles: true}}));
                        return 'select:' + opt.text;
                    }}
                }}
            }}
            // Try custom dropdown options (role=option or listbox children)
            const opts = document.querySelectorAll('[role="option"]');
            for (const el of opts) {{
                const t = (el.innerText || el.textContent || '').trim();
                if (t.includes('{acct.last4}')) {{
                    el.click();
                    return 'option:' + t;
                }}
            }}
            return null;
        }}""")

        if selected:
            log.info(
                "[%s] Selected account in download form: %s", self.institution, selected
            )
            print(f"       ✔ [{acct.last4}] Account selected in form: {selected}")
            page.wait_for_timeout(1000)
        else:
            log.warning(
                "[%s] Could not select %s in download form — proceeding anyway",
                self.institution,
                acct.last4,
            )
            print(
                f"       ⚠ [{acct.last4}] Account not found in dropdown — trying download anyway"
            )

        # Step 4: Click the Download button
        return self._click_download_button(page, acct)

    def _click_download_button(self, page, acct: AccountConfig) -> Path | None:
        """Find and click the Download button on the Chase download form page,
        then capture and save the resulting CSV file."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_name = f"{acct.last4}_{ts}.csv"
        target_path = self._export_dir / target_name

        try:
            download_btn = None
            confirm_selectors = [
                'button:text-is("Download")',
                'a:text-is("Download")',
                'mds-button:text-is("Download")',
                ':text-is("Download")',
                'input[type="submit"][value="Download"]',
            ]
            for sel in confirm_selectors:
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        text = (el.inner_text() or "").strip()
                        if text == "Download":
                            download_btn = el
                            print(
                                f"       ✔ Found Download button: {sel} (text='{text}')"
                            )
                            break
                        else:
                            log.info("Skipping %s — text is '%s'", sel, text[:50])
                except Exception:
                    continue

            if not download_btn:
                download_btn_handle = page.evaluate_handle("""() => {
                    const all = document.querySelectorAll('*');
                    for (const el of all) {
                        const text = (el.innerText || el.textContent || '').trim();
                        if (text === 'Download') {
                            const rect = el.getBoundingClientRect();
                            if (rect.width > 50 && rect.height > 20 && rect.width < 400) {
                                return el;
                            }
                        }
                    }
                    return null;
                }""")
                if download_btn_handle:
                    download_btn = download_btn_handle.as_element()
                    if download_btn:
                        print("       ✔ Found Download button via JS (any element)")

            if not download_btn:
                try:
                    dl_locator = page.get_by_role("button", name="Download", exact=True)
                    if dl_locator.count() > 0:
                        download_btn = dl_locator.first
                        print("       ✔ Found Download button via get_by_role")
                except Exception as e:
                    log.debug("Ignored exception: %s", e)

            if not download_btn:
                log.warning(
                    "[%s] Download button not found for %s — skipping",
                    self.institution,
                    acct.last4,
                )
                self._screenshot(page, f"no_download_btn_{acct.last4}")
                print(f"       ✗ [{acct.last4}] Download button not found — skipped")
                return None

            with page.expect_download(timeout=15000) as dl_info:
                download_btn.click()
            download = dl_info.value
            download.save_as(str(target_path))
            print(f"       ✔ Downloaded: {target_name}")
            return target_path

        except Exception as e:
            log.warning(
                "[%s] Download failed for %s: %s", self.institution, acct.last4, e
            )
            self._screenshot(page, f"download_error_{acct.last4}")
            self._dismiss_popups(page)
            print(f"       ✗ [{acct.last4}] Download failed — skipped")
            return None

    def _wait_for_dashboard_content(self, page, timeout: int = 30):
        """Wait for the Chase SPA to render account tiles.

        Chase's dashboard is a single-page app — the URL resolves
        immediately but the account content may take several seconds to
        render via client-side JavaScript.
        """
        print("  ⏳  Waiting for dashboard to render...", end="", flush=True)
        for i in range(0, timeout, 2):
            try:
                body = page.inner_text("body").strip()
                # Look for dollar amounts or account indicators
                if (
                    re.search(r"\$[\d,]+\.\d{2}", body)
                    or any(a.last4 in body for a in self._accounts)
                    or len(body) > 500
                ):
                    print(f" ready ({i + 2}s)")
                    return
            except Exception as e:
                log.debug("Ignored exception: %s", e)
            page.wait_for_timeout(2000)
            print(".", end="", flush=True)

        print(f" timeout ({timeout}s)")
        log.warning(
            "[%s] Dashboard content did not render within %ds",
            self.institution,
            timeout,
        )

    def _dismiss_popups(self, page):
        """Dismiss common popups using selectors from the registry."""
        reg = load_selectors()
        popup_group = get_selector_group(reg, "chase.popups.dismiss")
        selectors = popup_group["selectors"] if popup_group else []

        dismissed = 0
        for sel in selectors:
            try:
                els = page.query_selector_all(sel)
                for el in els:
                    if el.is_visible():
                        el.click()
                        dismissed += 1
                        log.info("Dismissed popup: %s", sel)
                        page.wait_for_timeout(300)
            except Exception as e:
                log.debug("Popup selector %s failed: %s", sel, e)
                continue

        # Handle browser-level dialogs
        page.on("dialog", lambda dialog: dialog.dismiss())

        if dismissed == 0:
            log.debug("No popups found")

    def _try_fill_smart(
        self, page, field_name: str, value: str, selectors: list[str]
    ) -> bool:
        """Try to fill a form field — delegates to ai_backstop resilient_fill.

        This method is kept for backward compatibility. New code should
        call resilient_fill() directly with a selector group.
        """
        group = {"intent": f"Fill {field_name} (smart)", "selectors": selectors}
        return resilient_fill(page, group, value)

    def _try_fill(
        self, page, field_name: str, value: str, selectors: list[str]
    ) -> bool:
        """Try to fill a form field — delegates to resilient_fill."""
        return self._try_fill_smart(page, field_name, value, selectors)

    def _try_submit(self, page):
        """Try to click the login submit button via the registry."""
        reg = load_selectors()
        submit_group = get_selector_group(reg, "chase.login.submit")
        if submit_group and resilient_click(page, submit_group):
            print("       ✔ Login submitted")
        else:
            print("       ⚠ Could not find submit button")

    def _ensure_overview_page(self, page):
        """Navigate back to the Chase dashboard (accounts overview)."""
        self._dismiss_popups(page)

        url = page.url.lower()
        dashboard = getattr(self, "_dashboard_url", "").lower()

        # Whitelist approach: only skip navigation if we're on the
        # exact overview page. Any sub-page (account activity, download
        # form, etc.) must trigger navigation back.
        # The overview URL ends at the base hash with no sub-path:
        #   https://secure.chase.com/web/auth/dashboard#
        #   https://secure.chase.com/web/auth/dashboard#/dashboard/overview
        # Sub-pages have longer paths like:
        #   #/dashboard/overviewAccounts/creditCard/...
        #   #/dashboard/confirmdownloadaccountactivity
        #   #/dashboard/accountdetail
        def _is_overview(u: str) -> bool:
            if not u:
                return False
            # Exact match with captured dashboard URL
            if dashboard and u.split("?")[0] == dashboard.split("?")[0]:
                return True
            # URL ends at the base hash (no sub-path after #)
            if u.rstrip("/").endswith("/dashboard#") or u.rstrip("/").endswith(
                "/dashboard"
            ):
                return True
            # URL hash is exactly /dashboard/overview (no further path)
            if (
                "#/dashboard/overview" in u
                and u.split("#/dashboard/overview")[-1].strip("/") == ""
            ):
                return True
            return False

        if _is_overview(url):
            log.info("Already on dashboard overview: %s", url)
            return

        log.info("Not on overview (%s) — navigating back to dashboard", url[:80])

        # Try the nav-back button first (fastest, preserves SPA state)
        reg = load_selectors()
        nav_group = get_selector_group(reg, "chase.overview.nav_back")
        if nav_group:
            el = resilient_find(page, nav_group, timeout=3)
            if el:
                try:
                    el.click()
                    log.info("Clicked nav-back via registry")
                    page.wait_for_load_state("networkidle", timeout=10000)
                    # Verify we landed on the overview
                    if _is_overview(page.url.lower()):
                        return
                    log.warning(
                        "Nav-back click didn't reach overview — falling back to goto"
                    )
                except Exception as e:
                    log.debug("Nav-back click failed: %s", e)

        # Fallback: Navigate directly to the captured dashboard URL
        fallback = getattr(self, "_dashboard_url", None) or self.export_url
        log.info("Navigating directly to dashboard: %s", fallback)
        page.goto(fallback, wait_until="domcontentloaded", timeout=30000)
        self._wait_for_dashboard_content(page)

    def _click_account(self, page, acct: AccountConfig) -> bool:
        """Click on an account link using the selector registry.

        Chase may render account names as <a>, <button>, or custom elements.
        Template variable {last4} is expanded by ai_backstop.
        """
        # Scroll to trigger lazy-loaded tiles (credit cards load below the fold)
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(500)
        except Exception as e:
            log.debug("Ignored exception: %s", e)

        # Debug: dump all clickable elements containing the last4
        try:
            matches = page.evaluate(f"""() => {{
                const all = document.querySelectorAll('a, button, [role="link"], [role="button"], span[class*="account"], mds-link');
                const results = [];
                for (const el of all) {{
                    const t = (el.innerText || el.textContent || '').trim();
                    if (t.includes('{acct.last4}') && t.length < 200) {{
                        results.push({{tag: el.tagName, text: t.substring(0, 100), classes: el.className, id: el.id}});
                    }}
                }}
                return results;
            }}""")
            for m in matches:
                log.info(
                    "Account element match: tag=%s id=%s classes=%s text=%s",
                    m["tag"],
                    m["id"],
                    m["classes"][:50],
                    m["text"][:80],
                )
        except Exception as e:
            log.debug("Debug evaluation failed: %s", e)

        # Strategy 1: Use the centralized selector registry
        reg = load_selectors()
        acct_group = get_selector_group(reg, "chase.overview.account_link")
        template_vars = {"last4": acct.last4}

        if acct_group:
            el = resilient_find(
                page, acct_group, template_vars=template_vars, timeout=5
            )
            if el:
                try:
                    text = el.inner_text().strip()
                    if "offer" in text.lower() or "cash back" in text.lower():
                        log.debug("Skipping offer/cashback element: %s", text[:50])
                    else:
                        el.click()
                        log.info("Navigated to account %s via registry", acct.last4)
                        return True
                except Exception as e:
                    log.debug("Registry click failed for %s: %s", acct.last4, e)

        # Fallback: find any clickable element containing last4 via JavaScript,
        # but skip any inside Chase Offers. Chase credit card tiles may use
        # <button>, <mds-link>, or [role=link] rather than <a> tags.
        try:
            clicked = page.evaluate(f"""() => {{
                const selectors = 'a, button, [role="link"], [role="button"], mds-link';
                const els = document.querySelectorAll(selectors);
                for (const el of els) {{
                    const text = (el.innerText || el.textContent || '').trim();
                    if (text.includes('{acct.last4}') &&
                        !text.toLowerCase().includes('offer') &&
                        !text.toLowerCase().includes('cash back') &&
                        text.length < 120) {{
                        el.click();
                        return true;
                    }}
                }}
                return false;
            }}""")
            if clicked:
                log.info("Navigated to account %s via JS fallback", acct.last4)
                return True
        except Exception as e:
            log.debug("JS fallback failed for %s: %s", acct.last4, e)

        # Strategy 3: Credit card accounts don't appear as individual tiles
        # on the main dashboard — they're grouped under a summary section.
        # The left nav has a "Credit cards" link that navigates the SPA to
        # show individual card tiles where last4 is visible.
        if acct.type in ("credit_card", "credit"):
            log.info(
                "[%s] Clicking 'Credit cards' nav link for %s",
                self.institution,
                acct.last4,
            )
            try:
                # Click the "Credit cards" nav link in the sidebar
                nav_clicked = page.evaluate("""() => {
                    const links = document.querySelectorAll('a, button, [role="link"]');
                    for (const el of links) {
                        const text = (el.innerText || el.textContent || '').trim();
                        if (text === 'Credit cards') {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }""")
                if nav_clicked:
                    log.info(
                        "[%s] Clicked 'Credit cards' nav — waiting for tiles",
                        self.institution,
                    )
                    page.wait_for_timeout(3000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception as e:
                        log.debug("Wait timed out: %s", e)
                    # Now search for the specific card's last4
                    clicked2 = page.evaluate(f"""() => {{
                        const els = document.querySelectorAll('a, button, [role="link"]');
                        for (const el of els) {{
                            const text = (el.innerText || el.textContent || '').trim();
                            if (text.includes('{acct.last4}') &&
                                !text.toLowerCase().includes('offer') &&
                                text.length < 120) {{
                                el.click();
                                return true;
                            }}
                        }}
                        return false;
                    }}""")
                    if clicked2:
                        log.info(
                            "Navigated to credit card %s via CC nav link", acct.last4
                        )
                        return True
                    else:
                        log.warning(
                            "[%s] Credit cards nav clicked but %s tile not found",
                            self.institution,
                            acct.last4,
                        )
            except Exception as e:
                log.debug("Credit cards nav click failed: %s", e)

        return False

    def _find_latest_download(self) -> Path | None:
        """Find the most recently modified file in the export directory."""
        csvs = sorted(
            self._export_dir.glob("*.csv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if csvs:
            return csvs[0]
        others = sorted(
            self._export_dir.glob("*.*"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        return others[0] if others else None

    def _dump_page_diagnostics(self, page):
        """Dump page structure info to help debug selector issues."""
        import json

        diag = {"url": page.url}

        try:
            body = page.inner_text("body")
            diag["body_text_preview"] = body[:5000]

            # Find elements with account last4 digits
            accts = self._accounts
            for acct in accts:
                els = page.evaluate(f"""() => {{
                    return Array.from(document.querySelectorAll('*')).filter(el =>
                        el.textContent.includes('{acct.last4}') && el.children.length < 3
                    ).map(el => ({{
                        tag: el.tagName, text: el.textContent.trim().substring(0, 200),
                        html: el.outerHTML.substring(0, 400),
                        link: el.closest('a')?.href || null,
                    }})).slice(0, 5);
                }}""")
                if els:
                    diag[f"account_{acct.last4}"] = els

            # Dollar amounts
            dollars = page.evaluate("""() => {
                return Array.from(document.querySelectorAll('*')).filter(el =>
                    /\\$[\\d,]+\\.\\d{2}/.test(el.textContent) && el.children.length < 2
                ).map(el => ({
                    tag: el.tagName, text: el.textContent.trim().substring(0, 100),
                    classes: String(el.className).substring(0, 100),
                })).slice(0, 20);
            }""")
            diag["dollar_elements"] = dollars

            # All nav/account links
            links = page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a[href]')).map(a => ({
                    text: (a.innerText || '').trim().substring(0, 80),
                    href: a.href,
                })).filter(a => a.text.length > 0).slice(0, 50);
            }""")
            diag["links"] = links

        except Exception as e:
            diag["error"] = str(e)

        out = self._export_dir / "chase_page_diagnostics.json"
        out.write_text(json.dumps(diag, indent=2))
        log.info("Page diagnostics saved to %s", out)
