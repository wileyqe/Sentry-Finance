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


class ChaseDownloadMixin:
    """Mixin extracted from ChaseConnector: _download_mixin methods."""

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
            self._screenshot(page, f"before_direct_form_{acct.last4}", error_only=True)
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

        self._screenshot(page, f"account_{acct.last4}", error_only=True)
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

        self._screenshot(page, f"download_form_{acct.last4}", error_only=True)

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

        self._screenshot(page, f"download_form_direct_{acct.last4}", error_only=True)
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
            el = resilient_find(page, nav_group, timeout=3, allow_ai=False)
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
                        log.info("Navigated to account via registry")
                        return True
                except Exception as e:
                    log.debug("Registry click failed: %s", e)

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
                log.info("Navigated to account via JS fallback")
                return True
        except Exception as e:
            log.debug("JS fallback failed: %s", e)

        # Strategy 3: Credit card accounts don't appear as individual tiles
        # on the main dashboard — they're grouped under a summary section.
        # The left nav has a "Credit cards" link that navigates the SPA to
        # show individual card tiles where last4 is visible.
        if acct.type in ("credit_card", "credit"):
            log.info(
                "[%s] Clicking 'Credit cards' nav link",
                self.institution,
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
