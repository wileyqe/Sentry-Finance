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
from datetime import date, datetime
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from skills.institution_connector import InstitutionConnector, AccountConfig
from backend.events import broadcast_event
from backend.mfa_bridge import wait_for_code
from dal.accounts_config import get_account_id
from dal.investments_writes import (
    record_investment_holdings,
    record_portfolio_snapshot,
)
from dal.parsers.tsp_statement import _fund_to_ticker
from extractors.sms_otp import wait_for_otp

log = logging.getLogger("sentry.extractors.tsp")


def _tsp_account_id() -> str:
    """Return TSP retirement account_id from accounts.yaml; fallback template."""
    return get_account_id("tsp", account_type="retirement") or "tsp_XXXX"

TSP_LOGIN_URL = "https://www.tsp.gov/login/"
# TSP migrated to an Angular SPA at api.rk.tsp.gov (the old tsp.gov/account/
# returns 404).  The homepage shows total balance; the investments page shows
# per-fund breakdown with units, NAV, and market value.
TSP_HOMEPAGE_URL = (
    "https://api.rk.tsp.gov/api/angularfirst-app/"
    "ah-angular-afirst-web/#/web/converge/homepage"
)
TSP_OVERVIEW_URL = TSP_HOMEPAGE_URL  # alias for base class


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
        # TSP redirects to api.rk.tsp.gov after login
        if "converge/homepage" in url or "converge/dc" in url:
            return True
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
        """SMS-first MFA with TOTP/bridge fallback.

        Flow:
          1. Check if already past MFA (session reuse)
          2. Detect MFA screen: method selection or direct code input
          3. If SMS option available → auto-capture via Phone Link
          4. If SMS fails or unavailable → fall back to MFA bridge (dashboard)
        """
        if self._is_post_login(page):
            return True

        page.wait_for_timeout(3000)
        if self._is_post_login(page):
            return True

        # ── Detect MFA screen ────────────────────────────────────────
        code_selectors = [
            'input[name="answer"]',
            'input[name="passcode"]',
            'input[name="credentials.passcode"]',
            'input[autocomplete="one-time-code"]',
            'input[name="verificationCode"]',
        ]
        code_sel = ", ".join(code_selectors)

        # TSP Okta goes directly to SMS — no factor selection page.
        # If a factor chooser appears (e.g. account config changes),
        # try clicking the SMS option first.
        sms_option_selectors = [
            'a[data-se="sms"]',
            '[data-type="phone"]',
            'a:has-text("SMS")',
            'a:has-text("Text")',
            '.factor-row:has-text("SMS")',
            '.factor-row:has-text("Phone")',
        ]
        for sel in sms_option_selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    log.info("[tsp] Factor chooser detected — clicking SMS: %s", sel)
                    el.click()
                    page.wait_for_timeout(2000)
                    break
            except Exception:
                continue

        # Check for the SMS form container (validated: data-se="factor-sms")
        sms_form = page.query_selector('form[data-se="factor-sms"]')
        is_sms = sms_form is not None

        # Wait for code input field
        try:
            page.wait_for_selector(code_sel, timeout=10000)
        except PlaywrightTimeout:
            if self._is_post_login(page):
                return True
            log.warning("[tsp] MFA code input not found; falling back to base")
            return super()._wait_for_mfa(page, timeout_seconds=timeout_seconds)

        # ── SMS auto-capture path ────────────────────────────────────
        # TSP SMS body: "Your tsp.gov multi-factor authentication code is XXXXXX"
        code = None
        if is_sms:
            log.info("[tsp] SMS MFA detected — auto-capture via Phone Link")
            broadcast_event("mfa_required", {
                "institution": "tsp",
                "prompt": "TSP SMS code sent — auto-capture in progress.",
            })
            code = wait_for_otp(timeout=90, hint="tsp.gov")
            if code:
                log.info("[tsp] SMS OTP captured automatically")

        # ── Fallback: MFA bridge (dashboard manual entry) ────────────
        if code is None:
            broadcast_event("mfa_required", {
                "institution": "tsp",
                "prompt": "Enter your TSP verification code to continue.",
            })
            log.info("[tsp] MFA bridge activated — waiting for code from dashboard")

            print()
            print("  ┌─────────────────────────────────────────────────┐")
            print("  │  [TSP] MFA code required.                       │")
            print("  │  Enter your code in the dashboard.              │")
            print("  └─────────────────────────────────────────────────┘")
            print()

            code = wait_for_code("tsp", timeout_seconds=timeout_seconds)
            if code is None:
                log.error("[tsp] MFA bridge timed out — no code received")
                return False

        # ── Fill and submit ──────────────────────────────────────────
        mfa_input = page.query_selector(code_sel)
        if mfa_input:
            mfa_input.fill(code)
        else:
            log.error("[tsp] MFA input field disappeared after receiving code")
            return False

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
            if mfa_input:
                mfa_input.press("Enter")

        try:
            page.wait_for_timeout(3000)
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except PlaywrightTimeout:
            pass

        return self._is_post_login(page)

    # ── Export ────────────────────────────────────────────────────────────

    def _trigger_export(self, page: Page, accounts: list[AccountConfig]) -> list[Path]:
        """Scrape TSP account data from the api.rk.tsp.gov Angular SPA.

        Flow:
          1. Ensure we're on the TSP homepage (post-login redirect lands here)
          2. Click "Investment details" to reach the per-fund breakdown
          3. Parse total balance, per-fund units, NAV, and market value
          4. Persist holdings and fetch current prices
        """
        # Ensure we're on the TSP SPA (not the old tsp.gov/account/ which is dead)
        current_url = page.url.lower()
        if "converge" not in current_url:
            log.info("[tsp] Navigating to TSP homepage: %s", TSP_HOMEPAGE_URL)
            page.goto(TSP_HOMEPAGE_URL, wait_until="domcontentloaded", timeout=30000)

        page.wait_for_timeout(3000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeout:
            log.debug("[tsp] networkidle timeout — continuing anyway")

        # Navigate to investments detail page
        if "investments" not in page.url.lower():
            clicked = page.evaluate("""
                (() => {
                    const els = document.querySelectorAll('a, button, span');
                    for (const el of els) {
                        if ((el.innerText || '').trim() === 'Investment details') {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                })()
            """)
            if clicked:
                log.info("[tsp] Clicked 'Investment details'")
                page.wait_for_timeout(5000)
            else:
                log.warning("[tsp] Could not find 'Investment details' link")

        # Parse the page text for fund data
        total_balance, fund_positions = self._parse_investments_page(page)

        if total_balance is None or total_balance <= 0:
            log.error("[tsp] Could not read total balance — aborting")
            return []

        self._result_balances["7777"] = {
            "name": "TSP Uniformed Services",
            "balance": f"${total_balance:,.2f}",
            "type": "retirement",
        }

        log.info("[tsp] Scraped TSP balance: $%.2f", total_balance)
        for fund, data in fund_positions.items():
            log.info(
                "[tsp]   %s: $%.2f  units=%.6f  nav=$%.4f",
                fund,
                data.get("balance", 0),
                data.get("units", 0),
                data.get("nav", 0),
            )

        self._persist_scraped_holdings(fund_positions, total_balance)

        return []

    def _parse_investments_page(self, page: Page) -> tuple[float | None, dict]:
        """Parse the TSP investments page for total balance and per-fund data.

        The api.rk.tsp.gov Angular SPA renders fund cards in a consistent
        text pattern (validated 2026-04):

            [Fund Name](PDF)
            $[Balance]
            Gain/Loss
            $[amount]
            ...
            Units
            [count]
            Fund Return
            [%]
            Fund Price
            $[price]

        Returns (total_balance, fund_positions) where fund_positions maps
        fund names to {"balance": float, "units": float, "nav": float}.
        """
        body = page.evaluate("document.body.innerText")
        lines = [l.strip() for l in body.split("\n") if l.strip()]

        total_balance = None
        fund_positions = {}

        # Fund name patterns
        fund_pattern = re.compile(
            r"^(L\s+\d{4}|L\s+Income|[GCFSI]\s+Fund)", re.IGNORECASE
        )

        for i, line in enumerate(lines):
            # Total balance: largest dollar amount, or the one labeled with "$xxx,xxx.xx"
            # that appears near "Balance as of" or "Your Current Mix"
            if total_balance is None:
                dollar = re.match(r"^\$([\d,]+\.\d{2})$", line)
                if dollar:
                    val = self._parse_dollar(line)
                    if val and val > 10000:
                        total_balance = val

            # Fund name detection (strips the "(PDF)" suffix)
            m = fund_pattern.match(line)
            if not m:
                continue
            fund_name = m.group(1).strip()

            # Scan forward for balance, units, and NAV
            balance = 0.0
            units = 0.0
            nav = 0.0
            for j in range(i + 1, min(i + 20, len(lines))):
                fwd = lines[j]
                # Balance: first dollar amount after fund name
                if balance == 0.0:
                    dm = re.match(r"^-?\$([\d,]+\.\d{2})$", fwd)
                    if dm:
                        balance = self._parse_dollar(fwd)
                        continue
                # Units
                if fwd == "Units" and j + 1 < len(lines):
                    um = re.match(r"^([\d,]+\.\d+)$", lines[j + 1])
                    if um:
                        units = float(um.group(1).replace(",", ""))
                # Fund Price (NAV)
                if fwd == "Fund Price" and j + 1 < len(lines):
                    pm = re.match(r"^\$([\d.]+)$", lines[j + 1])
                    if pm:
                        nav = float(pm.group(1))
                    break  # Fund Price is the last field per fund

            if balance > 0:
                fund_positions[fund_name] = {
                    "balance": balance,
                    "units": units,
                    "nav": nav,
                }

        return total_balance, fund_positions

    # ── Logout ───────────────────────────────────────────────────────────

    def _perform_logout(self, page: Page) -> None:
        """Log out of TSP after export.

        The api.rk.tsp.gov SPA hides the "Log out" link inside a profile
        menu (aria-label="Profile Menu").  Strategy:
          1. Open the profile menu to reveal the logout link
          2. Click the logout link
          3. Fallback: navigate directly to the logout URL
        """
        log.info("[tsp] Logging out...")
        try:
            # Try opening the profile menu first (reveals hidden logout link)
            profile_btn = page.query_selector('[aria-label="Profile Menu"]')
            if profile_btn:
                profile_btn.click()
                page.wait_for_timeout(1000)

            # Now look for the visible logout link
            signout_selectors = [
                'a:has-text("Log out")',
                'a:has-text("Log Out")',
                'a:has-text("Sign Out")',
                'a[href*="logout"]',
                'button:has-text("Log Out")',
            ]
            for sel in signout_selectors:
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        page.wait_for_timeout(3000)
                        log.info("[tsp] Logout complete")
                        return
                except Exception:
                    continue

            # Fallback: navigate directly to the logout URL
            log.info("[tsp] Logout link not visible, using direct URL")
            page.goto(
                "https://api.rk.tsp.gov/c/portal/logout",
                wait_until="domcontentloaded",
                timeout=15000,
            )
            page.wait_for_timeout(2000)
            log.info("[tsp] Logout complete (direct URL)")

        except Exception as e:
            raise RuntimeError(f"TSP logout failed: {e}") from e

    # ── Holdings Persistence ───────────────────────────────────────────

    def _persist_scraped_holdings(
        self, fund_positions: dict[str, dict], total_balance: float
    ) -> None:
        """Write scraped per-fund data to investment_holdings and fetch prices.

        After each connector scrape:
        1. Write per-fund holdings rows for today (infer NAV from last known units)
        2. Fetch current prices from MaxTSP API and cache in benchmark_prices
        3. Interpolate any missing days since the last holdings entry
        """
        try:
            from dal.database import get_db
            from dal.tsp_prices import (
                fetch_current_prices,
                interpolate_daily_holdings,
                upsert_benchmark_prices,
            )

            today = date.today().isoformat()

            tsp_id = _tsp_account_id()
            with get_db() as conn:
                # Read last known units from most recent investment_holdings
                anchor_date = conn.execute(
                    "SELECT MAX(date) FROM investment_holdings WHERE account_id = ?",
                    (tsp_id,),
                ).fetchone()[0]

                known_units = {}
                if anchor_date:
                    rows = conn.execute(
                        "SELECT ticker, shares FROM investment_holdings WHERE account_id = ? AND date = ?",
                        (tsp_id, anchor_date),
                    ).fetchall()
                    known_units = {r["ticker"]: r["shares"] for r in rows}

                # Write per-fund holdings for today
                holding_rows: list[dict] = []
                for fund_name, data in fund_positions.items():
                    ticker = _fund_to_ticker(fund_name)
                    balance = data.get("balance", 0.0)
                    if balance <= 0:
                        continue
                    # Prefer scraped units/NAV; fall back to last known units
                    units = data.get("units") or known_units.get(ticker)
                    nav = data.get("nav") or (
                        (balance / units) if units and units > 0 else None
                    )

                    holding_rows.append({
                        "account_id": tsp_id,
                        "date": today,
                        "ticker": ticker,
                        "shares": units if units is not None else 0.0,
                        "close_price": nav,
                        "market_value": balance,
                        "cost_basis": None,
                    })

                record_investment_holdings(conn, holding_rows)

                # Portfolio snapshot.  DELETE-then-INSERT preserves the
                # original semantics: an in-day re-scrape replaces the
                # earlier row rather than appending a duplicate.
                ts = today + "T16:00:00"
                conn.execute(
                    "DELETE FROM portfolio_snapshots WHERE account_id = ? AND timestamp = ?",
                    (tsp_id, ts),
                )
                record_portfolio_snapshot(
                    conn,
                    account_id=tsp_id,
                    timestamp=ts,
                    total_account_value=total_balance,
                    cash_balance=0.0,
                )

                # Fetch today's prices from MaxTSP and cache
                prices = fetch_current_prices()
                if prices:
                    upsert_benchmark_prices(conn, prices, today)
                    log.info("[tsp] Cached %d fund prices for %s", len(prices), today)

                # Interpolate any gaps
                interpolate_daily_holdings(conn, account_id=tsp_id)

                conn.commit()

            log.info("[tsp] Persisted scraped holdings for %s", today)

        except Exception as e:
            log.warning("[tsp] Holdings persistence failed (non-fatal): %s", e)

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_dollar(text: str) -> float:
        """Parse a dollar string like '$36,901.55' to float."""
        cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
