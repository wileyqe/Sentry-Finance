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


class ChaseBalancesMixin:
    """Mixin extracted from ChaseConnector: _balances_mixin methods."""

    def _trigger_export(self, page, accounts: list[AccountConfig]) -> list[Path]:
        """Execute the full Chase export process."""

        downloaded_files = []
        self._account_ids: dict[str, str] = {}  # last4 -> internal Chase account ID

        # Randomize the processing order to defeat behavioral footprinting
        # of traversing accounts in the exact same array sequence every time.
        accounts = list(accounts)  # clone the list
        random.shuffle(accounts)

        # Capture the dashboard URL — this is where we land post-login.
        self._dashboard_url = page.url
        print(f"  📍  Dashboard URL: {self._dashboard_url}")

        # Intercept Chase API responses to discover internal account IDs.
        # Chase's SPA fetches account data via XHR; we capture last4 -> ID mapping.
        def _on_response(response):
            try:
                url = response.url
                if (
                    "gateway.chase.com" in url
                    or "api.chase.com" in url
                    or "accountSummary" in url
                    or "/accounts" in url
                ):
                    try:
                        body = response.json()
                        self._extract_account_ids(body)
                    except Exception as e:
                        log.debug("Ignored exception: %s", e)
            except Exception as e:
                log.debug("Ignored exception: %s", e)

        page.on("response", _on_response)

        # Wait for the SPA to render account content.
        # Chase uses client-side rendering; the page body may be empty
        # for several seconds after navigation.
        self._wait_for_dashboard_content(page)

        # Give API calls a moment to complete
        page.wait_for_timeout(2000)
        page.remove_listener("response", _on_response)

        if self._account_ids:
            log.info(
                "[chase] Discovered %d account IDs via network",
                len(self._account_ids),
            )
        else:
            log.info("[chase] No account IDs via network — will use DOM navigation")

        self._screenshot(page, "dashboard", error_only=True)

        # Diagnostic: dump page structure to help debug selectors
        self._dump_page_diagnostics(page)

        # ── Phase 1: Balances ────────────────────────────────────────
        balance_accounts = [a for a in accounts if a.balance]
        if balance_accounts:
            print(f"\n  ── Phase 1: Balances ({len(balance_accounts)} accounts) ──")
            self._scrape_balances(page, balance_accounts)

        # ── Phase 2: Transaction CSVs ────────────────────────────────
        txn_accounts = [a for a in accounts if a.transactions]
        if txn_accounts:
            print(f"\n  ── Phase 2: Transactions ({len(txn_accounts)} accounts) ──")
            for acct in txn_accounts:
                csv_path = self._download_account_csv(page, acct)
                if csv_path:
                    downloaded_files.append(csv_path)

        # ── Phase 3: Account Details ─────────────────────────────────
        detail_accounts = [a for a in accounts if a.wants_loan_details]
        if detail_accounts:
            print(
                f"\n  ── Phase 3: Account Details ({len(detail_accounts)} accounts) ──"
            )
            for acct in detail_accounts:
                try:
                    self._scrape_account_details(page, acct)
                except Exception as e:
                    log.warning("[chase] Detail scrape failed for an account: %s", e)

        # ── Phase 4: Credit Score ────────────────────────────────────
        if any(getattr(a, 'wants_credit_score', False) for a in accounts):
            print("\n  ── Phase 4: Credit Score ──")
            try:
                self._scrape_credit_score(page)
            except Exception as e:
                log.warning("[%s] Credit score phase failed: %s", self.institution, e)

        return downloaded_files

    def _extract_account_ids(self, data, depth: int = 0):
        """Recursively search a JSON response for account last4 -> ID mappings."""
        if depth > 6 or not data:
            return
        if isinstance(data, dict):
            acct_id = (
                data.get("accountId") or data.get("id") or data.get("accountNumber")
            )
            last4 = None
            for key in (
                "last4",
                "lastFour",
                "maskedAccountNumber",
                "accountNumberLast4",
                "displayAccountNumber",
            ):
                val = data.get(key, "")
                if val and len(str(val)) >= 4:
                    last4 = str(val)[-4:]
                    break
            if acct_id and last4 and last4.isdigit():
                self._account_ids[last4] = str(acct_id)
            for v in data.values():
                self._extract_account_ids(v, depth + 1)
        elif isinstance(data, list):
            for item in data:
                self._extract_account_ids(item, depth + 1)

    def _scrape_balances(self, page, accounts: list[AccountConfig]):
        """Scrape balance values from the Chase dashboard."""
        self._ensure_overview_page(page)

        # Scroll to the bottom and back to trigger lazy-loaded tiles
        # (credit card tiles like Slate Edge load after the fold)
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1000)
        except Exception as e:
            log.debug("Ignored exception: %s", e)

        for acct in accounts:
            balance, avail_credit = self._find_balance(page, acct)
            if balance is not None:
                result = {
                    "name": acct.name,
                    "last4": acct.last4,
                    "type": acct.type,
                    "balance": balance,
                    "scraped_at": datetime.now().isoformat(),
                }
                if avail_credit:
                    result["available_credit"] = avail_credit
                self._result_balances[acct.last4] = result

                credit_info = f" (avail credit: {avail_credit})" if avail_credit else ""
                print(f"       ✔ [{acct.last4}] {acct.name}: {balance}{credit_info}")
            else:
                print(f"       ✗ [{acct.last4}] {acct.name}: balance not found")

    def _find_balance(self, page, acct: AccountConfig) -> tuple[str | None, str | None]:
        """Find the balance (and available credit) for an account.

        Uses JavaScript to extract the innerHTML of all account tiles,
        then uses Python regex to find the matching last4 and extract
        the associated balance. This bypasses issues where checking account
        names are hidden inside Shadow DOMs (<mds-button text="...XXXX">).
        """
        try:
            # Extract raw HTML from all account tiles
            tiles_html = page.evaluate("""() => {
                const tiles = Array.from(document.querySelectorAll('[data-testid="accountTile"]'));
                return tiles.map(t => t.innerHTML);
            }""")

            for html in tiles_html:
                # Check if this tile belongs to the target account
                if acct.last4 not in html:
                    continue

                # Fallback: Sometimes Chase puts the balance in a sibling tile or slightly different format.
                # However, the standard `accountTile` wraps the whole row.

                # Extract the primary balance
                balance_match = re.search(r"\$[\d,]+\.\d{2}", html)
                balance = balance_match.group(0) if balance_match else None

                # Extract available credit if present
                avail_credit = None
                credit_match = re.search(
                    r"(\$[\d,]+\.\d{2})\s*Available credit", html, re.IGNORECASE
                )
                if credit_match:
                    avail_credit = credit_match.group(1)
                elif "Available credit" in html:
                    # Look for the last dollar amount in the HTML if the structure changed
                    amounts = re.findall(r"\$[\d,]+\.\d{2}", html)
                    if len(amounts) >= 2:
                        avail_credit = amounts[-1]

                if balance:
                    log.info(
                        "[%s] Regex found tile for %s: balance=%s",
                        self.institution,
                        acct.last4,
                        balance,
                    )
                    return balance, avail_credit

            log.warning(
                "[%s] Could not find account tile containing %s",
                self.institution,
                acct.last4,
            )

        except Exception as e:
            print(f"       ⚠ Error finding balance for {acct.last4}: {e}")

        return None, None

    def _scrape_account_details(self, page, acct: AccountConfig):
        """Navigate to the Account Details sub-view for an account and
        extract configured detail fields via regex on ``inner_text``.

        Checking accounts reach the view via a left-rail "More" → "Account
        details" dropdown; credit cards expose it as a direct link/tab on
        the card page. The credit-card view also render-lags its tooltip
        `<a>` labels ("Total credit limit", "Available credit"), so an
        extra hydration wait is used for ``type == 'credit'``.
        """
        print(f"\n       [{acct.last4}] Account details for {acct.name}...")

        self._ensure_overview_page(page)
        if not self._click_account(page, acct):
            print(f"       ✗ Could not find account tile for {acct.last4}")
            return

        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception as e:
            log.debug("Wait timed out: %s", e)
        self._human_jitter()

        # Land on the detail sub-URL if we're still on the activity view
        if "/details/" not in page.url and "/accountDetails/" not in page.url:
            self._navigate_to_account_details(page)

        # CC details hydrate their `<a>`-wrapped labels late — wait for a
        # stable anchor before reading body text.
        if acct.type == "credit":
            try:
                page.wait_for_selector(
                    "a:has-text('Total credit limit'), "
                    "a:has-text('Available credit'), "
                    "*:has-text('Purchase APR')",
                    timeout=5000,
                )
            except Exception as e:
                log.debug("[chase] CC hydration anchor not found: %s", e)

        self._screenshot(page, f"detail_{acct.last4}", error_only=True)

        page_text = page.inner_text("body")
        dump_path = self._export_dir / f"chase_detail_page_text_{acct.last4}.txt"
        dump_path.write_text(page_text, encoding="utf-8")
        log.info("Chase detail page text dumped to %s", dump_path)

        field_patterns = {
            # ── Deposit fields (checking) ────────────────────────────
            "available_balance": [r"Available\s+balance"],
            "present_balance": [r"Present\s+balance"],
            # Chase labels APY as "Interest rate" on deposit accounts;
            # keep generic aliases as fallbacks. Value is a percentage.
            "apy": [r"Interest\s+rate", r"APY", r"Annual\s+Percentage\s+Yield"],
            # Label carries a dynamic year (e.g. "Interest in 2026"), so
            # the pattern must not pin it.
            "ytd_interest": [
                r"Interest\s+in\s+\d{4}",
                r"YTD\s+Interest",
                r"Interest\s+YTD",
            ],
            "last_statement_date": [r"Last\s+statement\s+date"],
            # ── Credit-card fields ───────────────────────────────────
            "purchase_apr": [r"Purchase\s+APR", r"Interest\s+Rate"],
            "cash_advance_apr": [r"Cash\s+advance\s+APR"],
            "credit_limit": [r"Total\s+credit\s+limit", r"Credit\s+Limit"],
            # Word boundary prevents accidental match on
            # "Available for cash advance".
            "available_credit": [r"\bAvailable\s+credit\b"],
            "cash_advance_limit": [r"Cash\s+advance\s+limit"],
            "cash_advance_available": [r"Available\s+for\s+cash\s+advance"],
            "cash_advance_balance": [r"Cash\s+advance\s+balance"],
            "minimum_payment": [r"Minimum\s+payment"],
            # Value-first: the "Minimum payment" line carries both the
            # amount and the due date — "$X.XX is due on <Month Day, Year>".
            # Pull the date directly via capture group.
            "payment_due_date": [
                r"\$[\d,]+\.\d{2}\s+is\s+due\s+on\s+"
                r"([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})",
            ],
            "statement_balance": [r"Balance\s+on\s+last\s+statement"],
            "remaining_statement_balance": [r"Remaining\s+statement\s+balance"],
            "next_closing_date": [r"Next\s+closing\s+date"],
            "last_payment": [r"Last\s+payment"],
            "automatic_payments": [r"Automatic\s+Payments?"],
        }

        details = {}
        for field_name in acct.loan_details:
            patterns = field_patterns.get(
                field_name, [field_name.replace("_", r"\s+")]
            )
            value = self._extract_field_value(page_text, patterns)
            if value:
                details[field_name] = value
                print(f"       ✔ {field_name}: {value}")
            else:
                details[field_name] = None
                print(f"       ✗ {field_name}: not found")

        self._result_loan_details[acct.last4] = details

    def _navigate_to_account_details(self, page):
        """From an account's activity page, navigate to its Account Details
        sub-view.

        Tries the direct "Account details" link/tab first (credit card
        layout). Falls back to opening the left-rail "More" dropdown and
        clicking "Account details" from the menu (checking account layout).
        """
        reg = load_selectors()
        ad_group = get_selector_group(reg, "chase.detail.account_details_link")
        more_group = get_selector_group(reg, "chase.detail.more_dropdown")

        # Attempt 1: direct Account details link/tab (CC)
        if ad_group:
            el = resilient_find(page, ad_group, timeout=3, allow_ai=False)
            if el:
                try:
                    el.click()
                    page.wait_for_load_state("domcontentloaded", timeout=5000)
                    log.info("[chase] Navigated to Account Details (direct)")
                    return
                except Exception as e:
                    log.debug("Direct Account details click failed: %s", e)

        # Attempt 2: More dropdown → Account details (checking)
        if more_group:
            more_el = resilient_find(page, more_group, timeout=3, allow_ai=False)
            if more_el:
                try:
                    more_el.click()
                    page.wait_for_timeout(800)
                    if ad_group:
                        ad_el = resilient_find(
                            page, ad_group, timeout=3, allow_ai=False
                        )
                        if ad_el:
                            ad_el.click()
                            page.wait_for_load_state(
                                "domcontentloaded", timeout=5000
                            )
                            log.info(
                                "[chase] Navigated to Account Details (via More)"
                            )
                            return
                except Exception as e:
                    log.debug("More dropdown navigation failed: %s", e)

        log.warning(
            "[chase] Could not navigate to Account Details view; "
            "regex will run on activity page and likely miss most fields"
        )

    @staticmethod
    def _extract_field_value(page_text: str, patterns: list[str]) -> str | None:
        """Extract a field value from page text using label patterns.

        Default shape is label-first — ``"Label: $1,234.56"`` / ``"Label  5.25%"``
        — and each pattern is interpolated as the label prefix of an assembled
        regex whose capture group is the value.

        A pattern that already contains its own capture group (e.g. value-first
        shapes like the Chase "Minimum payment" line which embeds the due date)
        is run verbatim, and group 1 is returned. This mirrors NFCU's helper so
        value-first and label-first patterns can live in the same list.
        """
        _has_capture = re.compile(r"\((?!\?:)")

        for pattern in patterns:
            if _has_capture.search(pattern):
                full_regex = pattern
            else:
                # Chase puts label and value on separate lines, with an
                # optional subtitle line between (e.g. "as of 12:00 AM ET
                # on 04/17/2026" between "Available balance" and
                # "$4,172.97"). The helper walks by line boundaries rather
                # than a flexible char gap so subtitle fragments like
                # "12:00", "04/17/2026", or the lowercase word "on" can't
                # masquerade as the real value. The subtitle slot forbids
                # ``$`` and ``%`` to keep it from eating the actual value
                # line. No plain-number fallback — every scraped Chase
                # field is a dollar amount, percentage, date, or flag.
                # Flag matching is case-sensitive to block the lowercase
                # English word "on" from matching the "On" flag.
                full_regex = (
                    rf"{pattern}[^\n]*\n(?:[^\n$%]*\n)?\s*"
                    rf"(\$[\d,]+\.?\d*|"  # dollar amount
                    rf"[\d,]+\.?\d*\s*%|"  # percentage
                    rf"\d{{1,2}}/\d{{1,2}}/\d{{2,4}}|"  # slash date
                    rf"[A-Z][a-z]+\s+\d{{1,2}},?\s+\d{{4}}|"  # "Mar 18, 2026"
                    rf"(?-i:On|Off|Enrolled|Not\s+Enrolled|Yes|No))"  # flags
                )
            match = re.search(full_regex, page_text, re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1).strip()

        return None

    def _scrape_credit_score(self, page):
        """Scrape VantageScore from Chase Credit Journey."""
        log.info("[%s] Attempting to scrape credit score...", self.institution)
        try:
            # 1. Try to find the portal link
            score_link = page.locator("a:has-text('Credit Journey'), a:has-text('Credit score'), div[data-testid='creditJourneyTile']").first
            if score_link.is_visible(timeout=5000):
                score_link.click()
                page.wait_for_load_state("networkidle", timeout=15000)
            else:
                log.info("[%s] Could not find explicit Credit Journey link on dashboard", self.institution)

            page_text = page.inner_text("body", timeout=5000)
            
            score_match = re.search(r"(?:Credit Journey|Your Score|Credit Score)[^\d]{0,40}?(\d{3})(?!\d)", page_text, re.IGNORECASE | re.DOTALL)
            
            if score_match:
                score = int(score_match.group(1))
                if 300 <= score <= 850:
                    score_date = datetime.now().strftime("%Y-%m-%d")
                            
                    from dal.database import get_db
                    from dal.credit_scores import record_credit_score
                    with get_db() as conn:
                        record_credit_score(
                            conn,
                            score=score,
                            score_type="VantageScore 3.0",
                            source="Experian",
                            institution_id=self.institution,
                            score_date=score_date,
                            factors=[],
                        )
                        conn.commit()
                    print(f"       ✔ Credit Score: {score} (as of {score_date})")
                else:
                    log.warning("[%s] Parsed score %d outside range", self.institution, score)
                    print(f"       ✗ Credit Score parsed invalid value: {score}")
            else:
                log.info("[%s] Credit score value not found on page", self.institution)
                print(f"       ✗ Credit Score value not found")

        except Exception as e:
            log.warning("[%s] Failed to scrape credit score: %s", self.institution, e)
            print(f"       ✗ Credit Score check failed: {e}")
        finally:
            try:
                page.goto(self._dashboard_url, wait_until="domcontentloaded", timeout=15000)
            except Exception:
                pass
