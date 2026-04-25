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


class NFCUDownloadMixin:
    """Mixin extracted from NFCUConnector: _download_mixin methods."""

    def _download_account_csv(self, page, acct: AccountConfig) -> Path | None:
        """Navigate to an account and download its transaction CSV."""
        print(f"\n       [{acct.last4}] {acct.name}...")

        # Navigate to the account page
        self._ensure_overview_page(page)
        if not self._click_account(page, acct):
            print(f"       ✗ Could not find account link for {acct.last4}")
            print(f"         → Navigate manually, then press ENTER")
            input()

        # Wait for account detail page
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception as e:
            log.debug("Wait timed out: %s", e)
        self._human_jitter()

        self._screenshot(page, f"account_{acct.last4}", error_only=True)

        # ── Find and click Download/Export ────────────────────────────
        # 1. Dismiss any existing popups/modals (e.g. "Transfer" or "Offer" details)
        self._dismiss_popups(page)

        download_selectors = [
            'button:has-text("Download")',
            'a:has-text("Download")',
            'button:has-text("Export")',
            'a:has-text("Export")',
            'button[aria-label*="download" i]',
            'button[aria-label*="export" i]',
            '[data-testid="download-transactions"]',
        ]

        download_btn = None
        for sel in download_selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    download_btn = el
                    print(f"       ✔ Found download button: {sel}")
                    break
            except Exception:
                continue

        if not download_btn:
            print(f"       ✗ No download button found")
            # Dump diagnostics to help debug why
            self._dump_page_diagnostics(page)
            print(f"         → Click Download/Export → CSV in the browser,")
            print(f"           then press ENTER")
            input()
            return self._find_latest_download()

        # Click download and capture the file
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            target_name = f"{acct.last4}_{ts}.csv"
            target_path = self._export_dir / target_name

            # Handle both direct download and "Select Format" dialog flows
            with page.expect_download(timeout=15000) as dl_info:
                download_btn.click()

                # Check if a CSV option appears (format selection dialog/dropdown)
                # Polling loop to catch the menu if it appears
                csv_selectors = [
                    "text=/^CSV$/i",  # Strict text match
                    'label:text-is("CSV")',  # Strict label
                    'input[value="csv" i]',
                    '[data-testid="csv-option"]',
                    'button:has-text("CSV")',  # Fallback
                ]

                # Brief poll (approx 3s)
                for _ in range(6):
                    found_csv = False
                    for sel in csv_selectors:
                        try:
                            el = page.query_selector(sel)
                            if el and el.is_visible():
                                print(f"       → CSV option found: {sel}")
                                el.click()
                                found_csv = True
                                break
                        except Exception as e:
                            log.debug("Ignored exception: %s", e)
                    if found_csv:
                        break
                    page.wait_for_timeout(500)

            download = dl_info.value
            download.save_as(str(target_path))
            print(f"       ✔ Downloaded: {target_name}")
            return target_path

        except Exception as e:
            print(f"       ⚠ Download failed ({e})")

            # Last resort: manual
            print(f"       ✗ Auto-download failed for {acct.last4}")
            # Check for popups again (maybe the click triggered one)
            self._dismiss_popups(page)
            print(f"         → Download CSV manually, then press ENTER")
            input()
            return self._find_latest_download()

    def _try_csv_format_dialog(self, page, acct: AccountConfig) -> Path | None:
        """Handle intermediate format selection dialogs (CSV/QFX/OFX)."""
        csv_selectors = [
            'text="CSV"',
            'label:has-text("CSV")',
            'input[value="csv"]',
            'button:has-text("CSV")',
            '[data-testid="csv-option"]',
            'text="Comma Separated"',
        ]

        for sel in csv_selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    target_name = f"{acct.last4}_{ts}.csv"
                    target_path = self._export_dir / target_name

                    with page.expect_download(timeout=30000) as dl_info:
                        el.click()

                    download = dl_info.value
                    download.save_as(str(target_path))
                    print(f"       ✔ Downloaded (format dialog): {target_name}")
                    return target_path
            except Exception:
                continue
        return None

    def _human_jitter(self, min_sec: float = 0.8, max_sec: float = 2.5):
        """Sleep for a random interval to disguise precise robotic cadences."""
        time.sleep(random.uniform(min_sec, max_sec))

    def _dismiss_popups(self, page):
        """Dismiss common popups using selectors from the registry."""
        reg = load_selectors()
        popup_group = get_selector_group(reg, "nfcu.popups.dismiss")
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

        # Also try pressing Escape
        try:
            page.keyboard.press("Escape")
        except Exception as e:
            log.debug("Ignored exception: %s", e)

        if dismissed == 0:
            log.debug("No popups found")

    def _ensure_overview_page(self, page):
        """Navigate back to the accounts overview page.

        Uses the dashboard URL captured after login instead of hardcoded
        paths, because direct URL access to digitalomni may return 404.
        """
        # Dismiss any popups that might block navigation/visibility
        self._dismiss_popups(page)

        url = page.url.lower().split("?")[0]  # Ignore query params
        dashboard = getattr(self, "_dashboard_url", "").lower().split("?")[0]

        # If we're already on the dashboard URL, we're good
        if dashboard and url == dashboard:
            log.info("Already on dashboard URL: %s", url)
            return

        log.info("Returning to Accounts Overview...")

        # Use the centralized selector registry for nav-back selectors
        reg = load_selectors()
        nav_group = get_selector_group(reg, "nfcu.overview.nav_back")
        if nav_group:
            # We don't want the AI to stall the pipeline for 15s if the nav-back
            # button isn't immediately visible, but we should give the page time to load
            el = resilient_find(page, nav_group, timeout=15, allow_ai=False)
            if el:
                try:
                    el.scroll_into_view_if_needed()
                    el.click()
                    log.info("Clicked nav-back via registry")
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception as e:
                        log.debug("Nav-back load state wait timed out: %s", e)
                    return
                except Exception as e:
                    log.debug("Nav-back click failed: %s", e)

        # Fallback: Navigate to captured dashboard URL (not export_url!)
        fallback = getattr(self, "_dashboard_url", None) or self.export_url
        log.warning("UI navigation failed, navigating to %s", fallback)
        page.goto(fallback, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception as e:
            log.debug("Wait timed out: %s", e)

        self._human_jitter(0.5, 1.5)

    def _click_account(self, page, acct: AccountConfig) -> bool:
        """Click on an account link using the selector registry.

        NFCU renders accounts as 'Account Name - LAST4' (dash-separated).
        Template variables {name} and {last4} are expanded by ai_backstop.
        """
        reg = load_selectors()
        acct_group = get_selector_group(reg, "nfcu.overview.account_link")
        template_vars = {"name": acct.name, "last4": acct.last4}

        if acct_group:
            # Prevent AI fallback delay if account isn't visible right away, but allow 15s for SPA router to render
            el = resilient_find(
                page,
                acct_group,
                template_vars=template_vars,
                timeout=15,
                allow_ai=False,
            )
            if el:
                try:
                    el.click()
                    log.info("Navigated to account via registry")
                    return True
                except Exception as e:
                    log.debug("Registry click failed: %s", e)

        # Fallback: find via JavaScript — look for links containing the last4
        try:
            clicked = page.evaluate(f"""() => {{
                const links = document.querySelectorAll('a');
                for (const a of links) {{
                    if (a.textContent.includes('{acct.last4}')) {{
                        a.click();
                        return true;
                    }}
                }}
                return false;
            }}""")
            if clicked:
                log.info("Navigated to account via JS fallback")
                return True
        except Exception as e:
            log.debug("Ignored exception: %s", e)

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
            accts = self._load_accounts()
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

        out = self._export_dir / "nfcu_page_diagnostics.json"
        out.write_text(json.dumps(diag, indent=2))
        log.info("Page diagnostics saved to %s", out)
