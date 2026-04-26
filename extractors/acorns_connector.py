"""
extractors/acorns_connector.py — Acorns connector.

Concrete InstitutionConnector subclass implementing the Acorns-specific
login flow and data extraction.
"""

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
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
from dal.investments_writes import record_portfolio_snapshot
from extractors.sms_otp import wait_for_otp
from extractors.ai_backstop import (
    resilient_find,
    resilient_click,
    get_selector_group,
)

log = logging.getLogger("sentry.extractors.acorns")


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
        return "https://app.acorns.com/invest/core"

    @property
    def login_url(self) -> str:
        return "https://oak.acorns.com/sign-in"

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
        # Wait for the login form to render (oak.acorns.com is a SPA)
        try:
            page.wait_for_selector("input#email", state="visible", timeout=10000)
        except Exception:
            log.debug(
                "[%s] email field not yet visible, continuing...", self.institution
            )

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

            resilient_click(page, submit_group)
            return True
        else:
            log.info(
                f"[{self.institution}] No credentials provided. Password Manager expected."
            )
            return False

    def _wait_for_mfa(self, page: Page, timeout_seconds: int = 300) -> bool:
        """Auto-detect login/MFA completion and intercept SMS OTP for Acorns.

        Returns:
            True if MFA completed successfully, False if timed out.
        """
        if self._is_post_login(page):
            return True

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
                    return True
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

        log.warning(
            "[%s] MFA wait timed out after %ds", self.institution, timeout_seconds
        )
        return False

    # ── Logout ────────────────────────────────────────────────────────────

    def _perform_logout(self, page: Page) -> None:
        """Log out of Acorns after export.

        Strategy:
          1. Click "Profile & Settings" in the sidebar
          2. Click "Sign Out" / "Log Out"
          3. Fallback: navigate to the Acorns logout URL
        """
        log.info("[%s] Logging out...", self.institution)

        try:
            # Navigate to a known base page first (avoid being on a deep detail page)
            page.goto(
                "https://app.acorns.com", wait_until="domcontentloaded", timeout=15000
            )
            page.wait_for_timeout(2000)

            # Strategy 1: Click "Profile & Settings" then "Sign Out"
            profile_selectors = [
                'a:has-text("Profile & Settings")',
                'a:has-text("Profile")',
                'button:has-text("Profile")',
                '[data-testid="profile-settings"]',
            ]
            for sel in profile_selectors:
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        page.wait_for_timeout(2000)
                        break
                except Exception:
                    continue

            # Look for Sign Out / Log Out
            signout_selectors = [
                'a:has-text("Sign Out")',
                'button:has-text("Sign Out")',
                'a:has-text("Log Out")',
                'button:has-text("Log Out")',
                '[data-testid="signout"]',
            ]
            found = False
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
                # Strategy 2: JS-based click — Acorns sometimes renders
                # the sign-out link inside a scrollable settings panel
                found = page.evaluate("""
                    (() => {
                        const links = document.querySelectorAll('a, button');
                        for (const el of links) {
                            const t = (el.innerText || '').trim().toLowerCase();
                            if (t === 'sign out' || t === 'log out') {
                                el.click();
                                return true;
                            }
                        }
                        return false;
                    })()
                """)

            if not found:
                # Strategy 3: Navigate to logout URL
                log.info(
                    "[%s] Sign Out not found, navigating to logout URL",
                    self.institution,
                )
                page.goto(
                    "https://app.acorns.com/logout",
                    wait_until="domcontentloaded",
                    timeout=15000,
                )

            page.wait_for_timeout(2000)
            print("  🔓  Logged out of Acorns")
            log.info("[%s] Logout complete", self.institution)

        except Exception as e:
            raise RuntimeError(f"Acorns logout failed: {e}") from e

    # ── Confirmations download directory ─────────────────────────────────
    _CONF_DIR = Path(__file__).resolve().parent.parent / "raw_exports" / "acorns"

    def _trigger_export(self, page: Page, accounts: list[AccountConfig]) -> list[Path]:
        """Execute the Acorns export: confirmations → snapshot → sanity check.

        Phase 1: Portfolio snapshot (total value for net worth).
        Phase 2: Download trade confirmations (primary data source).
        Phase 3: Share count scrape + sanity check vs confirmations.
        Phase 4: Delta-logging FALLBACK (only if no confirmations found).
        """
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

        # ── Phase 1: Portfolio Snapshot ──────────────────────────────────
        print(f"\n  ── Phase 1: Snapshot Extraction ({invest_acct.name}) ──")
        snapshot = self._scrape_portfolio_snapshot(page)
        if not snapshot:
            print("       ✗ Could not extract portfolio snapshot.")
            return downloaded_files

        # ── Phase 2: Trade Confirmations (primary) ──────────────────────
        print("\n  ── Phase 2: Trade Confirmations ──")
        conf_files = self._download_confirmations(page, invest_acct)
        confirmations_found = len(conf_files)
        if conf_files:
            downloaded_files.extend(conf_files)
            print(f"       ✔ Downloaded {len(conf_files)} confirmation(s)")
            self._process_confirmations(conf_files, invest_acct)
        else:
            print("       ⚠ No new confirmations found")

        # ── Phase 3: Share Count Scrape (sanity check) ──────────────────
        print("\n  ── Phase 3: Position Scrape ──")
        positions = self._scrape_positions(page)
        if positions and confirmations_found > 0:
            self._sanity_check_positions(invest_acct, positions)
        elif not positions:
            print("       ⚠ Could not extract complete positions.")

        # ── Phase 4: Delta-Logging (fallback) ───────────────────────────
        if confirmations_found == 0:
            print("\n  ── Phase 4: Delta-Logging (fallback) ──")
            self._process_delta_logging(invest_acct, snapshot, positions or [])
        else:
            # Still log the snapshot even when confirmations handled trades
            db_acct_id = f"{self.institution}_{invest_acct.last4}"
            with get_db() as conn:
                conn.execute(
                    """INSERT INTO portfolio_snapshots
                       (account_id, timestamp, total_account_value, cash_balance)
                       VALUES (?, ?, ?, ?)""",
                    (db_acct_id, snapshot["timestamp"],
                     snapshot["total_account_value"], snapshot["cash_balance"]),
                )
                conn.commit()

        # Set summary balance
        fmt_bal = f"${snapshot['total_account_value']:,.2f}"
        self._result_balances[invest_acct.last4] = {
            "name": invest_acct.name,
            "balance": fmt_bal,
        }
        log.info(f"[{self.institution}] Finished export phase.")
        return downloaded_files

    # ── Month name/number mapping ──────────────────────────────────────
    _MONTH_NAMES = {
        "January": 1, "February": 2, "March": 3, "April": 4,
        "May": 5, "June": 6, "July": 7, "August": 8,
        "September": 9, "October": 10, "November": 11, "December": 12,
    }

    def _download_confirmations(
        self, page: Page, acct: AccountConfig
    ) -> list[Path]:
        """Navigate to Confirmations section and download unprocessed PDFs.

        Path: app.acorns.com/documents/core/statements
              → switch the "Statements" dropdown to "Confirmations"
              → iterate Download links for dates we haven't processed.

        Returns list of downloaded file paths.
        """
        import re
        from datetime import date as date_type

        self._CONF_DIR.mkdir(parents=True, exist_ok=True)
        db_acct_id = f"{self.institution}_{acct.last4}"

        # Find the latest confirmation we've already processed
        with get_db() as conn:
            row = conn.execute(
                """SELECT MAX(timestamp) FROM positions_ledger
                   WHERE account_id = ? AND source = 'confirmation'""",
                (db_acct_id,),
            ).fetchone()
        last_processed = row[0][:10] if row and row[0] else None
        if last_processed:
            print(f"       ℹ Last processed confirmation: {last_processed}")

        # ── Step 1: Navigate to Documents & Statements page ─────────────
        docs_url = "https://app.acorns.com/documents/core/statements"
        try:
            page.goto(docs_url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2500)
        except Exception as e:
            log.warning("[%s] Could not navigate to Documents page: %s", self.institution, e)
            return []

        # ── Step 2: Switch dropdown from "Statements" to "Confirmations" ─
        # The page has two dropdowns: "Invest" and "Statements".
        # Click the "Statements" dropdown, then select "Confirmations".
        self._screenshot(page, "documents_page", error_only=False)

        switched = False
        try:
            # Find the Statements dropdown — try selectors one at a time
            stmt_selectors = [
                'button:has-text("Statements")',
                '[role="button"]:has-text("Statements")',
                'text="Statements"',
            ]
            stmt_btn = None
            for sel in stmt_selectors:
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        stmt_btn = el
                        break
                except Exception:
                    continue

            if stmt_btn:
                stmt_btn.click()
                page.wait_for_timeout(1500)
                self._screenshot(page, "statements_dropdown_open", error_only=False)

                # Find and click "Confirmations" in the opened dropdown
                conf_selectors = [
                    'text="Confirmations"',
                    '[role="option"]:has-text("Confirmations")',
                    '[role="menuitem"]:has-text("Confirmations")',
                    'li:has-text("Confirmations")',
                    'a:has-text("Confirmations")',
                    'button:has-text("Confirmations")',
                ]
                for sel in conf_selectors:
                    try:
                        el = page.query_selector(sel)
                        if el and el.is_visible():
                            el.click()
                            page.wait_for_timeout(2500)
                            switched = True
                            print("       ✔ Switched to Confirmations view")
                            break
                    except Exception:
                        continue

                if not switched:
                    log.warning("[%s] 'Confirmations' option not found in dropdown", self.institution)
            else:
                log.warning("[%s] 'Statements' dropdown button not found on page", self.institution)
        except Exception as e:
            log.warning("[%s] Failed to switch to Confirmations: %s", self.institution, e)

        if not switched:
            self._screenshot(page, "confirmations_switch_failed")
            log.info("[%s] Could not reach Confirmations, will use delta-logging", self.institution)
            return []

        # ── Step 3: Read the year headers and identify current context ───
        # The confirmations list shows dates like "April 6", "April 2",
        # "March 30", etc., grouped under year headers like "2026", "2025".
        # We parse row text to extract dates, using the nearest year header.
        download_info = page.evaluate("""
            (() => {
                const results = [];
                let currentYear = new Date().getFullYear();
                const body = document.body.innerText || '';

                // Find all elements with 'Download' text
                const allElements = document.querySelectorAll('*');
                for (const el of allElements) {
                    const text = (el.textContent || '').trim();
                    // Year header detection
                    if (/^20\\d{2}$/.test(text) && el.children.length === 0) {
                        currentYear = parseInt(text);
                    }
                    // Download link detection
                    if (text === 'Download' && (el.tagName === 'A' || el.tagName === 'BUTTON'
                        || el.getAttribute('role') === 'button')) {
                        // Walk up to find the row context
                        let row = el.closest('tr, [class*="row"], [class*="Row"]');
                        if (!row) row = el.parentElement?.parentElement || el.parentElement;
                        const rowText = (row ? row.textContent : '').trim();
                        results.push({
                            rowText: rowText,
                            year: currentYear,
                        });
                    }
                }
                return results;
            })()
        """)

        if not download_info:
            log.info("[%s] No Download links found on Confirmations page", self.institution)
            return []

        print(f"       ℹ Found {len(download_info)} confirmation(s) on page")

        # ── Step 4: Download unprocessed confirmations ───────────────────
        downloaded = []
        seen_dates: set[str] = set()  # deduplicate within this session
        download_links = page.query_selector_all(
            'a:has-text("Download"), button:has-text("Download")'
        )

        for i, link in enumerate(download_links):
            if i >= len(download_info):
                break

            row_text = download_info[i]["rowText"]
            year = download_info[i]["year"]

            # Extract month + day from row text (e.g. "April 6 Download")
            date_match = re.search(
                r"(January|February|March|April|May|June|July|August|"
                r"September|October|November|December)\s+(\d{1,2})",
                row_text,
            )
            if not date_match:
                continue

            month_num = self._MONTH_NAMES[date_match.group(1)]
            day = int(date_match.group(2))
            conf_date = date_type(year, month_num, day)
            conf_date_str = conf_date.isoformat()

            # Deduplicate within this session
            if conf_date_str in seen_dates:
                continue
            seen_dates.add(conf_date_str)

            # Skip if already processed in a prior run
            if last_processed and conf_date_str <= last_processed:
                continue

            dest_filename = f"acorns_confirmation_{conf_date_str}.pdf"
            dest = self._CONF_DIR / dest_filename

            # Reuse cached file if it exists (prior run that wasn't committed)
            if dest.exists():
                downloaded.append(dest)
                print(f"       ♻ Cached: {dest_filename}")
                continue

            # Download
            try:
                with page.expect_download(timeout=15000) as dl_info:
                    link.click()
                dl = dl_info.value
                dl.save_as(str(dest))
                downloaded.append(dest)
                print(f"       📥 {dest_filename}")
                page.wait_for_timeout(1000)
            except Exception as e:
                log.warning("[%s] Failed to download %s: %s", self.institution, conf_date_str, e)

        return downloaded

    def _process_confirmations(
        self, conf_files: list[Path], acct: AccountConfig
    ) -> None:
        """Parse downloaded confirmation PDFs and write to positions_ledger."""
        from dal.parsers.acorns_confirmation import AcornsConfirmationParser

        parser = AcornsConfirmationParser()
        total_trades = 0
        # Deduplicate by resolved path (handles same file appearing twice)
        seen_paths: set[str] = set()

        with get_db() as conn:
            for pdf_path in conf_files:
                resolved = str(pdf_path.resolve())
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)

                try:
                    content = pdf_path.read_bytes()
                    result = parser.parse(content)
                except Exception as e:
                    log.warning("[%s] Failed to read %s: %s", self.institution, pdf_path.name, e)
                    continue

                if result.can_commit:
                    summary = parser.commit(conn, result)
                    trades = summary.get("total_trades", 0)
                    total_trades += trades
                    print(
                        f"       ✔ {pdf_path.name}: {trades} trades "
                        f"(inserted={summary['inserted']}, upgraded={summary['upgraded']})"
                    )
                else:
                    log.warning("[%s] Confirmation %s not committable: %s",
                                self.institution, pdf_path.name, result.warnings)

        print(f"       📊 Total: {total_trades} trades from {len(seen_paths)} confirmation(s)")

    def _sanity_check_positions(
        self, acct: AccountConfig, positions: list[dict]
    ) -> None:
        """Compare scraped share counts to confirmation-derived running totals."""
        db_acct_id = f"{self.institution}_{acct.last4}"

        with get_db() as conn:
            for pos in positions:
                ticker = pos["ticker"]
                scraped_shares = pos["shares"]  # Decimal

                # Get latest running total from positions_ledger
                row = conn.execute(
                    """SELECT new_total_shares_dec
                       FROM positions_ledger
                       WHERE account_id = ? AND ticker = ?
                       ORDER BY timestamp DESC LIMIT 1""",
                    (db_acct_id, ticker),
                ).fetchone()

                if row and row["new_total_shares_dec"]:
                    ledger_shares = Decimal(row["new_total_shares_dec"])
                    diff = abs(scraped_shares - ledger_shares)
                    if diff > Decimal("0.01"):
                        print(
                            f"       ⚠ MISMATCH {ticker}: "
                            f"scraped={scraped_shares}, ledger={ledger_shares}, "
                            f"diff={diff}"
                        )
                    else:
                        print(f"       ✔ {ticker}: {scraped_shares} shares (matches ledger)")
                else:
                    print(f"       ℹ {ticker}: {scraped_shares} shares (no ledger entry yet)")

    def _scrape_portfolio_snapshot(self, page) -> dict | None:
        """Extract top-line portfolio value from the Acorns Invest page."""
        try:
            invest_url = "https://app.acorns.com/invest/core"
            log.info("[%s] Navigating to %s for snapshot", self.institution, invest_url)
            page.goto(invest_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # Extract the primary dollar value from the Invest page.
            # Acorns displays the total value prominently in the green hero
            # banner (e.g. "$7,934.69").  We scan all visible text elements
            # for dollar-formatted strings and take the first match, which
            # is the largest/most prominent one.
            total_value_str = page.evaluate("""
                (() => {
                    const els = document.querySelectorAll('h1,h2,h3,h4,p,span,div');
                    for (const el of els) {
                        const t = (el.innerText || '').trim();
                        if (/^\\$[\\d,]+\\.\\d{2}$/.test(t)) {
                            const v = parseFloat(t.replace(/[$,]/g, ''));
                            if (v > 100) return t;
                        }
                    }
                    return null;
                })()
            """)

            if not total_value_str:
                log.warning(
                    "[%s] Could not find portfolio value on page", self.institution
                )
                return None

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
        """Extract exact fractional share counts from Acorns fund detail pages.

        Strategy:
          1. Navigate to /invest/core/portfolio to discover which tickers exist
          2. For each ticker, navigate to its detail page and extract the share count
        """
        positions = []

        # Known Acorns Core portfolio ETFs (used as fallback if DOM discovery fails)
        KNOWN_TICKERS = ["VOO", "IJH", "IJR", "IXUS"]

        try:
            portfolio_url = "https://app.acorns.com/invest/core/portfolio"
            log.info(
                "[%s] Navigating to %s for positions", self.institution, portfolio_url
            )
            page.goto(portfolio_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # Discover tickers from the portfolio page links/text
            discovered_tickers = page.evaluate("""
                (() => {
                    const known = ['VOO', 'IJH', 'IJR', 'IXUS'];
                    const found = new Set();
                    const allText = document.body.innerText || '';
                    for (const t of known) {
                        if (allText.includes(t)) found.add(t);
                    }
                    // Also check links that contain ticker slugs
                    document.querySelectorAll('a[href*="portfolio"]').forEach(a => {
                        for (const t of known) {
                            if (a.href.toLowerCase().includes(t.toLowerCase())) {
                                found.add(t);
                            }
                        }
                    });
                    return Array.from(found);
                })()
            """)

            tickers = discovered_tickers if discovered_tickers else KNOWN_TICKERS
            log.info("[%s] Found tickers: %s", self.institution, tickers)

            fund_errors = []

            # Visit each ticker's fund detail page to extract share count
            for ticker in tickers:
                detail_url = (
                    f"https://app.acorns.com/invest/core/portfolio/fund/{ticker}"
                )
                try:
                    log.info(
                        "[%s] Fetching shares for %s at %s",
                        self.institution,
                        ticker,
                        detail_url,
                    )
                    page.goto(detail_url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(2500)

                    # Extract share count from the fund detail page.
                    # Layout: "Your position" section has rows like:
                    #   "Market value"  "$4,423.91"
                    #   "Shares"        "7.0701"
                    # The label and value are separate DOM elements on
                    # different lines in the innerText dump.
                    shares_str = page.evaluate("""
                        (() => {
                            const body = document.body.innerText || '';
                            const lines = body.split('\\n').map(l => l.trim()).filter(Boolean);
                            for (let i = 0; i < lines.length; i++) {
                                if (/^Shares/.test(lines[i])) {
                                    // The value is typically the next non-empty line
                                    for (let j = i + 1; j <= Math.min(i + 3, lines.length - 1); j++) {
                                        const numMatch = lines[j].match(/^(\\d+\\.\\d{2,6})$/);
                                        if (numMatch) return numMatch[1];
                                    }
                                    // Also check same line: "Shares   7.0701"
                                    const inline = lines[i].match(/Shares\\s+(\\d+\\.\\d{2,6})/);
                                    if (inline) return inline[1];
                                }
                            }
                            // Fallback: look for "X.XXXX shares" pattern
                            const match = body.match(/(\\d+\\.\\d{2,6})\\s*shares/i);
                            if (match) return match[1];
                            return null;
                        })()
                    """)

                    if shares_str:
                        # Keep as Decimal string — do NOT convert to float here.
                        # The scraper is the last place we touch this number before
                        # it hits positions_ledger; we must honour schema V4 precision.
                        shares_dec = Decimal(shares_str)
                        positions.append(
                            {
                                "ticker": ticker,
                                "shares": shares_dec,
                                "shares_str": shares_str,
                            }
                        )
                        print(f"       ✔ Holding: {ticker} | {shares_dec:.4f} shares")
                    else:
                        log.warning(
                            "[%s] Could not extract shares for %s",
                            self.institution,
                            ticker,
                        )
                        print(f"       ✗ {ticker}: Could not extract share count")
                        fund_errors.append(ticker)

                except Exception as e:
                    log.warning(
                        "[%s] Failed to fetch %s details: %s",
                        self.institution,
                        ticker,
                        e,
                    )
                    print(f"       ✗ {ticker}: Error — {e}")
                    fund_errors.append(ticker)

            if fund_errors:
                log.error(
                    "Partial scrape: %d/%d funds failed (%s). "
                    "Discarding ALL fund data to prevent phantom deltas.",
                    len(fund_errors),
                    len(tickers),
                    ", ".join(fund_errors),
                )
                return []
            else:
                log.info("All %d funds scraped successfully", len(positions))
                return positions

        except Exception as e:
            log.error("Fund scraping failed completely — no fund data written: %s", e)

        return []

    def _process_delta_logging(
        self, acct: AccountConfig, snapshot: dict, positions: list[dict]
    ):
        """Compare scraped positions to DB to determine implied trades."""
        db_acct_id = f"{self.institution}_{acct.last4}"
        ts = snapshot["timestamp"]

        with get_db() as conn:
            # 1. Log the top-line snapshot
            record_portfolio_snapshot(
                conn,
                account_id=db_acct_id,
                timestamp=ts,
                total_account_value=snapshot["total_account_value"],
                cash_balance=snapshot["cash_balance"],
            )

            # 2. Process deltas for each holding
            for pos in positions:
                ticker = pos["ticker"]
                new_shares = pos["shares"]  # Decimal
                new_shares_str = pos.get("shares_str", str(new_shares))

                row = conn.execute(
                    """
                    SELECT new_total_shares, new_total_shares_dec
                    FROM positions_ledger
                    WHERE account_id = ? AND ticker = ?
                    ORDER BY timestamp DESC LIMIT 1
                """,
                    (db_acct_id, ticker),
                ).fetchone()

                # Prefer the high-precision TEXT column; fall back to REAL
                if row:
                    dec_str = row["new_total_shares_dec"]
                    if dec_str:
                        try:
                            last_shares = Decimal(dec_str)
                        except (InvalidOperation, TypeError):
                            last_shares = Decimal(str(row["new_total_shares"] or 0))
                    else:
                        last_shares = Decimal(str(row["new_total_shares"] or 0))
                else:
                    last_shares = Decimal("0")

                delta = new_shares - last_shares  # Decimal − Decimal

                if abs(delta) > Decimal("0.0001"):
                    txn_type = "IMPLIED_BUY" if delta > 0 else "IMPLIED_SELL"
                    if last_shares == Decimal("0"):
                        txn_type = "INITIAL_BASELINE"

                    print(
                        f"       ⚡ {txn_type}: {ticker} | Delta: {delta:+.4f} shares"
                    )

                    price, cost_basis = self._get_yfinance_enrichment(
                        ticker, float(delta)
                    )

                    # AI-030: populate `cost_basis_dec` on IMPLIED_BUY /
                    # INITIAL_BASELINE rows so `dal/investments.get_lots`
                    # doesn't fall back to observation-day MTM. Acorns
                    # doesn't expose true purchase price, so `cost_basis`
                    # (= price × |delta| from `_get_yfinance_enrichment`)
                    # remains a contemporaneous mark-to-market
                    # approximation — but anchored to the lot's date,
                    # not to refresh-day. SELL rows leave it NULL because
                    # `realized_gain_dec` is computed against the FIFO
                    # cost-basis series, not the SELL row's own basis.
                    is_buy_shape = txn_type in (
                        "IMPLIED_BUY",
                        "INITIAL_BASELINE",
                    )
                    cost_basis_dec_str = (
                        str(cost_basis)
                        if is_buy_shape and cost_basis is not None
                        else None
                    )

                    conn.execute(
                        """
                        INSERT INTO positions_ledger
                        (account_id, timestamp, ticker, transaction_type,
                         share_delta, new_total_shares,
                         yfinance_closing_price, estimated_transaction_value,
                         share_delta_dec, new_total_shares_dec,
                         cost_basis_dec, source)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scraper')
                    """,
                        (
                            db_acct_id,
                            ts,
                            ticker,
                            txn_type,
                            float(delta),  # legacy REAL column
                            float(new_shares),  # legacy REAL column
                            price,
                            cost_basis,
                            str(delta),  # V4 TEXT precision column
                            new_shares_str,  # V4 TEXT precision column
                            cost_basis_dec_str,
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
