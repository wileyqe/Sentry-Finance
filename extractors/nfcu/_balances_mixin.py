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


class NFCUBalancesMixin:
    """Mixin extracted from NFCUConnector: _balances_mixin methods."""

    def _trigger_export(self, page, accounts: list[AccountConfig]) -> list[Path]:
        """Execute the full NFCU export process.

        Phase 1: Scrape balances from the accounts overview
        Phase 2: Download transaction CSVs
        Phase 3: Extract loan details from detail pages
        """
        downloaded_files = []

        # Randomize the processing order to defeat behavioral footprinting
        # of traversing accounts in the exact same array sequence every time.
        accounts = list(accounts)  # clone the list
        random.shuffle(accounts)

        # Capture the dashboard URL — this is where we land post-login.
        # We use this instead of self.export_url for navigation since
        # direct URL access to digitalomni may return 404.
        self._dashboard_url = page.url
        print(f"  📍  Dashboard URL: {self._dashboard_url}")
        self._screenshot(page, "dashboard", error_only=True)

        # Diagnostic: dump page structure to help debug selectors
        self._dump_page_diagnostics(page)

        # ── Phase 1: Balances ────────────────────────────────────────
        balance_accounts = [a for a in accounts if a.balance]
        if balance_accounts:
            print(f"\n  ── Phase 1: Balances ({len(balance_accounts)} accounts) ──")
            self._scrape_balances(page, balance_accounts)

        # ── Smart Fast-Path (Skip Unchanged Accounts) ────────────────
        from dal.database import get_db
        from dal.balances import get_latest_balance

        changed_accounts = []
        with get_db() as conn:
            for acct in accounts:
                scraped_data = self._result_balances.get(acct.last4)
                if not scraped_data:
                    # If we couldn't scrape the balance, process to be safe
                    changed_accounts.append(acct)
                    continue

                # Parse the scraped string (e.g., "$4,200.00") into a float
                scraped_str = scraped_data["balance"]
                try:
                    scraped_num = float(
                        scraped_str.replace("$", "").replace(",", "").strip()
                    )
                except ValueError:
                    scraped_num = None

                db_acct_id = f"{self.institution}_{acct.last4}"
                db_bal_row = get_latest_balance(conn, db_acct_id)

                if getattr(self, "_force_run", False):
                    print(
                        f"       ⚡  [{acct.last4}] {acct.name}: Forced run, executing extraction updates"
                    )
                    changed_accounts.append(acct)
                elif db_bal_row and db_bal_row.get("balance") == scraped_num:
                    print(
                        f"       ⏭️  [{acct.last4}] {acct.name}: Balance unchanged, skipping extraction updates"
                    )
                else:
                    changed_accounts.append(acct)

        # ── Phase 2: Transaction CSVs ────────────────────────────────
        txn_accounts = [a for a in changed_accounts if a.transactions]
        if txn_accounts:
            print(f"\n  ── Phase 2: Transactions ({len(txn_accounts)} accounts) ──")
            for acct in txn_accounts:
                csv_path = self._download_account_csv(page, acct)
                if csv_path:
                    downloaded_files.append(csv_path)

        # ── Phase 3: Loan Details ────────────────────────────────────
        loan_accounts = [a for a in changed_accounts if a.wants_loan_details]
        if loan_accounts:
            print(f"\n  ── Phase 3: Loan Details ({len(loan_accounts)} accounts) ──")
            for acct in loan_accounts:
                self._scrape_loan_details(page, acct)

        # ── Phase 4: Credit Score ────────────────────────────────────
        if any(getattr(a, 'wants_credit_score', False) for a in accounts):
            print("\n  ── Phase 4: Credit Score ──")
            try:
                self._scrape_credit_score(page)
            except Exception as e:
                log.warning("[%s] Credit score phase failed: %s", self.institution, e)

        return downloaded_files

    def _scrape_balances(self, page, accounts: list[AccountConfig]):
        """Scrape balance values from the accounts overview page."""
        self._ensure_overview_page(page)

        for acct in accounts:
            balance = self._find_balance(page, acct)
            if balance is not None:
                self._result_balances[acct.last4] = {
                    "name": acct.name,
                    "last4": acct.last4,
                    "type": acct.type,
                    "balance": balance,
                    "scraped_at": datetime.now().isoformat(),
                }
                print(f"       ✔ [{acct.last4}] {acct.name}: {balance}")
            else:
                print(f"       ✗ [{acct.last4}] {acct.name}: balance not found")

    def _find_balance(self, page, acct: AccountConfig) -> str | None:
        """Find the balance for an account on the overview page."""
        try:
            # Strategy 1: Find elements containing the last4 digits,
            # then look for dollar amounts in the parent container
            elements = page.query_selector_all(f"text=/{acct.last4}/")
            for el in elements:
                parent = el.evaluate_handle(
                    "el => el.closest('div[class], section, article, li, tr') "
                    "|| el.parentElement.parentElement"
                )
                if parent:
                    text = parent.evaluate("el => el.innerText")
                    amounts = re.findall(r"\$[\d,]+\.\d{2}", text)
                    if amounts:
                        return amounts[0]

            # Strategy 2: Regex the full page text
            page_text = page.inner_text("body")
            match = re.search(
                rf"{acct.last4}.*?(\$[\d,]+\.\d{{2}})", page_text, re.DOTALL
            )
            if match:
                return match.group(1)

        except Exception as e:
            print(f"       ⚠ Error finding balance for {acct.last4}: {e}")

        return None

    def _scrape_loan_details(self, page, acct: AccountConfig):
        """Navigate to a loan account and extract requested detail fields."""
        print(f"\n       [{acct.last4}] Loan details for {acct.name}...")

        self._ensure_overview_page(page)
        if not self._click_account(page, acct):
            print(f"       ✗ Could not find account link for {acct.last4}")
            print(f"         → Navigate manually, then press ENTER")
            input()

        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception as e:
            log.debug("Wait timed out: %s", e)
        self._human_jitter()

        self._screenshot(page, f"loan_detail_{acct.last4}", error_only=True)

        # Expand "Show more details" if present (Loan accounts)
        try:
            # Look for the expansion button/link
            # Common text: "SHOW MORE DETAILS", "Show more details"
            toggle = page.query_selector("text=/show more details/i")
            if toggle and toggle.is_visible():
                print(f"       → Expanding 'Show more details'...")
                toggle.click()
                # Wait for animation/DOM update
                page.wait_for_timeout(2000)
                self._screenshot(
                    page, f"loan_detail_expanded_{acct.last4}", error_only=True
                )
        except Exception as e:
            log.debug("Ignored exception: %s", e)

        # Extract text from the page
        page_text = page.inner_text("body")
        # Dump raw page text for debugging regex matches
        dump_path = self._export_dir / f"loan_page_text_{acct.last4}.txt"
        dump_path.write_text(page_text, encoding="utf-8")
        log.info("Loan page text dumped to %s", dump_path)

        # ── Normalize NFCU's split rendering ──
        # NFCU renders dollar amounts as separate DOM elements, producing
        # inner_text like:  "$\n1,292\n.\n36"  or  "2\n.\n375\n%"
        # Collapse these back into "$1,292.36" and "2.375%" so regex works.
        page_text = re.sub(r"\$\s*\n\s*", "$", page_text)  # "$\n" → "$"
        page_text = re.sub(
            r"(\d)\s*\n\s*\.\s*\n?\s*", r"\1.", page_text
        )  # "1,292\n.\n36" → "1,292.36"
        page_text = re.sub(r"(\d)\s*\n\s*%", r"\1%", page_text)  # "375\n%" → "375%"

        details = {}

        field_patterns = {
            "original_loan_amount": [
                r"Original\s+(?:Loan\s+)?Amount",
                r"Loan\s+Amount",
            ],
            "14_day_payoff": [r"14[\s-]*Day\s+Payoff", r"Payoff\s+Amount"],
            "monthly_payment": [
                r"Monthly\s+Payment\s+Amount",
                r"Monthly\s+Payment",
                r"Payment\s+Amount",
                r"Regular\s+Payment",
            ],
            "remaining_term": [r"Remaining\s+Term", r"Term\s+Remaining"],
            "apr": [
                r"Current\s+APR",
                r"APR",
                r"Annual\s+Percentage\s+Rate",
                r"Interest\s+Rate",
            ],
            "ytd_interest": [
                r"Interest\s+Charged\s+YTD",
                r"YTD\s+Interest",
                r"Year[\s-]+to[\s-]+Date\s+Interest",
                r"Interest\s+Paid\s+YTD",
            ],
            "daily_interest_accrual": [
                r"Daily\s+Interest\s+Accrual\s+Amount",
                r"Daily\s+Interest",
                r"Per\s+Diem",
                r"Daily.*Accrual",
            ],
            "maturity_date": [
                r"Maturity\s+Date",
                r"Payoff\s+Date",
                r"Loan\s+End\s+Date",
            ],
            "escrow_balance": [r"Escrow\s+Balance", r"Escrow"],
            "payment_due": [
                r"Payment\s+Due",
                r"Next\s+Payment",
                r"Due\s+Date",
                r"\bDue\b",
            ],
            "interest_rate": [r"Interest\s+Rate", r"Rate", r"APR"],
            "credit_limit": [
                r"Credit\s+Limit",
                r"Total\s+Credit\s+Line",
            ],
            "available_credit": [
                r"Available\s+Credit",
                r"Credit\s+Available",
            ],
            "minimum_payment": [
                r"Minimum\s+Payment\s+Due",
                r"Minimum\s+Payment",
                r"Min(?:imum)?\s+Due",
            ],
            "purchase_apr": [
                r"Purchase\s+APR",
                r"Purchase\s+Rate",
            ],
            "cash_advance_apr": [
                r"Cash\s+Advance\s+APR",
                r"Cash\s+Advance\s+Rate",
            ],
            "rewards_points": [
                # Value-first: NFCU renders rewards as a button label like
                # "10,142pts Rewards" — digits → pts → Rewards. Listed first
                # so it wins against the label-first fallbacks below when
                # both shapes co-exist on the page.
                r"(\d[\d,]*)\s*pts\s+Rewards?",
                r"Rewards?\s+Points?\s+Balance",
                r"Points?\s+Balance",
                r"Available\s+Points",
            ],
            "statement_balance": [
                r"Statement\s+Balance",
                r"Previous\s+Statement",
                r"Last\s+Statement",
            ],
            # ── P15-T04 Phase B: deposit fields ────────────────────────────
            "apy": [
                r"APY",
                r"Annual\s+Percentage\s+Yield",
                r"Dividend\s+Rate",
            ],
            "dividends_ytd": [
                r"Year[\s-]+to[\s-]+Date\s+Dividends",
                r"Dividends?\s+YTD",
                r"YTD\s+Dividends",
            ],
            "last_year_dividends": [
                r"Last\s+Year\s+Dividends",
                r"Previous\s+Year\s+Dividends",
                r"Prior\s+Year\s+Dividends",
            ],
            "date_opened": [
                r"Date\s+Opened",
                r"Account\s+Opened",
                r"Opened\s+(?:on)?",
            ],
            "direct_deposit_enrolled": [
                r"Direct\s+Deposit",
            ],
            "available_balance": [
                r"Available\s+Balance",
            ],
            # ── P15-T04 Phase B: credit-card fields ───────────────────────
            "cash_advance_limit": [
                r"Cash\s+Advance\s+Limit",
            ],
            "cash_advance_available": [
                r"Cash\s+Advance\s+Available",
                r"Available\s+Cash\s+Advance",
            ],
            "payment_due_date": [
                r"Payment\s+Due\s+Date",
                r"Due\s+Date",
            ],
            # ── P15-T04 Phase B: loan fields ──────────────────────────────
            "payoff_today": [
                r"Today'?s?\s+Payoff",
                r"Current\s+Payoff",
            ],
            "payments_made": [
                r"Payments\s+Made",
                r"Number\s+of\s+Payments\s+Made",
            ],
            "collateral_type": [
                r"Collateral\s+Type",
            ],
            "collateral_description": [
                r"Collateral\s+Description",
                r"Collateral\s+Info",
            ],
            "vin": [
                # Value-first: 17-char VIN regex with its own capture group
                # so _extract_field_value runs it verbatim. NFCU renders
                # "VIN: <17-char alnum>" but may swap label to "Vehicle
                # Identification Number".
                r"(?:VIN|Vehicle\s+Identification(?:\s+Number)?)[\s:#]+([A-HJ-NPR-Z0-9]{17})",
            ],
            "gap_flag": [
                r"GAP(?:\s+Coverage)?(?:\s+Insurance)?",
            ],
        }

        for field_name in acct.loan_details:
            if field_name == "current_balance":
                continue  # handled separately via HomeSquad below
            patterns = field_patterns.get(field_name, [field_name.replace("_", r"\s+")])
            value = self._extract_field_value(page_text, patterns)
            if value:
                details[field_name] = value
                print(f"       ✔ {field_name}: {value}")
            else:
                details[field_name] = None
                print(f"       ✗ {field_name}: not found")

        if details.get("purchase_apr") and not details.get("apr"):
            details["apr"] = details["purchase_apr"]

        # ── Special handler: current_balance + property estimate via HomeSquad ──
        if "current_balance" in acct.loan_details:
            hs_data = self._scrape_homesquad_data(page, acct)
            details["current_balance"] = hs_data.get("balance")
            if hs_data.get("estimated_home_value"):
                details["estimated_home_value"] = hs_data["estimated_home_value"]
                # Promote the scraped value into the canonical real_estate
                # valuations table so the Accounts page and net-worth
                # history see it without waiting for the one-off seeder.
                # Failure here must NOT take down the refresh flow
                # (CLAUDE.md connector-isolation guardrail).
                self._promote_homesquad_to_real_estate(
                    account_id=f"{self.institution}_{acct.last4}",
                    raw_value=hs_data["estimated_home_value"],
                )

        self._result_loan_details[acct.last4] = details

    def _promote_homesquad_to_real_estate(self, account_id: str, raw_value: str) -> None:
        """Append today's HomeSquad value as a new row in ``real_estate``.

        Looks up an existing property row by ``linked_loan_id == account_id``
        (the mortgage account this connector is scraping) and inherits
        ``name``, ``linked_loan_id``, and ``owner_id`` from it. If no
        such property row exists yet, logs a warning and returns — we
        deliberately don't auto-create the property row here; property
        bootstrap is out-of-band (``scripts/seed_real_estate.py``).
        """
        try:
            from datetime import date
            from dal.database import get_db
            from dal.real_estate import record_real_estate_valuations

            cleaned = re.sub(r"[^0-9.]", "", str(raw_value))
            if not cleaned:
                log.warning(
                    "HomeSquad value %r had no numeric content — skipping real_estate promotion",
                    raw_value,
                )
                return
            value_dollars = float(cleaned)
            if value_dollars <= 0:
                log.warning(
                    "HomeSquad value %.2f not positive — skipping real_estate promotion",
                    value_dollars,
                )
                return

            with get_db() as conn:
                existing = conn.execute(
                    """SELECT name, linked_loan_id, owner_id
                       FROM real_estate
                       WHERE linked_loan_id = ?
                       ORDER BY as_of DESC, id DESC
                       LIMIT 1""",
                    (account_id,),
                ).fetchone()
                if not existing:
                    log.warning(
                        "HomeSquad promotion: no real_estate row linked to loan %s — "
                        "run scripts/seed_real_estate.py to bootstrap the property first",
                        account_id,
                    )
                    return

                record_real_estate_valuations(
                    conn,
                    [
                        {
                            "name": existing["name"],
                            "estimated_value": value_dollars,
                            "linked_loan_id": existing["linked_loan_id"],
                            "source": "homesquad",
                            "as_of": date.today().isoformat(),
                            "owner_id": existing["owner_id"],
                        }
                    ],
                )
                conn.commit()
        except Exception as e:
            log.warning(
                "HomeSquad -> real_estate promotion failed for %s: %s", account_id, e
            )
            return

        # Confirmation print is best-effort — a Windows console encoding
        # error on a checkmark must not cancel the already-committed write.
        try:
            print(
                f"       + real_estate: appended HomeSquad value ${value_dollars:,.0f} for {account_id}"
            )
        except Exception:
            pass

    def _scrape_credit_score(self, page: Page):
        """Scrape FICO credit score from the NFCU dashboard or sub-page."""
        log.info("[%s] Attempting to scrape credit score...", self.institution)
        try:
            # 1. Try to find score on the dashboard first, or look for a link
            score_link = page.locator("a:has-text('Credit Score'), a:has-text('FICO Score'), a:has-text('Mission Dashboard')").first
            if score_link.is_visible(timeout=5000):
                score_link.click()
                page.wait_for_load_state("networkidle", timeout=15000)
            else:
                log.info("[%s] Could not find explicit Credit Score link on dashboard, scanning current page", self.institution)

            page_text = page.inner_text("body", timeout=5000)
            
            # Simple heuristic matching FICO strings on NFCU
            score_match = re.search(r"(?:FICO|Your Score|Credit Score)[^\d]{0,30}?(\d{3})(?!\d)", page_text, re.IGNORECASE | re.DOTALL)
            date_match = re.search(r"as of\s+(\d{1,2}/\d{1,2}/\d{4})", page_text, re.IGNORECASE)
            
            if score_match:
                score = int(score_match.group(1))
                if 300 <= score <= 850:
                    score_date = datetime.now().strftime("%Y-%m-%d")
                    if date_match:
                        try:
                            score_date = datetime.strptime(date_match.group(1), "%m/%d/%Y").strftime("%Y-%m-%d")
                        except ValueError:
                            pass
                            
                    from dal.database import get_db
                    from dal.credit_scores import record_credit_score
                    with get_db() as conn:
                        record_credit_score(
                            conn,
                            score=score,
                            score_type="FICO",
                            source="TransUnion",
                            institution_id=self.institution,
                            score_date=score_date,
                            factors=[],
                        )
                        conn.commit()
                    print(f"       ✔ Credit Score: {score} (as of {score_date})")
                else:
                    log.warning("[%s] Parsed score %d outside valid 300-850 range", self.institution, score)
                    print(f"       ✗ Credit Score parsed invalid value: {score}")
            else:
                log.info("[%s] Credit score value not found on page", self.institution)
                print(f"       ✗ Credit Score value not found")

        except Exception as e:
            log.warning("[%s] Failed to scrape credit score: %s", self.institution, e)
            print(f"       ✗ Credit Score check failed: {e}")
        finally:
            try:
                # Always restore back to the dashboard if we navigated away
                page.goto(self._dashboard_url, wait_until="domcontentloaded", timeout=15000)
            except Exception:
                pass

    def _scrape_homesquad_data(self, page, acct) -> dict:
        """Open the HomeSquad mortgage dashboard and scrape balance + home value.

        HomeSquad opens in a NEW TAB. We use open_transient_tab to ensure
        the popup is automatically closed when we're done, preventing
        zombie tabs per resource-session-management.md.

        Returns:
            {"balance": "$260,420.13", "estimated_home_value": "$334,300"}
            Values are None if not found.
        """
        result = {"balance": None, "estimated_home_value": None}
        print(f"       → Opening HomeSquad dashboard for {acct.last4}...")
        try:
            # Look for the HomeSquad button on the account page
            hs_btn = page.query_selector("text=/HomeSquad/i")
            if not hs_btn or not hs_btn.is_visible():
                hs_btn = page.query_selector('button:has-text("HomeSquad")')
            if not hs_btn or not hs_btn.is_visible():
                hs_btn = page.query_selector('a:has-text("HomeSquad")')

            if not hs_btn:
                print("       ✗ HomeSquad button not found")
                return result

            # HomeSquad opens in a new tab — capture it with open_transient_tab
            context = page.context
            with self.open_transient_tab(
                context, trigger=lambda: hs_btn.click()
            ) as hs_page:
                try:
                    hs_page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception as e:
                    log.debug("HomeSquad domcontentloaded wait timeout: %s", e)

                # ── Smart SPA wait: poll for content (up to 20s) ──
                # HomeSquad is a slow SPA — a fixed 2-3s jitter is not enough.
                # Poll until dollar amounts appear in the page text.
                hs_text = ""
                for attempt in range(10):  # 10 × 2s = 20s max
                    try:
                        hs_text = hs_page.inner_text("body", timeout=3000)
                    except Exception:
                        hs_text = ""
                    if "$" in hs_text and re.search(r"\$[\d,]+", hs_text):
                        log.info(
                            "HomeSquad content loaded after %ds", (attempt + 1) * 2
                        )
                        break
                    log.debug("HomeSquad SPA loading... attempt %d/10", attempt + 1)
                    hs_page.wait_for_timeout(2000)
                else:
                    log.warning("HomeSquad SPA did not fully load within 20s")

                # Screenshot after content has loaded
                try:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    path = (
                        self._export_dir.parent.parent
                        / "data"
                        / "screenshots"
                        / f"{self.institution}_homesquad_{acct.last4}_{ts}.png"
                    )
                    path.parent.mkdir(parents=True, exist_ok=True)
                    hs_page.screenshot(path=str(path), full_page=True)
                    log.info("[%s] Screenshot: %s", self.institution, path.name)
                except Exception as e:
                    log.debug("HomeSquad screenshot failed: %s", e)

                if not hs_text or "$" not in hs_text:
                    print("       ✗ HomeSquad page did not render")
                    return result

                # Dump for debugging
                dump_path = self._export_dir / f"homesquad_page_text_{acct.last4}.txt"
                dump_path.write_text(hs_text, encoding="utf-8")
                log.info("HomeSquad page text dumped to %s", dump_path)

                # Normalize split dollar rendering
                hs_text = re.sub(r"\$\s*\n\s*", "$", hs_text)
                hs_text = re.sub(r"(\d)\s*\n\s*\.\s*\n?\s*", r"\1.", hs_text)
                hs_text = re.sub(r"(\d)\s*\n\s*%", r"\1%", hs_text)

                # ── Extract balance ──
                balance_match = re.search(
                    r"Balance\s*\n\s*(\$[\d,]+\.?\d*)", hs_text, re.IGNORECASE
                )
                if balance_match:
                    result["balance"] = balance_match.group(1).strip()
                    print(
                        f"       ✔ current_balance: {result['balance']} (from HomeSquad)"
                    )
                else:
                    print("       ✗ current_balance: not found on HomeSquad")

                # ── Extract estimated home value ──
                # NFCU HomeSquad shows:
                #   "Estimated value\n$367,000" — the property's own estimate
                #   "Average home value\n$288,482" — the neighborhood average
                # We want the property-specific one first.
                value_patterns = [
                    r"Estimated\s+value\s*\n?\s*(\$[\d,]+\.?\d*)",
                    r"Property\s+Value\s*\n?\s*(\$[\d,]+\.?\d*)",
                    r"Market\s+Value\s*\n?\s*(\$[\d,]+\.?\d*)",
                    r"Current\s+Value\s*\n?\s*(\$[\d,]+\.?\d*)",
                    r"Appraised\s+Value\s*\n?\s*(\$[\d,]+\.?\d*)",
                ]
                for pat in value_patterns:
                    val_match = re.search(pat, hs_text, re.IGNORECASE)
                    if val_match:
                        result["estimated_home_value"] = val_match.group(1).strip()
                        print(
                            f"       ✔ estimated_home_value: {result['estimated_home_value']} (from HomeSquad)"
                        )
                        break
                else:
                    # Fallback: look for any large dollar amount that isn't the balance
                    all_amounts = re.findall(r"\$([\d,]+)\.?\d*", hs_text)
                    for amt_str in all_amounts:
                        amt = int(amt_str.replace(",", ""))
                        balance_num = (
                            int(
                                result["balance"]
                                .replace("$", "")
                                .replace(",", "")
                                .split(".")[0]
                            )
                            if result["balance"]
                            else 0
                        )
                        # Property values are typically > $100k and not the balance
                        if amt > 100000 and amt != balance_num:
                            result["estimated_home_value"] = f"${amt_str}"
                            print(
                                f"       ✔ estimated_home_value: {result['estimated_home_value']} (from HomeSquad, inferred)"
                            )
                            break
                    else:
                        print("       ✗ estimated_home_value: not found on HomeSquad")

                return result
            # Tab is automatically closed here by open_transient_tab

        except Exception as e:
            print(f"       ✗ HomeSquad error: {e}")
            return result

    @staticmethod
    def _extract_field_value(page_text: str, patterns: list[str]) -> str | None:
        """Extract a field value from page text using label patterns.

        Default shape is label-first — ``"Label: $1,234.56"`` / ``"Label  5.25%"``
        — and each pattern is interpolated as the label prefix of an assembled
        regex whose capture group is the value.

        A pattern that already contains its own capture group (e.g. NFCU's
        value-first rewards button label ``"10,142pts Rewards"`` → pattern
        ``r"(\\d[\\d,]*)\\s*pts\\s+Rewards?"``) is run verbatim, and group 1 is
        returned. This lets callers mix value-first shapes into the same
        pattern list without a second code path.
        """
        _has_capture = re.compile(r"\((?!\?:)")

        for pattern in patterns:
            if _has_capture.search(pattern):
                full_regex = pattern
            else:
                full_regex = (
                    rf"{pattern}(?:.{{0,50}}?)\s*[:=]?\s*"
                    rf"(\$[\d,]+\.?\d*|"  # dollar amount
                    rf"[\d,]+\.?\d*\s*%|"  # percentage
                    rf"\d{{1,2}}/\d{{1,2}}/\d{{2,4}}|"  # date
                    rf"\d+ (?:months?|years?)|"  # term like "36 months"
                    rf"Not\s+Enrolled|Enrolled|Yes|No|"  # enrollment / GAP flags
                    rf"[\d,]+\.?\d*)"  # plain number
                )
            match = re.search(full_regex, page_text, re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1).strip()

        return None
