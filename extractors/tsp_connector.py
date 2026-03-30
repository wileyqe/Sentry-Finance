"""
extractors/tsp_connector.py — TSP Tier 2 connector with MFA bridge.

Tier 2: logs in automatically but pauses at MFA and routes the code
request through the dashboard SSE stream + API endpoint. Session reuse
via persistent browser profile minimizes MFA frequency.

Account: TSP Uniformed Services (7777)
Institution ID: tsp

Login flow (observed 2026-03):
  - https://www.tsp.gov/login/ hosts an Okta Sign-In Widget
  - Username: #okta-signin-username
  - Password: #okta-signin-password
  - Submit:   #okta-signin-submit
  - MFA:      Okta TOTP via input[name="answer"] or input[name="passcode"]
  - Post-login lands on the account summary/overview page
"""

import logging
import re
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from skills.institution_connector import InstitutionConnector, AccountConfig
from backend.events import broadcast_event
from backend.mfa_bridge import wait_for_code

log = logging.getLogger("sentry.extractors.tsp")

TSP_LOGIN_URL = "https://www.tsp.gov/login/"
TSP_OVERVIEW_URL = "https://www.tsp.gov/account/"


class TSPConnector(InstitutionConnector):

    @property
    def institution(self) -> str:
        return "tsp"

    @property
    def display_name(self) -> str:
        return "Thrift Savings Plan"

    @property
    def export_url(self) -> str:
        return TSP_OVERVIEW_URL

    @property
    def login_url(self) -> str:
        return TSP_LOGIN_URL

    # ── Session Detection ────────────────────────────────────────────────

    def _is_post_login(self, page: Page) -> bool:
        """TSP-specific post-login detection."""
        url = page.url.lower()
        # TSP shows account overview / summary after login
        if any(kw in url for kw in ("account", "summary", "overview", "balance")):
            # Verify it's not the login page itself
            if "login" not in url and "signin" not in url:
                return True
        # Fall back to base detection
        return super()._is_post_login(page)

    # ── Login ────────────────────────────────────────────────────────────

    def _perform_login(self, page: Page, credentials: dict | None = None) -> bool:
        """Navigate to TSP login (Okta widget) and fill credentials."""
        log.info("[tsp] Navigating to login URL: %s", self.login_url)
        page.goto(self.login_url, wait_until="domcontentloaded", timeout=30000)

        # Wait for the Okta widget to render
        try:
            page.wait_for_selector(
                "#okta-signin-username", state="visible", timeout=15000
            )
        except PlaywrightTimeout:
            log.warning("[tsp] Okta username field not visible after 15s")
            return False

        if not credentials or "username" not in credentials or "password" not in credentials:
            log.info("[tsp] No credentials provided — waiting for Password Manager autofill")
            # Wait briefly for autofill, then click submit
            page.wait_for_timeout(3000)
            try:
                page.click("#okta-signin-submit", timeout=5000)
            except PlaywrightTimeout:
                log.warning("[tsp] Could not click submit button")
            return True

        # Fill credentials from Credential Broker
        log.info("[tsp] Filling credentials from broker")
        page.fill("#okta-signin-username", credentials["username"])
        page.fill("#okta-signin-password", credentials["password"])
        page.wait_for_timeout(500)
        page.click("#okta-signin-submit")

        return True

    # ── MFA Bridge ───────────────────────────────────────────────────────

    def _wait_for_mfa(self, page: Page, timeout_seconds: int = 300) -> bool:
        """Override base MFA wait to route through SSE bridge instead of terminal."""
        # Check if we're already past MFA
        if self._is_post_login(page):
            return True

        # Wait a moment for the page to settle after login submission
        page.wait_for_timeout(3000)

        # Re-check after settling
        if self._is_post_login(page):
            return True

        # Detect whether we're on an MFA screen
        # Okta TOTP uses input[name="answer"] or input[name="passcode"]
        mfa_selectors = [
            'input[name="answer"]',
            'input[name="passcode"]',
            'input[name="credentials.passcode"]',
            'input[autocomplete="one-time-code"]',
            'input[name="verificationCode"]',
        ]
        mfa_sel = ", ".join(mfa_selectors)

        try:
            page.wait_for_selector(mfa_sel, timeout=10000)
        except PlaywrightTimeout:
            # Not on an MFA screen — might already be past it
            if self._is_post_login(page):
                return True
            log.warning("[tsp] Expected MFA screen but didn't find it; proceeding")
            # Fall back to base polling for manual completion
            return super()._wait_for_mfa(page, timeout_seconds=timeout_seconds)

        # Signal the dashboard that we need a code
        broadcast_event("mfa_required", {
            "institution": "tsp",
            "prompt": "Enter your TSP authenticator app code to continue.",
        })
        log.info("[tsp] MFA bridge activated — waiting for code from dashboard")

        print()
        print("  ┌─────────────────────────────────────────────────┐")
        print("  │  [TSP] MFA code requested via dashboard.        │")
        print("  │  Enter your authenticator code in the UI.       │")
        print("  └─────────────────────────────────────────────────┘")
        print()

        # Block until the user submits a code via /api/mfa/submit
        code = wait_for_code("tsp", timeout_seconds=timeout_seconds)
        if code is None:
            log.error("[tsp] MFA bridge timed out — no code received")
            return False

        # Fill the code and submit
        mfa_input = page.query_selector(mfa_sel)
        if mfa_input:
            mfa_input.fill(code)
        else:
            log.error("[tsp] MFA input field disappeared after receiving code")
            return False

        # Look for submit button — Okta uses .button-primary or button[type=submit]
        submit_selectors = [
            'input[type="submit"]',
            'button[type="submit"]',
            ".button-primary",
            'button:has-text("Verify")',
            'button:has-text("Submit")',
            'button:has-text("Log in")',
        ]
        for sel in submit_selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    break
            except Exception:
                continue
        else:
            # Fallback: press Enter
            if mfa_input:
                mfa_input.press("Enter")

        # Wait for MFA to process
        try:
            page.wait_for_timeout(3000)
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except PlaywrightTimeout:
            pass

        return self._is_post_login(page)

    # ── Export ────────────────────────────────────────────────────────────

    def _trigger_export(self, page: Page, accounts: list[AccountConfig]) -> list[Path]:
        """Scrape TSP account overview for total balance and per-fund breakdown."""
        # Navigate to account overview if not already there
        current_url = page.url.lower()
        if "account" not in current_url or "login" in current_url:
            log.info("[tsp] Navigating to account overview: %s", self.export_url)
            page.goto(self.export_url, wait_until="domcontentloaded", timeout=30000)

        # Wait for the overview page content to load
        page.wait_for_timeout(3000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeout:
            log.debug("[tsp] networkidle timeout — continuing anyway")

        total_balance = self._scrape_total_balance(page)
        fund_positions = self._scrape_fund_positions(page)

        if total_balance is None or total_balance <= 0:
            log.error("[tsp] Could not read total balance — aborting")
            return []

        # Populate self._result_balances for the standard pipeline
        # (automation_worker / result_writer handles persistence)
        self._result_balances["7777"] = {
            "name": "TSP Uniformed Services",
            "balance": f"${total_balance:,.2f}",
            "type": "retirement",
        }

        log.info("[tsp] Scraped TSP balance: $%.2f", total_balance)
        for fund, data in fund_positions.items():
            log.info("[tsp]   %s: $%.2f", fund, data.get("balance", 0))

        return []  # No files downloaded; data goes through _result_balances

    def _scrape_total_balance(self, page: Page) -> float | None:
        """Extract total account value from the TSP overview page.

        Uses multiple strategies to find the balance on the page.
        """
        strategies = [
            # Strategy 1: Find the largest dollar amount on the page
            # TSP overview prominently displays the total account balance
            lambda: page.evaluate("""
                (() => {
                    const els = document.querySelectorAll('h1,h2,h3,h4,p,span,div,td,strong');
                    let maxVal = 0;
                    let maxText = null;
                    for (const el of els) {
                        const t = (el.innerText || '').trim();
                        const match = t.match(/^\\$([\\d,]+\\.\\d{2})$/);
                        if (match) {
                            const v = parseFloat(match[1].replace(/,/g, ''));
                            if (v > maxVal && v > 1000) {
                                maxVal = v;
                                maxText = t;
                            }
                        }
                    }
                    return maxText;
                })()
            """),
            # Strategy 2: Look for text near "Account Balance" or "Total"
            lambda: page.evaluate("""
                (() => {
                    const body = document.body.innerText || '';
                    const lines = body.split('\\n').map(l => l.trim()).filter(Boolean);
                    for (let i = 0; i < lines.length; i++) {
                        if (/total.*balance|account.*balance|total.*value/i.test(lines[i])) {
                            for (let j = i; j <= Math.min(i + 3, lines.length - 1); j++) {
                                const m = lines[j].match(/\\$([\\d,]+\\.\\d{2})/);
                                if (m) return m[0];
                            }
                        }
                    }
                    return null;
                })()
            """),
        ]

        for strategy in strategies:
            try:
                raw = strategy()
                if raw:
                    return self._parse_dollar(raw)
            except Exception as e:
                log.debug("[tsp] Balance scrape strategy failed: %s", e)
                continue

        log.warning("[tsp] Could not scrape total balance from any strategy")
        return None

    def _scrape_fund_positions(self, page: Page) -> dict[str, dict]:
        """Extract per-fund balances from the TSP overview page.

        Returns: {"L 2065": {"balance": 36901.55}, "C Fund": {"balance": 83146.22}, ...}
        """
        positions = {}
        try:
            # TSP overview shows fund breakdown in a table or card layout
            # Extract fund names and their associated dollar values
            fund_data = page.evaluate("""
                (() => {
                    const result = {};
                    const fundPatterns = [
                        /^(L\\s+\\d{4})$/i,
                        /^(L\\s+Income)$/i,
                        /^([GCFSI]\\s+Fund)$/i,
                    ];
                    const allEls = document.querySelectorAll('td, th, span, div, p, strong, a');
                    const candidates = [];
                    for (const el of allEls) {
                        const t = (el.innerText || '').trim();
                        if (t.length > 0 && t.length < 30) {
                            candidates.push({text: t, el: el});
                        }
                    }
                    for (let i = 0; i < candidates.length; i++) {
                        const text = candidates[i].text;
                        let isFund = false;
                        for (const pat of fundPatterns) {
                            if (pat.test(text)) { isFund = true; break; }
                        }
                        if (!isFund) continue;
                        // Look for a dollar amount nearby (next few elements)
                        for (let j = i + 1; j <= Math.min(i + 5, candidates.length - 1); j++) {
                            const valMatch = candidates[j].text.match(/^\\$([\\d,]+\\.\\d{2})$/);
                            if (valMatch) {
                                const val = parseFloat(valMatch[1].replace(/,/g, ''));
                                if (val > 0) {
                                    result[text] = val;
                                    break;
                                }
                            }
                        }
                    }
                    return result;
                })()
            """)

            if fund_data:
                for fund_name, balance in fund_data.items():
                    positions[fund_name] = {"balance": balance}

        except Exception as e:
            log.warning("[tsp] Fund position scrape failed: %s", e)

        return positions

    # ── Logout ───────────────────────────────────────────────────────────

    def _perform_logout(self, page: Page) -> None:
        """Log out of TSP after export."""
        log.info("[tsp] Logging out...")
        try:
            # Look for a Sign Out / Log Out link
            signout_selectors = [
                'a:has-text("Log Out")',
                'button:has-text("Log Out")',
                'a:has-text("Sign Out")',
                'button:has-text("Sign Out")',
                '[data-testid="signout"]',
                'a[href*="logout"]',
            ]
            for sel in signout_selectors:
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        page.wait_for_timeout(2000)
                        print("  🔓  Logged out of TSP")
                        log.info("[tsp] Logout complete")
                        return
                except Exception:
                    continue

            # Fallback: navigate directly to a logout URL
            log.info("[tsp] Sign Out link not found, trying direct logout URL")
            page.goto(
                "https://www.tsp.gov/logout/",
                wait_until="domcontentloaded",
                timeout=15000,
            )
            page.wait_for_timeout(2000)
            print("  🔓  Logged out of TSP")

        except Exception as e:
            raise RuntimeError(f"TSP logout failed: {e}") from e

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_dollar(text: str) -> float:
        """Parse a dollar string like '$36,901.55' to float."""
        cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
