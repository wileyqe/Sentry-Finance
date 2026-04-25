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


class ChaseLoginMixin:
    """Mixin extracted from ChaseConnector: _login_mixin methods."""

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
        self._screenshot(page, "login_page", error_only=True)
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
                            const otpEl = document.querySelector('input[id*="password_input_abc"], input[id="password_input-input-field"], input[name*="otp"], input[type="number"]');
                            const hasOtp = otpEl && otpEl.offsetParent !== null;
                            return url.includes("dashboard") || hasPassword || hasOtp;
                        }""",
                        timeout=15000,
                    )
                except Exception as e:
                    log.debug("Wait for post-login state timed out: %s", e)

                self._screenshot(page, "after_submit", error_only=True)
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
            self._screenshot(page, "after_submit", error_only=True)
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
                            el.click(force=True, timeout=3000)
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

    def _wait_for_mfa(self, page, timeout_seconds: int = 300) -> bool:
        """Auto-detect login/MFA completion for Chase.

        Override the base class because Chase uses '/auth/' in its
        dashboard URL which would confuse the generic keyword check.
        We specifically look for the secure dashboard instead.

        Returns:
            True if MFA completed successfully, False if timed out.
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
                    return True
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
                    self._screenshot(page, "after_mfa", error_only=True)
                    return True

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
                        self._screenshot(page, "after_mfa", error_only=True)
                        return True

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
                                self._screenshot(page, "after_mfa", error_only=True)
                                return True
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
        return False

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
