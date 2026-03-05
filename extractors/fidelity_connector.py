"""
extractors/fidelity_connector.py — Fidelity CSV-download connector.

Automates:
  1. Login → manual TOTP MFA approval
  2. Download transaction-history CSV from Activity & Orders
  3. Download positions-snapshot CSV from Positions page
  4. Run the existing ingest pipeline to rebuild daily ledger + persist to DB

This connector deliberately avoids DOM-based balance scraping.
All data comes from the two CSV exports that Fidelity provides natively.
"""

import logging
import sys
from datetime import date
from pathlib import Path

from playwright.sync_api import Page

from extractors.ai_backstop import (
    get_selector_group,
    load_selectors,
    resilient_click,
    resilient_find,
)
from skills.institution_connector import AccountConfig, InstitutionConnector

log = logging.getLogger("sentry.extractors.fidelity")

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "raw_exports" / "fidelity"


class FidelityConnector(InstitutionConnector):
    """Fidelity brokerage — CSV download automation."""

    # ── Identity ──────────────────────────────────────────────────────────

    @property
    def institution(self) -> str:
        return "fidelity"

    @property
    def display_name(self) -> str:
        return "Fidelity"

    @property
    def login_url(self) -> str:
        return "https://digital.fidelity.com/prgw/digital/login/full-page"

    @property
    def export_url(self) -> str:
        return "https://digital.fidelity.com/ftgw/digital/portfolio/activity"

    # ── Login ─────────────────────────────────────────────────────────────

    def _perform_login(self, page: Page, credentials: dict | None = None) -> bool:
        """Navigate to Fidelity login and authenticate.

        Two credential paths:
          A) Broker credentials → fill username/password → submit
          B) Password Manager autofill → wait for fields to be filled → submit
        """
        reg = load_selectors()

        # Navigate to login page
        print("  🌐  Navigating to Fidelity login...")
        page.goto(self.login_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)

        self._screenshot(page, "login_page", error_only=True)

        # ── Path A: Broker credentials ────────────────────────────────
        if credentials and credentials.get("username") and credentials.get("password"):
            print("  🔑  Filling credentials from broker...")

            # Fill username
            username_group = get_selector_group(reg, "fidelity.login.username")
            if username_group:
                el = resilient_find(page, username_group, timeout=5)
                if el:
                    el.click()
                    page.wait_for_timeout(300)
                    el.fill(credentials["username"])
                    print("       ✔ Username filled")
                else:
                    log.warning("[fidelity] Could not find username field")
                    return False

            # Fill password
            password_group = get_selector_group(reg, "fidelity.login.password")
            if password_group:
                el = resilient_find(page, password_group, timeout=2)
                if el:
                    el.click()
                    page.wait_for_timeout(300)
                    el.fill(credentials["password"])
                    print("       ✔ Password filled")
                else:
                    log.warning("[fidelity] Could not find password field")
                    return False

            # Submit
            submit_group = get_selector_group(reg, "fidelity.login.submit")
            if submit_group:
                page.wait_for_timeout(500)
                resilient_click(page, submit_group, allow_ai=False)
                print("  ✔  Login submitted (broker)")

            page.wait_for_timeout(3000)
            self._screenshot(page, "after_submit", error_only=True)
            return True  # MFA handled by lifecycle

        # ── Path B: Password Manager autofill ─────────────────────────
        print("  ⏳  Waiting for Password Manager autofill...")

        # Wait for the username field to be filled by Password Manager
        username_group = get_selector_group(reg, "fidelity.login.username")
        if username_group and username_group.get("selectors"):
            primary = username_group["selectors"][0]
            try:
                page.wait_for_function(
                    f"""() => {{
                        const el = document.querySelector('{primary}');
                        return el && el.value && el.value.length > 0;
                    }}""",
                    timeout=30000,
                )
                print("       ✔ Username autofilled")
            except Exception:
                log.warning("[fidelity] Autofill timed out — fallback to manual")

        # Give Password Manager a moment for the password field
        page.wait_for_timeout(2000)

        # Submit
        submit_group = get_selector_group(reg, "fidelity.login.submit")
        if submit_group:
            resilient_click(page, submit_group, allow_ai=False)
            print("  ✔  Login submitted (autofill)")

        page.wait_for_timeout(3000)
        self._screenshot(page, "after_submit", error_only=True)
        return True

    # ── Post-login detection ──────────────────────────────────────────────

    def _is_post_login(self, page: Page) -> bool:
        """Detect whether the user has completed authentication.

        Fidelity post-login redirects to the portfolio summary page.
        """
        url = page.url.lower()
        # Still on login / MFA page → not done
        if any(
            kw in url
            for kw in ["login", "logon", "authenticate", "mfa", "verify", "otp"]
        ):
            return False
        # Landed on portfolio/summary/activity → authenticated
        if any(kw in url for kw in ["portfolio", "summary", "account", "activity"]):
            return True
        # Catch-all: check if login form is gone
        try:
            has_login = page.query_selector('input[type="password"]')
            if has_login and has_login.is_visible():
                return False
        except Exception:
            pass
        return True

    # ── Export ─────────────────────────────────────────────────────────────

    def _trigger_export(self, page: Page, accounts: list[AccountConfig]) -> list[Path]:
        """Download Fidelity activity CSV and run the ingest pipeline.

        Activity-only model:
          1. Download History CSV (captures all buys/sells/dividends)
          2. Run ingest pipeline (derives positions from baseline + deltas,
             values at yfinance previous-close)

        No positions download needed — holdings are fully derivable from
        the initial ingestion baseline + subsequent activity.
        """
        downloaded_files = []

        RAW_DIR.mkdir(parents=True, exist_ok=True)
        reg = load_selectors()

        # ── Phase 1: Download transaction history CSV ─────────────────
        print("\n  ── Phase 1: Transaction History CSV ──")
        history_path = self._download_history_csv(page, reg)
        if history_path:
            downloaded_files.append(history_path)

        # ── Phase 2: Run ingest (baseline + deltas + yfinance close) ──
        if downloaded_files:
            print("\n  ── Phase 2: Incremental Ingest ──")
            self._run_ingest(downloaded_files)

        return downloaded_files

    def _download_history_csv(self, page: Page, reg: dict) -> Path | None:
        """Navigate to Activity & Orders and download the history CSV.

        Fidelity's Activity page has a download icon (↓) in the top-right
        that opens a dropdown/popover with a "Download as CSV" option.
        Two clicks are needed: icon → menu item.
        """

        # Navigate to Activity & Orders page
        print("  📍  Navigating to Activity & Orders...")
        page.goto(self.export_url, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            log.debug("[fidelity] networkidle timed out, continuing")

        page.wait_for_timeout(3000)
        self._screenshot(page, "activity_page", error_only=True)

        # Click the "History" sub-tab to show full history instead of just "Past 30 days"
        try:
            history_tab = page.query_selector('button:has-text("History")')
            if history_tab and history_tab.is_visible():
                history_tab.click()
                page.wait_for_timeout(2000)
                print("       ✔ Switched to History tab")
        except Exception as e:
            log.debug("[fidelity] Could not click History tab: %s", e)

        # Step 1: Click the download icon to open the dropdown
        download_group = get_selector_group(reg, "fidelity.activity.download_icon")
        if download_group:
            el = resilient_find(page, download_group, timeout=5)
            if el:
                el.click()
                page.wait_for_timeout(1500)
                print("       ✔ Download menu opened")
            else:
                log.warning("[fidelity] Download icon not found on Activity page")
                self._screenshot(page, "no_download_icon")
                return None
        else:
            # Fallback: try the icon selectors directly
            for sel in [
                '[aria-label*="download" i]',
                '[aria-label*="export" i]',
                'button:has-text("Download")',
            ]:
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        page.wait_for_timeout(1500)
                        print("       ✔ Download menu opened (fallback)")
                        break
                except Exception:
                    continue
            else:
                log.warning("[fidelity] Could not find download icon")
                self._screenshot(page, "no_download_icon")
                return None

        # Step 2: Click "Download as CSV" in the dropdown menu
        csv_selectors = [
            'text="Download as CSV"',
            'a:has-text("Download as CSV")',
            'button:has-text("Download as CSV")',
            'text="Download"',
            'a:has-text("Download")',
            'button:has-text("Download")',
            '[role="menuitem"]:has-text("Download")',
            '[role="menuitem"]:has-text("CSV")',
        ]
        dest_filename = f"History_for_Account_{date.today().strftime('%Y')}.csv"

        for sel in csv_selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    with page.expect_download(timeout=30000) as download_info:
                        el.click()
                    download = download_info.value
                    dest = RAW_DIR / dest_filename
                    download.save_as(str(dest))
                    print(f"       ✔ Saved: {dest.name}")
                    return dest
            except Exception as e:
                log.debug("[fidelity] CSV selector '%s' failed: %s", sel, e)
                continue

        log.warning("[fidelity] Could not click CSV download option in dropdown")
        self._screenshot(page, "no_csv_option")
        return None

    # ── Ingest ────────────────────────────────────────────────────────────

    def _run_ingest(self, downloaded_files: list[Path]) -> None:
        """Run the existing Fidelity ingest pipeline on the new CSV data.

        Reuses ingest_fidelity_history.py's parsing and DB persistence logic.
        """
        # Add project root to sys.path for the ingest script imports
        if str(BASE_DIR) not in sys.path:
            sys.path.insert(0, str(BASE_DIR))

        try:
            from scripts.ingest_fidelity_history import (
                load_all_data,
                reconstruct_daily_ledger,
                fetch_market_data,
                generate_outputs,
                persist_to_db,
            )

            print("  🔄  Running ingest pipeline...")

            # Step 1: Parse CSVs (the script auto-discovers files in raw_exports/fidelity/)
            txns, positions = load_all_data()

            # Step 2: Reconstruct daily ledger
            daily_df, equity_syms = reconstruct_daily_ledger(txns, positions)

            # Step 3: Fetch yfinance market data
            market_df, actions_df = fetch_market_data(equity_syms)

            # Step 4: Generate output CSVs
            snapshot = generate_outputs(daily_df, market_df, actions_df, equity_syms)

            # Step 5: Persist SPAXX cash balance to SQLite
            persist_to_db(snapshot)

            # Store the cash balance as our connector balance result
            if not snapshot.empty:
                last_row = snapshot.iloc[-1]
                cash = float(last_row["Cash_Balance"])
                total = float(last_row["Total_Account_Value"])
                self._result_balances["0827"] = {
                    "name": "Individual Brokerage",
                    "balance": f"${total:,.2f}",
                }
                print(
                    f"  ✅  Ingest complete — Total: ${total:,.2f} (Cash: ${cash:,.2f})"
                )

        except Exception as e:
            log.exception("[fidelity] Ingest pipeline failed: %s", e)
            print(f"  ⚠   Ingest pipeline error: {e}")

    # ── Logout ────────────────────────────────────────────────────────────

    def _perform_logout(self, page: Page) -> None:
        """Log out of Fidelity.

        From the live screenshot: 'Log Out' is a direct link in the top
        navigation bar — no profile-menu click needed.
        """
        reg = load_selectors()

        # Try the direct "Log Out" link first (visible in top nav)
        signout_group = get_selector_group(reg, "fidelity.logout.signout_link")
        if signout_group:
            clicked = resilient_click(page, signout_group, allow_ai=False)
            if clicked:
                print("  🚪  Logged out of Fidelity")
                page.wait_for_timeout(2000)
                return

        # Fallback: try via profile menu
        profile_group = get_selector_group(reg, "fidelity.logout.profile_menu")
        if profile_group:
            clicked = resilient_click(page, profile_group, allow_ai=False)
            if clicked:
                page.wait_for_timeout(1500)
                if signout_group:
                    resilient_click(page, signout_group, allow_ai=False)
                    print("  🚪  Logged out of Fidelity (via profile menu)")
                    page.wait_for_timeout(2000)
                    return

        # Last resort: navigate to the logout URL directly
        log.info("[fidelity] Fallback: navigating to logout URL")
        try:
            page.goto(
                "https://login.fidelity.com/ftgw/Fas/Fidelity/RtlCust/Logout/Init",
                wait_until="domcontentloaded",
                timeout=15000,
            )
            print("  🚪  Logged out via direct URL")
        except Exception as e:
            log.warning("[fidelity] Logout navigation failed: %s", e)
