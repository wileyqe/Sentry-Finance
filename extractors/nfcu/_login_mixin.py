"""
extractors/nfcu_connector.py — Navy Federal Credit Union connector.

Concrete InstitutionConnector subclass implementing the NFCU-specific
login flow, balance scraping, transaction CSV download, and loan detail
extraction.

Uses the user's actual Chrome instance via CDP. Google Password Manager
handles credential autofill; the script only clicks submit and waits
for MFA. No plaintext credentials are handled in code.

Usage:
    from extractors.nfcu_connector import NFCUConnector

    connector = NFCUConnector(headless=False)
    result = connector.run(force=True)
    print(result)
"""

import re
import time
import random
import logging
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page

from skills.institution_connector import InstitutionConnector, AccountConfig
from extractors.ai_backstop import (
    resilient_find,
    resilient_click,
    load_selectors,
    get_selector_group,
    reset_ai_counter,
)

log = logging.getLogger("sentry.extractors.nfcu")


class NFCULoginMixin:
    """Mixin extracted from NFCUConnector: _login_mixin methods."""

    def _perform_login(self, page, credentials: dict | None = None) -> bool:
        """Navigate to NFCU login and authenticate.

        Two credential paths:
          A) Broker credentials (credentials dict provided):
             Fill username/password fields directly, then submit.
          B) Password Manager autofill (credentials=None):
             Wait for Google Password Manager to autofill, then submit.

        In both cases, MFA is handled by the lifecycle's _wait_for_mfa.
        """
        reset_ai_counter()  # Reset per-run AI call budget
        reg = load_selectors()

        print("  🌐  Navigating to NFCU login page...")
        page.goto(self.login_url, wait_until="domcontentloaded", timeout=30000)

        # Wait for Angular SPA to render the login form
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception as e:
            log.debug("Wait timed out: %s", e)
        self._human_jitter(1.0, 2.0)

        # Wait for the actual login form to appear
        login_group = get_selector_group(reg, "nfcu.login.username")
        if login_group:
            first_sel = login_group["selectors"][0]
            try:
                page.wait_for_selector(first_sel, timeout=15000, state="visible")
            except Exception as e:
                log.debug("Login form selector wait timed out: %s", e)

        # Dismiss popups (cookie banners, notification prompts, etc.)
        self._dismiss_popups(page)
        self._screenshot(page, "login_ready", error_only=True)

        # ── Path A: Broker credentials ─────────────────────────────
        if credentials and credentials.get("username") and credentials.get("password"):
            print("  🔑  Filling credentials from broker...")
            filled = self._fill_credentials(page, reg, credentials)
            if not filled:
                log.warning(
                    "[%s] Broker credential fill failed, falling back to autofill",
                    self.institution,
                )
                # Fall through to Path B
            else:
                # Submit
                submit_group = get_selector_group(reg, "nfcu.login.submit")
                if submit_group:
                    resilient_click(page, submit_group)
                    print("  ✔  Login submitted (broker)")
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception as e:
                    log.debug("Wait timed out: %s", e)
                self._screenshot(page, "after_submit", error_only=True)
                return True  # MFA handled by lifecycle

        # ── Path B: Password Manager autofill ──────────────────────
        print("  ⏳  Waiting for Password Manager autofill...")
        autofill_ok = self._wait_for_autofill(page, reg)

        if autofill_ok:
            # Click the submit button
            submit_group = get_selector_group(reg, "nfcu.login.submit")
            if submit_group:
                resilient_click(page, submit_group)
                print("  ✔  Login submitted (autofill)")
            # Wait for navigation after submit
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception as e:
                log.debug("Wait timed out: %s", e)
            self._screenshot(page, "after_submit", error_only=True)
        else:
            self._screenshot(page, "autofill_not_detected")
            log.error(
                "[%s] Password Manager autofill not detected after "
                "%ds. Ensure Chrome Sync is enabled in the "
                "automation profile (C:\\ChromeAutomationProfile) "
                "and NFCU credentials are saved in Google "
                "Password Manager.",
                self.institution,
                30,
            )
            print("  ❌  Password Manager autofill failed.")
            print("      To fix: open the automation profile Chrome,")
            print("      sign into Google, enable Sync (passwords).")
            return False

        return True  # MFA handled by lifecycle's _wait_for_mfa

    def _fill_credentials(self, page, reg: dict, credentials: dict) -> bool:
        """Fill username and password fields from broker-provided credentials.

        Uses the same selector registry as autofill detection.
        Returns True if both fields were filled successfully.
        """
        try:
            # Fill username
            user_group = get_selector_group(reg, "nfcu.login.username")
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
            pw_group = get_selector_group(reg, "nfcu.login.password")
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
        """Trigger Password Manager autofill and verify fields are filled.

        Chrome Password Manager shows a dropdown when the user clicks the
        username field. We simulate this by:
          1. Clicking the username field to focus it
          2. Waiting for the autofill dropdown to appear
          3. Pressing ArrowDown + Enter to select the first suggestion
          4. Verifying both username and password fields have values

        Uses direct Playwright selectors (not resilient_find) to avoid
        triggering the AI backstop for simple form interactions.
        """
        # Direct selectors for the login form — no AI needed
        username_selectors = [
            'input[name="username"]',
            "input#username",
            'input[autocomplete="username"]',
            'input[type="text"]',
        ]
        password_selectors = [
            'input[type="password"]',
            "input#password",
            'input[name="password"]',
        ]

        # Find the username field
        u_el = None
        for sel in username_selectors:
            u_el = page.query_selector(sel)
            if u_el:
                log.debug("Username field found with: %s", sel)
                break
        if not u_el:
            log.warning("Username field not found with any selector")
            return False

        # Try up to 3 times to trigger autofill
        cdp_session = None
        try:
            cdp_session = page.context.new_cdp_session(page)
        except Exception as e:
            log.debug("Could not create CDP session: %s", e)

        for attempt in range(3):
            log.info("Password Manager trigger attempt %d/3", attempt + 1)

            # ── Strategy A: CDP-level trusted mouse click ────────
            # Chrome's Password Manager only responds to "trusted"
            # input events. Send a real mouse click via CDP.
            u_el.focus()  # Ensure element is focused first
            bbox = u_el.bounding_box()
            if bbox and cdp_session:
                cx = bbox["x"] + bbox["width"] / 2
                cy = bbox["y"] + bbox["height"] / 2
                try:
                    print(f"  🖱️  Sending CDP trusted click to ({cx:.0f}, {cy:.0f})...")

                    # 1. Move mouse to target
                    cdp_session.send(
                        "Input.dispatchMouseEvent",
                        {
                            "type": "mouseMoved",
                            "x": cx,
                            "y": cy,
                        },
                    )
                    page.wait_for_timeout(100)

                    # 2. Press
                    cdp_session.send(
                        "Input.dispatchMouseEvent",
                        {
                            "type": "mousePressed",
                            "x": cx,
                            "y": cy,
                            "button": "left",
                            "clickCount": 1,
                        },
                    )
                    page.wait_for_timeout(100)  # Simulate human click duration

                    # 3. Release
                    cdp_session.send(
                        "Input.dispatchMouseEvent",
                        {
                            "type": "mouseReleased",
                            "x": cx,
                            "y": cy,
                            "button": "left",
                            "clickCount": 1,
                        },
                    )
                    log.debug(
                        "CDP mouse click sequence complete at (%.0f, %.0f)", cx, cy
                    )
                except Exception as e:
                    log.debug("CDP mouse click failed: %s, using Playwright click", e)
                    page.mouse.click(cx, cy)
            else:
                page.mouse.click(
                    *(
                        (bbox["x"] + bbox["width"] / 2, bbox["y"] + bbox["height"] / 2)
                        if bbox
                        else (100, 200)
                    )
                )

            page.wait_for_timeout(2000)  # Wait for dropdown to render

            # Take a screenshot to see the dropdown state
            if attempt == 0:
                self._screenshot(page, "autofill_dropdown", error_only=True)

            # Press ArrowDown then Enter to select the suggestion
            page.keyboard.press("ArrowDown")
            page.wait_for_timeout(500)
            page.keyboard.press("Enter")
            page.wait_for_timeout(1500)

            # Verify both fields have values
            try:
                u_val = u_el.input_value()
                p_el = None
                for sel in password_selectors:
                    p_el = page.query_selector(sel)
                    if p_el:
                        break
                p_val = p_el.input_value() if p_el else ""

                if u_val and p_val:
                    log.info(
                        "Password Manager autofill success (user: %s...)", u_val[:3]
                    )
                    print(f"  ✔  Password Manager filled credentials")
                    return True
                else:
                    log.debug(
                        "Attempt %d: user=%s, pass=%s",
                        attempt + 1,
                        "filled" if u_val else "empty",
                        "filled" if p_val else "empty",
                    )
            except Exception as e:
                log.debug("Autofill check failed: %s", e)

            # Wait before retrying
            page.wait_for_timeout(2000)

        self._screenshot(page, "autofill_failed")

        # ── Fallback: Graceful Manual Intervention ───────────
        # If automated triggering failed, don't crash. Ask the user.
        print()
        print(f"  ⚠  Autofill trigger failed. Please click the username")
        print(f"      field in the browser and select your account manually.")
        print(f"      The script is waiting for you...")

        # Wait up to 60s for user to help
        for i in range(30):
            page.wait_for_timeout(2000)
            try:
                u_val = u_el.input_value()
                p_el = None
                for sel in password_selectors:
                    p_el = page.query_selector(sel)
                    if p_el:
                        break
                p_val = p_el.input_value() if p_el else ""

                if u_val and p_val:
                    log.info("Manual autofill detected")
                    print(f"  ✔  Credentials detected, proceeding...")
                    return True
            except Exception as e:
                log.debug("Ignored exception: %s", e)

        return False

    def _perform_logout(self, page) -> None:
        """Log out of NFCU after export.

        Strategy:
          1. Click the profile/user menu icon to reveal Sign Out
          2. Click "Sign Out"
          3. Fallback: navigate to the sign-out URL
        """
        log.info("[%s] Logging out...", self.institution)

        try:
            # Strategy 1: Click the Sign Out link/button in the UI
            signout_selectors = [
                'a:has-text("Sign Out")',
                'button:has-text("Sign Out")',
                'a:has-text("Log Out")',
                'button:has-text("Log Out")',
                '[data-testid="signout"]',
            ]

            # First try to find it directly (may be in a dropdown).
            # Narrow the catch-all Exception — earlier it swallowed
            # KeyboardInterrupt / SystemExit too. Playwright's
            # query_selector + click can raise TimeoutError when the
            # element disappears mid-search and AttributeError if the
            # element handle is already detached; both are recoverable
            # "try the next selector" cases.
            found = False
            for sel in signout_selectors:
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        found = True
                        break
                except (AttributeError, TimeoutError):
                    continue

            if not found:
                # Try clicking the profile/user icon first to open the menu
                profile_selectors = [
                    '[aria-label="Profile"]',
                    '[aria-label="User menu"]',
                    'button:has-text("Profile")',
                    '[data-testid="profile-menu"]',
                    'nf-icon[icon="user"]',
                    'button[class*="user"], button[class*="profile"]',
                ]
                for sel in profile_selectors:
                    try:
                        el = page.query_selector(sel)
                        if el and el.is_visible():
                            el.click()
                            page.wait_for_timeout(1000)
                            break
                    except Exception:
                        continue

                # Now try to find Sign Out again
                for sel in signout_selectors:
                    try:
                        el = page.query_selector(sel)
                        if el and el.is_visible():
                            el.click()
                            found = True
                            break
                    except Exception:
                        continue

            if not found:
                # Strategy 2: Navigate directly to the sign-out URL
                log.info(
                    "[%s] Sign Out button not found, navigating to sign-out URL",
                    self.institution,
                )
                page.goto(
                    "https://digitalomni.navyfederal.org/signin/signout/",
                    wait_until="domcontentloaded",
                    timeout=15000,
                )

            page.wait_for_timeout(2000)
            print("  🔓  Logged out of NFCU")
            log.info("[%s] Logout complete", self.institution)

        except Exception as e:
            raise RuntimeError(f"NFCU logout failed: {e}") from e
