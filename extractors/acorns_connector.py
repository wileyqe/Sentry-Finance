"""
extractors/acorns_connector.py — Acorns connector.

Concrete InstitutionConnector subclass implementing the Acorns-specific
login flow and data extraction.
"""

import logging
from datetime import datetime
from pathlib import Path
from playwright.sync_api import Page

try:
    import yfinance as yf
except ImportError:
    yf = None

from skills.institution_connector import (
    InstitutionConnector,
    AccountConfig,
)
from dal.database import get_db
from extractors.sms_otp import wait_for_otp
from extractors.ai_backstop import (
    resilient_find,
    resilient_click,
    get_selector_group,
)

log = logging.getLogger("sentry")


class AcornsConnector(InstitutionConnector):
    """
    Acorns connector.
    """

    @property
    def institution(self) -> str:
        return "acorns"

    @property
    def display_name(self) -> str:
        return "Acorns"

    @property
    def export_url(self) -> str:
        # Dashboard URL for Acorns
        return "https://app.acorns.com/present"

    @property
    def login_url(self) -> str:
        return "https://app.acorns.com/login"

    def _is_session_valid(self, page: Page) -> bool:
        """Override session valid check to account for Acorns SPA behavior."""
        try:
            log.info(
                f"[{self.institution}] Checking session validity at {self.export_url}"
            )
            page.goto(self.export_url, wait_until="domcontentloaded", timeout=45000)

            # Additional wait to ensure redirects happen
            page.wait_for_timeout(3000)

            current_url = page.url.lower()
            log.info(f"[{self.institution}] URL after navigation: {current_url}")

            if any(kw in current_url for kw in ["login", "sign-in", "signin", "auth"]):
                log.info(f"[{self.institution}] Redirected to login page.")
                return False

            # If we are somehow on an unauthenticated page without 'login' in the URL,
            # we should check for the email input field.
            if page.query_selector('input[type="email"]') or page.query_selector(
                "input#email"
            ):
                log.info(
                    f"[{self.institution}] Login field found on page. Not authenticated."
                )
                return False

            return True
        except Exception as e:
            log.warning(f"[{self.institution}] Session check error: {e}")
            return False

    def _is_post_login(self, page: Page) -> bool:
        """
        Detect Acorns post-login state via DOM inspection.
        """
        current_url = page.url.lower()
        if any(kw in current_url for kw in ["login", "sign-in", "signin", "auth"]):
            return False

        return super()._is_post_login(page)

    def _perform_login(self, page: Page, credentials: dict | None = None) -> bool:
        """
        Navigate to Acorns login and authenticate.
        """
        log.info(f"[{self.institution}] Navigating to login URL: {self.login_url}")
        page.goto(self.login_url, wait_until="domcontentloaded", timeout=45000)

        # Load selector registry
        from extractors.ai_backstop import load_selectors

        reg = load_selectors()

        if credentials and "username" in credentials and "password" in credentials:
            log.info(f"[{self.institution}] Using broker credentials.")
            user_group = get_selector_group(reg, f"{self.institution}.login.username")
            pw_group = get_selector_group(reg, f"{self.institution}.login.password")
            submit_group = get_selector_group(reg, f"{self.institution}.login.submit")

            email_el = resilient_find(page, user_group)
            pw_el = resilient_find(page, pw_group)

            if not email_el or not pw_el:
                log.error(f"[{self.institution}] Could not find login fields.")
                return False

            email_el.fill(credentials["username"])
            pw_el.fill(credentials["password"])

            pwd = credentials.get("password")
            if pwd:
                credentials["password"] = "CLEARED"

            resilient_click(page, submit_group)
            return True
        else:
            log.info(
                f"[{self.institution}] No credentials provided. Password Manager expected."
            )
            return False

    def _wait_for_mfa(self, page: Page, timeout_seconds: int = 300):
        """Auto-detect login/MFA completion and intercept SMS OTP for Acorns."""
        if self._is_post_login(page):
            return

        print()
        print("  ┌─────────────────────────────────────────────────┐")
        print(f"  │  [{self.display_name}] Waiting for login/MFA...  │")
        print("  └─────────────────────────────────────────────────┘")
        print()

        polls = timeout_seconds // 2
        otp_requested = False

        for i in range(polls):
            page.wait_for_timeout(2000)
            try:
                if self._is_post_login(page):
                    log.info(
                        "[%s] Login/MFA completed (URL: %s)",
                        self.institution,
                        page.url[:80],
                    )
                    return
            except Exception as e:
                log.debug("Login detection poll failed: %s", e)

            # Look for OTP entry fields
            if not otp_requested:
                try:
                    # Acorns typically asks for 6 digits or similar code
                    otp_field = page.query_selector(
                        'input[autocomplete="one-time-code"], '
                        'input[name*="code"], '
                        'input[id*="otp"], '
                        'input[type="number"]:visible'
                    )

                    if otp_field and otp_field.is_visible():
                        log.info(
                            "[%s] OTP field detected. Intercepting SMS...",
                            self.institution,
                        )
                        otp_requested = True

                        code = wait_for_otp(timeout=120, hint="Acorns")

                        if code:
                            log.info(
                                "[%s] Filling intercepted OTP: %s***",
                                self.institution,
                                code[:2],
                            )

                            # Determine if Acorns uses one single input or 6 split inputs
                            inputs = page.query_selector_all(
                                'input[autocomplete="one-time-code"], input[type="number"]'
                            )

                            if len(inputs) == len(code):
                                # 6 split inputs
                                log.info(
                                    "[%s] Filling split OTP inputs.", self.institution
                                )
                                for idx, char in enumerate(code):
                                    inputs[idx].fill(char)
                                    page.wait_for_timeout(100)

                                # If it doesn't auto-submit, press enter or click next
                                inputs[-1].press("Enter")
                            else:
                                # Normal single input
                                log.info(
                                    "[%s] Filling single OTP input.", self.institution
                                )
                                otp_field.fill(code)
                                page.wait_for_timeout(500)
                                otp_field.press("Enter")

                            try:
                                page.wait_for_load_state("networkidle", timeout=15000)
                            except Exception as e:
                                log.debug(
                                    "[%s] Wait for OTP submission timeout: %s",
                                    self.institution,
                                    e,
                                )
                except Exception as e:
                    log.debug(
                        "[%s] OTP interception logic error: %s", self.institution, e
                    )

    def _trigger_export(self, page: Page, accounts: list[AccountConfig]) -> list[Path]:
        """Execute the Delta-Logging export process for Acorns."""
        log.info(f"[{self.institution}] _trigger_export started.")
        downloaded_files = []

        invest_acct = next(
            (a for a in accounts if a.type.lower() == "investment"), None
        )
        if not invest_acct:
            log.warning(
                "[%s] No investment account configured in accounts.yaml",
                self.institution,
            )
            return downloaded_files

        print(f"\n  ── Phase 1: Snapshot Extraction ({invest_acct.name}) ──")

        # Scrape current totals
        snapshot = self._scrape_portfolio_snapshot(page)
        if not snapshot:
            print("       ✗ Could not extract portfolio snapshot.")
            return downloaded_files

        # Scrape precise share counts
        positions = self._scrape_positions(page)
        if not positions:
            print("       ✗ Could not extract positions.")
            return downloaded_files

        print(f"\n  ── Phase 2: Delta-Logging ──")
        self._process_delta_logging(invest_acct, snapshot, positions)

        # Set summary balance
        fmt_bal = f"${snapshot['total_account_value']:,.2f}"
        self._result_balances[invest_acct.last4] = {
            "name": invest_acct.name,
            "balance": fmt_bal,
        }
        log.info(f"[{self.institution}] Finished export phase.")
        return downloaded_files

    def _scrape_portfolio_snapshot(self, page) -> dict | None:
        """Extract top-line numbers."""
        try:
            # SCAFFOLDING: Replace with actual selectors once DOM is known
            total_value_str = "$0.00"  # Placeholder
            val = float(total_value_str.replace("$", "").replace(",", "").strip())

            snapshot = {
                "timestamp": datetime.now().isoformat(),
                "total_account_value": val,
                "cash_balance": 0.0,
            }
            print(f"       ✔ Portfolio Value: ${val:,.2f}")
            return snapshot
        except Exception as e:
            log.warning("Failed to extract snapshot: %s", e)
            return None

    def _scrape_positions(self, page) -> list[dict]:
        """Extract exact fractional share counts for holdings (e.g., VOO, IJH)."""
        positions = []
        try:
            # SCAFFOLDING: Mock data until DOM is mapped
            positions = [
                {"ticker": "VOO", "shares": 10.5123},
                {"ticker": "IXUS", "shares": 50.1234},
            ]
            for p in positions:
                print(f"       ✔ Holding: {p['ticker']} | {p['shares']:.4f} shares")
        except Exception as e:
            log.warning("Failed to extract positions: %s", e)

        return positions

    def _process_delta_logging(
        self, acct: AccountConfig, snapshot: dict, positions: list[dict]
    ):
        """Compare scraped positions to DB to determine implied trades."""
        db_acct_id = f"{self.institution}_{acct.last4}"
        ts = snapshot["timestamp"]

        with get_db() as conn:
            # 1. Log the top-line snapshot
            conn.execute(
                """
                INSERT INTO portfolio_snapshots (account_id, timestamp, total_account_value, cash_balance)
                VALUES (?, ?, ?, ?)
            """,
                (
                    db_acct_id,
                    ts,
                    snapshot["total_account_value"],
                    snapshot["cash_balance"],
                ),
            )

            # 2. Process deltas for each holding
            for pos in positions:
                ticker = pos["ticker"]
                new_shares = pos["shares"]

                row = conn.execute(
                    """
                    SELECT new_total_shares FROM positions_ledger
                    WHERE account_id = ? AND ticker = ?
                    ORDER BY timestamp DESC LIMIT 1
                """,
                    (db_acct_id, ticker),
                ).fetchone()

                last_shares = row["new_total_shares"] if row else 0.0
                delta = new_shares - last_shares

                if abs(delta) > 0.0001:
                    txn_type = "IMPLIED_BUY" if delta > 0 else "IMPLIED_SELL"
                    if last_shares == 0.0:
                        txn_type = "INITIAL_BASELINE"

                    print(
                        f"       ⚡ {txn_type}: {ticker} | Delta: {delta:+.4f} shares"
                    )

                    price, cost_basis = self._get_yfinance_enrichment(ticker, delta)

                    conn.execute(
                        """
                        INSERT INTO positions_ledger 
                        (account_id, timestamp, ticker, transaction_type, share_delta, new_total_shares, yfinance_closing_price, estimated_transaction_value)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            db_acct_id,
                            ts,
                            ticker,
                            txn_type,
                            delta,
                            new_shares,
                            price,
                            cost_basis,
                        ),
                    )
                else:
                    print(f"       ⏭️  {ticker}: Unchanged")

            conn.commit()

    def _get_yfinance_enrichment(
        self, ticker: str, delta: float
    ) -> tuple[float | None, float | None]:
        """Fetch closing price for the current day from yFinance."""
        if not yf:
            log.warning("yfinance not installed, skipping enrichment.")
            return None, None

        try:
            tk = yf.Ticker(ticker)
            hist = tk.history(period="1d")
            if not hist.empty:
                close_price = float(hist["Close"].iloc[-1])
                cost_basis = close_price * abs(delta)
                print(
                    f"          📈 yFinance logic: {ticker} @ ${close_price:.2f} (Est Value: ${cost_basis:.2f})"
                )
                return close_price, cost_basis
        except Exception as e:
            log.error("Failed to fetch yfinance data for %s: %s", ticker, e)

        return None, None
