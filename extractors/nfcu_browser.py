"""
extractors/nfcu_browser.py — Navy Federal Credit Union browser-based extractor.

Automates the full flow:
  1. Session check → restore or fresh login
  2. Credential entry (from env or interactive prompt)
  3. Pause for 2FA (human-in-the-loop)
  4. Navigate to each account's transaction history
  5. Download transactions as CSV
  6. Rename and normalize the downloaded files

The NFCU online banking portal uses Backbase (Angular SPA) hosted at
digitalomni.navyfederal.org. It uses Akamai Bot Manager for detection,
so we run in HEADED mode by default to let the user handle any challenges.

Usage:
    from extractors.nfcu_browser import NFCUBrowserExtractor

    extractor = NFCUBrowserExtractor()
    results = extractor.extract()
    for r in results:
        print(f"{r.account}: {r.row_count} rows")
"""
import logging
import pathlib
import shutil
from datetime import datetime

import pandas as pd

from extractors.base import BaseExtractor, ExtractionResult
from extractors.browser_manager import BrowserManager
from extractors.session_manager import SessionManager
from extractors.credentials import get_credentials, has_env_credentials

log = logging.getLogger("antigravity")

# ── NFCU-Specific Configuration ─────────────────────────────────────────────
# These selectors and URLs target the Backbase-powered NFCU digital banking
# portal. If NFCU updates their UI, these are the values to change.

NFCU_URLS = {
    "login": "https://digitalomni.navyfederal.org/signin/",
    "dashboard": "https://digitalomni.navyfederal.org/dashboard",
    "accounts": "https://digitalomni.navyfederal.org/accounts",
}

# Selectors for the login form (Angular components)
# These may need updating if NFCU changes their login page structure.
NFCU_SELECTORS = {
    # Login page
    "username_input": 'input[name="username"], input[id="username"], '
                      'input[placeholder*="Access Number"], '
                      'input[placeholder*="Username"], '
                      'input[data-testid="username"]',

    "password_input": 'input[name="password"], input[id="password"], '
                      'input[type="password"], '
                      'input[data-testid="password"]',

    "login_button":   'button[type="submit"], '
                      'button[data-testid="login-button"], '
                      'button:has-text("Sign In"), '
                      'button:has-text("Log In")',

    # Post-login indicators (proves we're authenticated)
    "dashboard_loaded": '[data-testid="accounts-summary"], '
                        '.account-summary, '
                        '[class*="dashboard"], '
                        '[class*="account-list"], '
                        'text="Account Summary"',

    # Account navigation
    "account_links":  '[data-testid="account-item"] a, '
                      '.account-item a, '
                      '[class*="account"] a[href*="account"]',

    # Transaction history
    "txn_history":    '[data-testid="transaction-list"], '
                      '.transaction-list, '
                      '[class*="transaction"]',

    # Download button within transaction history
    "download_btn":   'button:has-text("Download"), '
                      'a:has-text("Download"), '
                      '[data-testid="download-transactions"], '
                      'button[aria-label*="download" i], '
                      'button[aria-label*="export" i]',

    # CSV format option (in download dialog)
    "csv_option":     'text="CSV", '
                      'label:has-text("CSV"), '
                      'input[value="csv"], '
                      '[data-testid="csv-option"]',

    # Date range selector
    "date_range":     '[data-testid="date-range"], '
                      'select[name*="date"], '
                      'button:has-text("Date Range")',
}

# How long to wait for various page loads (seconds)
NFCU_TIMEOUTS = {
    "page_load": 30,
    "login_submit": 15,
    "dashboard_load": 30,
    "account_load": 20,
    "download": 30,
    "two_factor": 300,   # 5 minutes for human 2FA
}


class NFCUBrowserExtractor(BaseExtractor):
    """Extracts transaction data from Navy Federal via browser automation.

    Flow:
      1. Check for saved session in .sessions/
      2. If valid session exists, restore it and skip login
      3. If no session, open headed browser:
         a. Navigate to login page
         b. Fill username/password (from env vars or interactive prompt)
         c. Click login
         d. PAUSE for human 2FA/CAPTCHA
         e. Save session for future runs
      4. Navigate to each account's transaction history
      5. Download CSV for each account
      6. Return ExtractionResult objects
    """

    def __init__(self, headless: bool = False, slow_mo: int = 100):
        """
        Args:
            headless: Run without visible window. NOT recommended for NFCU
                      (Akamai bot detection will likely block headless).
            slow_mo: Milliseconds to slow Playwright actions.
        """
        self._base = pathlib.Path(__file__).resolve().parent.parent
        self._headless = headless
        self._slow_mo = slow_mo
        self._session_mgr = SessionManager()
        self._browser_mgr = BrowserManager(
            download_dir=self._base / "downloads" / "nfcu",
            screenshot_dir=self._base / "screenshots",
            headless=headless,
            slow_mo=slow_mo,
        )

    @property
    def institution(self) -> str:
        return "Navy Federal"

    # ── Main Entry Point ──────────────────────────────────────────────────

    def extract(self, accounts: list[str] | None = None,
                **kwargs) -> list[ExtractionResult]:
        """Extract transaction data from NFCU.

        Args:
            accounts: Optional list of account names to extract. If None,
                      extracts all visible accounts.

        Returns:
            List of ExtractionResult objects (one per account).
        """
        results = []

        # Check for existing session
        storage_state = None
        if self._session_mgr.has_session("nfcu"):
            print("  🔑  Found saved NFCU session, attempting restore...")
            storage_state = self._session_mgr.load("nfcu")

        # Clear previous downloads
        self._browser_mgr.clear_downloads()

        with self._browser_mgr.launch(storage_state=storage_state) as (browser, context, page):

            # ── Step 1: Authenticate ─────────────────────────────────────
            if not self._is_authenticated(page):
                print("  🔐  Session expired or not found — logging in...")
                success = self._login(page)
                if not success:
                    log.error("Login failed for NFCU")
                    return []

                # Save session after successful login
                self._session_mgr.save_from_context("nfcu", context)
                print("  💾  Session saved for future runs")
            else:
                print("  ✅  Session restored — already authenticated")

            # ── Step 2: Discover Accounts ────────────────────────────────
            account_list = self._discover_accounts(page)
            if not account_list:
                log.warning("No accounts found on dashboard")
                self._browser_mgr.screenshot(page, "no_accounts")
                return []

            print(f"  📋  Found {len(account_list)} accounts")
            for acct in account_list:
                print(f"       • {acct['name']} ({acct.get('type', 'unknown')})")

            # Filter to requested accounts
            if accounts:
                account_list = [a for a in account_list
                                if a["name"].lower() in [x.lower() for x in accounts]]

            # ── Step 3: Download Transactions ────────────────────────────
            for acct in account_list:
                print(f"\n  📥  Downloading: {acct['name']}...")
                try:
                    csv_path = self._download_transactions(page, acct)
                    if csv_path and csv_path.exists():
                        df = self._parse_csv(csv_path, acct)
                        if df is not None and not df.empty:
                            results.append(ExtractionResult(
                                institution="Navy Federal",
                                account=acct["name"],
                                df=df,
                                timestamp=datetime.now(),
                                source=f"browser:{csv_path.name}",
                            ))
                            print(f"  ✔  {acct['name']}: {len(df)} rows")
                        else:
                            print(f"  ⚠  {acct['name']}: CSV empty or unparseable")
                    else:
                        print(f"  ✗  {acct['name']}: Download failed")
                except Exception as e:
                    log.error("Error extracting %s: %s", acct["name"], e)
                    self._browser_mgr.screenshot(page, f"error_{acct['name']}")

            # Save updated session
            self._session_mgr.save_from_context("nfcu", context)

        return results

    # ── Authentication ────────────────────────────────────────────────────

    def _is_authenticated(self, page) -> bool:
        """Check if the current session is authenticated.

        Navigates to the dashboard and checks for account indicators.
        """
        try:
            self._browser_mgr.safe_goto(
                page, NFCU_URLS["dashboard"],
                timeout=NFCU_TIMEOUTS["page_load"]
            )
            self._browser_mgr.random_delay(2, 4)

            # Check if we landed on the dashboard vs redirected to login
            current_url = page.url.lower()

            if "signin" in current_url or "login" in current_url:
                return False

            # Try to find a dashboard element
            found = self._browser_mgr.wait_for_element(
                page, NFCU_SELECTORS["dashboard_loaded"],
                timeout=10
            )
            return found

        except Exception as e:
            log.debug("Auth check failed: %s", e)
            return False

    def _login(self, page) -> bool:
        """Perform the login flow. Browser-first design.

        If NFCU_USERNAME and NFCU_PASSWORD environment variables are set,
        credentials are auto-filled. Otherwise the user logs in directly
        in the browser window and the script waits.

        Returns True if login succeeded (no longer on /signin/ page).
        """
        # Navigate to login page
        print("  🌐  Navigating to NFCU login...")
        if not self._browser_mgr.safe_goto(
            page, NFCU_URLS["login"],
            timeout=NFCU_TIMEOUTS["page_load"]
        ):
            return False

        self._browser_mgr.random_delay(2, 4)
        self._browser_mgr.screenshot(page, "login_page")

        # ── Attempt automated fill ───────────────────────────────────────
        creds = None
        if has_env_credentials("NFCU"):
            print("  ✏️   Credentials found in environment — auto-filling...")
            creds = get_credentials("NFCU")
        else:
            # Offer interactive entry
            print("\n  ⌨️   Enter credentials in terminal to auto-fill,")
            print("       OR press Enter to log in manually in the browser window.")
            username = input("  👤  Username (Access Number): ").strip()
            if username:
                import getpass
                password = getpass.getpass("  🔑  Password: ").strip()
                creds = {"username": username, "password": password}

        if creds:
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
                self._browser_mgr.random_delay(1, 2)

                self._try_fill_field(
                    page, NFCU_SELECTORS["username_input"],
                    creds["username"], "username"
                )
                self._browser_mgr.random_delay(0.5, 1.5)

                self._try_fill_field(
                    page, NFCU_SELECTORS["password_input"],
                    creds["password"], "password"
                )
                self._browser_mgr.random_delay(0.5, 1.0)

                self._try_click(
                    page, NFCU_SELECTORS["login_button"], "login button"
                )
                self._browser_mgr.random_delay(3, 5)

            except Exception as e:
                log.warning("Auto-fill failed: %s — falling back to manual", e)

        # ── Single human pause: covers login + 2FA + CAPTCHA ─────────────
        # Poll the page URL to see if the user has already logged in.
        # If still on a login/verify page, pause for the human.
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        current_url = page.url.lower()
        if any(kw in current_url for kw in ("signin", "login", "verify", "mfa")):
            print()
            print("  ┌─────────────────────────────────────────────────┐")
            print("  │  Log in using the browser window that opened.   │")
            print("  │  Complete credentials, 2FA, and any CAPTCHAs.   │")
            print("  │                                                  │")
            print("  │  When you see your account dashboard,            │")
            print("  │  come back here and press ENTER.                 │")
            print("  └─────────────────────────────────────────────────┘")
            print()
            self._browser_mgr.wait_for_human(
                "Finish logging in via the browser, then press Enter"
            )

        # ── Verify Login Success ─────────────────────────────────────────
        self._browser_mgr.random_delay(1, 2)

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        current_url = page.url.lower()
        if any(kw in current_url for kw in ("signin", "login")):
            print("  ❌  Still on login page — login may have failed")
            self._browser_mgr.screenshot(page, "login_failed")
            return False

        print("  ✅  Login successful!")
        self._browser_mgr.screenshot(page, "login_success")
        return True

    # ── Account Discovery ─────────────────────────────────────────────────

    def _discover_accounts(self, page) -> list[dict]:
        """Find all accounts on the dashboard.

        Returns a list of dicts with 'name', 'type', 'url' keys.
        """
        accounts = []

        try:
            # Navigate to accounts/dashboard
            self._browser_mgr.safe_goto(
                page, NFCU_URLS["dashboard"],
                timeout=NFCU_TIMEOUTS["dashboard_load"]
            )
            page.wait_for_load_state("networkidle", timeout=20000)
            self._browser_mgr.random_delay(2, 4)

            self._browser_mgr.screenshot(page, "dashboard")

            # Strategy 1: Look for account links
            links = page.query_selector_all(
                NFCU_SELECTORS["account_links"]
            )

            if links:
                for link in links:
                    name = link.inner_text().strip()
                    href = link.get_attribute("href") or ""
                    if name and len(name) > 2:
                        accounts.append({
                            "name": name,
                            "type": self._guess_account_type(name),
                            "url": href,
                            "element": link,
                        })

            # Strategy 2: If no links found, try to find account containers
            # by looking for text patterns
            if not accounts:
                log.info("No account links found via selector, trying text search")

                # Look for common account type keywords in the page
                page_text = page.inner_text("body")
                known_types = [
                    "Checking", "Savings", "Credit Card",
                    "Auto Loan", "Mortgage", "Money Market",
                ]

                for acct_type in known_types:
                    if acct_type.lower() in page_text.lower():
                        accounts.append({
                            "name": acct_type,
                            "type": acct_type.lower(),
                            "url": "",
                            "element": None,
                        })

            # Strategy 3: Let the user tell us
            if not accounts:
                print("\n  ⚠  Could not auto-detect accounts.")
                print("       Screenshot saved to screenshots/")
                self._browser_mgr.screenshot(page, "no_accounts_detected")
                self._browser_mgr.wait_for_human(
                    "Navigate to an account in the browser, then press Enter"
                )
                # After manual navigation, add a placeholder
                accounts.append({
                    "name": "Manual",
                    "type": "unknown",
                    "url": page.url,
                    "element": None,
                })

        except Exception as e:
            log.error("Account discovery failed: %s", e)
            self._browser_mgr.screenshot(page, "discovery_error")

        # Remove duplicates
        seen = set()
        unique = []
        for a in accounts:
            key = a["name"].lower()
            if key not in seen:
                seen.add(key)
                unique.append(a)

        return unique

    @staticmethod
    def _guess_account_type(name: str) -> str:
        """Guess account type from its display name."""
        name_lower = name.lower()
        if "check" in name_lower:
            return "checking"
        if "saving" in name_lower:
            return "savings"
        if "credit" in name_lower:
            return "credit_card"
        if "auto" in name_lower or "car" in name_lower:
            return "auto_loan"
        if "mortgage" in name_lower or "mrtg" in name_lower:
            return "mortgage"
        if "money market" in name_lower:
            return "money_market"
        return "other"

    # ── Transaction Download ──────────────────────────────────────────────

    def _download_transactions(self, page, account: dict) -> pathlib.Path | None:
        """Navigate to an account and download its transaction CSV.

        Returns the path to the downloaded file, or None if download failed.
        """
        # Navigate to account if we have a URL
        if account.get("url"):
            full_url = account["url"]
            if not full_url.startswith("http"):
                full_url = f"https://digitalomni.navyfederal.org{full_url}"

            self._browser_mgr.safe_goto(
                page, full_url,
                timeout=NFCU_TIMEOUTS["account_load"]
            )
        elif account.get("element"):
            try:
                account["element"].click()
            except Exception:
                log.warning("Could not click account element for %s", account["name"])

        self._browser_mgr.random_delay(2, 4)

        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass

        self._browser_mgr.screenshot(page, f"account_{account['name']}")

        # Look for the download button
        download_found = self._browser_mgr.wait_for_element(
            page, NFCU_SELECTORS["download_btn"],
            timeout=NFCU_TIMEOUTS["account_load"]
        )

        if not download_found:
            print(f"  ⚠  No download button found for {account['name']}")
            self._browser_mgr.screenshot(page, f"no_download_{account['name']}")

            self._browser_mgr.wait_for_human(
                f"Navigate to {account['name']} transaction history and "
                f"click Download → CSV, then press Enter"
            )

            # Check if a file was downloaded
            downloads = self._browser_mgr.list_downloads()
            if downloads:
                return downloads[-1]
            return None

        # Click download and wait for file
        def click_download():
            # Try to click the download button
            for selector in NFCU_SELECTORS["download_btn"].split(", "):
                try:
                    btn = page.query_selector(selector.strip())
                    if btn and btn.is_visible():
                        btn.click()
                        return
                except Exception:
                    continue

            # Fallback: click first visible download-like button
            page.click(NFCU_SELECTORS["download_btn"].split(",")[0].strip())

        # Some download flows have an intermediate dialog for format selection
        csv_path = self._browser_mgr.wait_for_download(
            page, click_download,
            timeout=NFCU_TIMEOUTS["download"]
        )

        if not csv_path:
            # Maybe there's a format selection dialog
            self._browser_mgr.random_delay(1, 2)

            csv_btn = page.query_selector(NFCU_SELECTORS["csv_option"])
            if csv_btn:
                csv_path = self._browser_mgr.wait_for_download(
                    page, lambda: csv_btn.click(),
                    timeout=NFCU_TIMEOUTS["download"]
                )

        if not csv_path:
            # Last resort: ask human
            self._browser_mgr.wait_for_human(
                f"Please download {account['name']} transactions as CSV "
                f"manually, then press Enter"
            )
            downloads = self._browser_mgr.list_downloads()
            if downloads:
                csv_path = downloads[-1]

        return csv_path

    # ── CSV Parsing ───────────────────────────────────────────────────────

    def _parse_csv(self, path: pathlib.Path,
                   account: dict) -> pd.DataFrame | None:
        """Parse a downloaded NFCU CSV file into a standardized DataFrame.

        Uses the existing load_nfcu() function from loaders.py.
        """
        try:
            from loaders import load_nfcu
            df = load_nfcu(path, "Navy Federal", account["name"])
            return df
        except Exception as e:
            log.error("Failed to parse %s: %s", path.name, e)
            return None

    # ── Utility ───────────────────────────────────────────────────────────

    def _try_fill_field(self, page, selector: str, value: str,
                        field_name: str) -> bool:
        """Try to fill a form field, handling multiple possible selectors.

        Returns True if the field was found and filled.
        """
        for sel in selector.split(", "):
            sel = sel.strip()
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    self._browser_mgr.type_like_human(page, sel, value)
                    log.debug("Filled %s via selector: %s", field_name, sel)
                    return True
            except Exception:
                continue

        log.warning("Could not fill %s (tried all selectors)", field_name)
        return False

    def _try_click(self, page, selector: str, button_name: str) -> bool:
        """Try to click a button, handling multiple possible selectors.

        Returns True if a button was found and clicked.
        """
        for sel in selector.split(", "):
            sel = sel.strip()
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.click()
                    log.debug("Clicked %s via selector: %s", button_name, sel)
                    return True
            except Exception:
                continue

        log.warning("Could not click %s (tried all selectors)", button_name)
        return False
