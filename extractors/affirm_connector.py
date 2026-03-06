"""
extractors/affirm_connector.py — Affirm connector.

Concrete InstitutionConnector subclass implementing the Affirm-specific
login flow and data extraction for:
  - BNPL (Buy Now, Pay Later) active contract scraping
  - HYSA (High-Yield Savings Account) balance and transaction scraping

Auth model: Phone number + SMS OTP (no password).
  - Phone number stored in credential broker as 'username' field.
  - SMS OTP auto-captured via sms_otp.py (Phone Link integration).

URL Note: Affirm's dashboard uses /u/ prefix (e.g. /u/savings, /u/loans)
          but login/logout use /user/ prefix (e.g. /user/signin, /user/signout).
"""

import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page

from skills.institution_connector import (
    InstitutionConnector,
    AccountConfig,
)
from dal.database import get_db
from dal.balances import record_balance, record_loan_details
from dal.transactions import upsert_transactions
from extractors.sms_otp import wait_for_otp
from extractors.ai_backstop import (
    resilient_find,
    resilient_click,
    get_selector_group,
    load_selectors,
)

log = logging.getLogger("sentry.extractors.affirm")

# ── Affirm URL constants ────────────────────────────────────────────────────
# Login/logout use /user/ prefix; dashboard pages use /u/ prefix.

AFFIRM_SIGN_IN = "https://www.affirm.com/user/signin"
AFFIRM_SIGN_OUT = "https://www.affirm.com/user/signout"
AFFIRM_DASHBOARD = "https://www.affirm.com/u/"
AFFIRM_SAVINGS = "https://www.affirm.com/u/savings"
AFFIRM_LOANS = "https://www.affirm.com/u/loans"


class AffirmConnector(InstitutionConnector):
    """Affirm connector.

    Handles two product areas:
      1. HYSA — scrape savings balance and recent transactions
      2. BNPL — enumerate active contracts, scrape contract details
    """

    @property
    def institution(self) -> str:
        return "affirm"

    @property
    def display_name(self) -> str:
        return "Affirm"

    @property
    def export_url(self) -> str:
        return AFFIRM_DASHBOARD

    @property
    def login_url(self) -> str:
        return AFFIRM_SIGN_IN

    # ── Session Validation ───────────────────────────────────────────────

    def _is_session_valid(self, page: Page) -> bool:
        """Override session check for Affirm.

        Navigate to the dashboard and check if we land on an
        authenticated page or get redirected to login.
        """
        try:
            response = page.goto(
                self.export_url, wait_until="domcontentloaded", timeout=30000
            )
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            current = page.url.lower()

            # Redirected to login?
            if any(kw in current for kw in ("signin", "sign-in", "login", "auth")):
                log.info("[%s] Session expired — redirected to login", self.institution)
                return False

            # HTTP error?
            if response and response.status >= 400:
                log.info(
                    "[%s] Session check got HTTP %d",
                    self.institution,
                    response.status,
                )
                return False

            # On a dashboard page? (/u/ paths are authenticated)
            if "/u/" in current:
                log.info("[%s] Session valid — on dashboard URL", self.institution)
                return True

            # Check for dashboard content markers
            try:
                body = page.inner_text("body").strip().lower()
                if len(body) > 200 and any(
                    kw in body
                    for kw in ("savings", "loans", "manage", "money", "deals")
                ):
                    log.info(
                        "[%s] Session valid — dashboard content found",
                        self.institution,
                    )
                    return True
            except Exception:
                pass

            return False

        except Exception as e:
            log.warning("[%s] Session check failed: %s", self.institution, e)
            return False

    # ── Post-Login Detection ─────────────────────────────────────────────

    def _is_post_login(self, page: Page) -> bool:
        """Detect whether authentication is complete on Affirm.

        Affirm redirects to /u/ dashboard pages after login.
        Login pages use /user/signin or /user/verify paths.
        """
        current = page.url.lower()

        # Strategy 1: On a /u/ dashboard path (not /user/signin)
        if "/u/" in current and "/user/signin" not in current:
            return True

        # Strategy 2: URL no longer has login keywords
        login_keywords = ("signin", "sign-in", "login", "verify", "otp", "challenge")
        if not any(kw in current for kw in login_keywords):
            # Check for dashboard nav elements
            try:
                body = page.inner_text("body").strip().lower()
                if any(
                    marker in body
                    for marker in ("savings", "loans", "manage", "money", "deals")
                ):
                    return True
            except Exception:
                pass

        return False

    # ── Login ────────────────────────────────────────────────────────────

    def _perform_login(self, page: Page, credentials: dict | None = None) -> bool:
        """Navigate to Affirm sign-in and enter phone number.

        Affirm uses phone+SMS OTP (no password). The credential broker
        stores the phone number in the 'username' slot.

        Flow:
          1. Navigate to sign-in page
          2. Fill phone number from broker credentials
          3. Click Continue/Submit
          4. OTP handled by _wait_for_mfa()
        """
        log.info("[%s] Navigating to login URL: %s", self.institution, self.login_url)
        page.goto(self.login_url, wait_until="domcontentloaded", timeout=45000)

        # Wait for the phone input to render
        try:
            page.wait_for_selector('input[type="tel"]', state="visible", timeout=10000)
        except Exception:
            log.debug(
                "[%s] Phone field not visible yet, continuing...", self.institution
            )

        reg = load_selectors()

        if credentials and "username" in credentials:
            phone_number = credentials["username"]
            log.info("[%s] Using broker credentials (phone).", self.institution)

            phone_group = get_selector_group(
                reg, f"{self.institution}.login.phone_input"
            )
            submit_group = get_selector_group(reg, f"{self.institution}.login.submit")

            phone_el = resilient_find(page, phone_group)
            if not phone_el:
                log.error("[%s] Could not find phone input field.", self.institution)
                return False

            phone_el.fill(phone_number)
            page.wait_for_timeout(500)

            resilient_click(page, submit_group)
            log.info("[%s] Phone number submitted, awaiting OTP...", self.institution)
            return True
        else:
            log.info(
                "[%s] No credentials provided — user must enter phone manually.",
                self.institution,
            )
            return True

    # ── MFA (SMS OTP) ────────────────────────────────────────────────────

    def _wait_for_mfa(self, page: Page, timeout_seconds: int = 300):
        """Auto-detect OTP prompt and intercept SMS code for Affirm.

        Affirm may present:
          1. SMS OTP to phone (primary)
          2. Email OTP (additional verification for untrusted devices)

        Uses the Phone Link SMS capture from sms_otp.py for step 1.
        Email OTP must be entered manually if triggered.
        """
        if self._is_post_login(page):
            return

        print()
        print("  ┌─────────────────────────────────────────────────┐")
        print(f"  │  [{self.display_name}] Waiting for SMS OTP...    │")
        print("  │                                                  │")
        print("  │  A verification code will be sent to your phone. │")
        print("  │  Phone Link will auto-capture it.                │")
        print("  │                                                  │")
        print("  │  If email OTP is also required, enter it in the  │")
        print("  │  browser manually.                               │")
        print("  └─────────────────────────────────────────────────┘")
        print()

        polls = timeout_seconds // 2
        otp_attempted = False

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

            # Look for OTP entry field
            if not otp_attempted:
                try:
                    # Check for any visible OTP-like input fields
                    otp_field = page.query_selector(
                        'input[autocomplete="one-time-code"], '
                        'input[name*="code"], '
                        'input[id*="otp"], '
                        'input[inputmode="numeric"]:visible'
                    )

                    if otp_field and otp_field.is_visible():
                        log.info(
                            "[%s] OTP field detected. Intercepting SMS...",
                            self.institution,
                        )
                        otp_attempted = True

                        code = wait_for_otp(timeout=120, hint="Affirm")

                        if code:
                            log.info(
                                "[%s] Filling intercepted OTP: %s***",
                                self.institution,
                                code[:2],
                            )

                            # Check for split inputs (one digit per field)
                            all_inputs = page.query_selector_all(
                                'input[autocomplete="one-time-code"], '
                                'input[inputmode="numeric"][maxlength="1"]'
                            )

                            if len(all_inputs) == len(code):
                                log.info(
                                    "[%s] Filling split OTP inputs.",
                                    self.institution,
                                )
                                for idx, char in enumerate(code):
                                    all_inputs[idx].fill(char)
                                    page.wait_for_timeout(100)
                                all_inputs[-1].press("Enter")
                            else:
                                log.info(
                                    "[%s] Filling single OTP input.",
                                    self.institution,
                                )
                                otp_field.fill(code)
                                page.wait_for_timeout(500)
                                otp_field.press("Enter")

                            try:
                                page.wait_for_load_state("networkidle", timeout=15000)
                            except Exception:
                                log.debug(
                                    "[%s] Wait for OTP submission timeout",
                                    self.institution,
                                )
                        else:
                            log.warning(
                                "[%s] Phone Link OTP capture failed — "
                                "user must enter code manually.",
                                self.institution,
                            )
                except Exception as e:
                    log.debug(
                        "[%s] OTP interception logic error: %s",
                        self.institution,
                        e,
                    )

            # Progress indicator every 30 seconds
            if i > 0 and i % 15 == 0:
                elapsed = i * 2
                print(f"  ⏳  Still waiting... ({elapsed}s / {timeout_seconds}s)")

        log.warning(
            "[%s] MFA wait timed out after %ds", self.institution, timeout_seconds
        )

    # ── Export Orchestrator ───────────────────────────────────────────────

    def _trigger_export(self, page: Page, accounts: list[AccountConfig]) -> list[Path]:
        """Execute data extraction for both HYSA and BNPL.

        Routes to the appropriate scraper based on account type:
          - type=savings → _scrape_hysa()
          - type=bnpl    → _scrape_bnpl()
        """
        files: list[Path] = []

        for acct in accounts:
            if acct.type == "savings":
                log.info("[%s] Extracting HYSA data...", self.institution)
                self._scrape_hysa(page, acct)
            elif acct.type == "bnpl":
                log.info("[%s] Extracting BNPL contracts...", self.institution)
                self._scrape_bnpl(page, acct)
            else:
                log.warning(
                    "[%s] Unknown account type '%s' for %s",
                    self.institution,
                    acct.type,
                    acct.name,
                )

        return files

    # ── HYSA Scraping ────────────────────────────────────────────────────

    def _scrape_hysa(self, page: Page, acct: AccountConfig) -> None:
        """Scrape High-Yield Savings balance and recent transactions.

        Navigates to /u/savings and extracts:
          - Available balance / Current balance
          - Transaction list via aria-label attributes on button elements
        """
        log.info("[%s] Navigating to savings page...", self.institution)
        page.goto(AFFIRM_SAVINGS, wait_until="domcontentloaded", timeout=30000)

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            log.debug("[%s] Savings page networkidle timeout", self.institution)

        # Give the SPA time to render
        page.wait_for_timeout(2000)

        # ── Scrape balance ───────────────────────────────────────────
        balances = self._extract_savings_balance(page)
        available = balances.get("available")
        current = balances.get("current")
        pending = balances.get("pending")

        # Record Available balance as the primary (conservative) number
        balance = available or current
        if balance is not None:
            account_id = f"{self.institution}_{acct.last4}"
            self._result_balances[acct.last4] = {
                "name": acct.name,
                "balance": balance,
            }

            with get_db() as conn:
                self._ensure_account(conn, account_id, acct)
                record_balance(conn, account_id, balance)
                conn.commit()

            log.info("[%s] HYSA available: $%.2f", self.institution, balance)
            if current and current != balance:
                log.info(
                    "[%s] HYSA current: $%.2f (pending: %s)",
                    self.institution,
                    current,
                    f"${pending:,.2f}" if pending else "unknown",
                )
            print(f"  💰  HYSA Available: ${balance:,.2f}")
            if current and current != balance:
                print(f"       Current:   ${current:,.2f}  (pending: ${pending:,.2f})")
        else:
            log.warning("[%s] Could not extract HYSA balance", self.institution)
            self._screenshot(page, "hysa_balance_failed")

        # ── Scrape transactions ──────────────────────────────────────
        if acct.transactions:
            txns = self._extract_savings_transactions(page)
            if txns:
                account_id = f"{self.institution}_{acct.last4}"
                # Inject account_id and institution_id into each txn dict
                for txn in txns:
                    txn["account_id"] = account_id
                    txn["institution_id"] = self.institution

                with get_db() as conn:
                    self._ensure_account(conn, account_id, acct)
                    result = upsert_transactions(conn, txns)
                    conn.commit()
                log.info(
                    "[%s] HYSA transactions: %d scraped, %d new",
                    self.institution,
                    len(txns),
                    result.get("inserted", 0),
                )
                print(f"  📝  HYSA Transactions: {len(txns)} scraped")
            else:
                log.info("[%s] No HYSA transactions found", self.institution)

    def _extract_savings_balance(self, page: Page) -> dict:
        """Extract savings balances from the /u/savings page.

        Returns a dict with:
          - available: float | None (hero section — excludes pending)
          - current:   float | None (sidebar — includes pending)
          - pending:   float | None (sidebar — pending amount)
        """
        try:
            result = page.evaluate("""
                (() => {
                    const body = document.body.innerText;
                    const data = {};

                    // Available balance (hero section)
                    const availMatch = body.match(
                        /Available\\s+balance[\\s\\n]*\\$([\\d,]+\\.\\d{2})/i
                    );
                    if (availMatch)
                        data.available = parseFloat(availMatch[1].replace(/,/g, ''));

                    // Current balance (sidebar widget)
                    const currMatch = body.match(
                        /Current\\s+balance[\\s\\n]*\\$([\\d,]+\\.\\d{2})/i
                    );
                    if (currMatch)
                        data.current = parseFloat(currMatch[1].replace(/,/g, ''));

                    // Pending transactions amount (sidebar)
                    const pendMatch = body.match(
                        /Pending\\s+transactions[\\s\\n]*-?\\$([\\d,]+\\.\\d{2})/i
                    );
                    if (pendMatch)
                        data.pending = parseFloat(pendMatch[1].replace(/,/g, ''));

                    return data;
                })()
            """)
            return result or {}
        except Exception as e:
            log.debug("[%s] Balance extraction failed: %s", self.institution, e)

        return {}

    def _extract_savings_transactions(self, page: Page) -> list[dict]:
        """Scrape recent savings transactions from aria-label attributes.

        Affirm savings transactions are button elements with aria-labels
        like: 'Interest, March 1, 2026, +$18.71'
              'Deposit, February 4, 2026, +$350.00'
        """
        transactions = []
        try:
            raw = page.evaluate("""
                (() => {
                    const txns = [];
                    // Find all buttons/elements with aria-label containing $
                    const elements = document.querySelectorAll(
                        'button[aria-label*="$"], [role="button"][aria-label*="$"]'
                    );
                    for (const el of elements) {
                        const label = el.getAttribute('aria-label');
                        if (label) txns.push(label);
                    }
                    return txns;
                })()
            """)

            for label in raw or []:
                try:
                    parsed = self._parse_aria_label_transaction(label)
                    if parsed:
                        transactions.append(parsed)
                except Exception as e:
                    log.debug(
                        "[%s] Skipping malformed transaction '%s': %s",
                        self.institution,
                        label[:40],
                        e,
                    )
        except Exception as e:
            log.warning("[%s] Transaction scraping failed: %s", self.institution, e)

        return transactions

    @staticmethod
    def _parse_aria_label_transaction(label: str) -> dict | None:
        """Parse an aria-label string into a transaction dict.

        Expected formats:
          Posted:  'Interest, March 1, 2026, +$18.71'
          Pending: 'Deposit, Available in 2 days, +$350.00'
        """
        # Split on commas — expecting: [type, date_or_status, ..., amount]
        parts = [p.strip() for p in label.split(",")]
        if len(parts) < 3:
            return None

        description = parts[0]

        # Find the amount (last part containing $)
        amount_str = None
        for part in reversed(parts):
            if "$" in part:
                amount_str = part.strip()
                break

        if not amount_str:
            return None

        # Parse amount
        is_negative = "-" in amount_str
        amount = float(re.sub(r"[^0-9.]", "", amount_str))
        if is_negative:
            amount = -amount

        # Detect pending status: "Available in X days" pattern
        middle_text = ", ".join(parts[1:-1]).strip()
        is_pending = bool(re.search(r"available in", middle_text, re.IGNORECASE))

        # Parse date from the middle parts (skip amount parts)
        date_parts = [p for p in parts[1:-1] if "$" not in p]
        date_str = ", ".join(date_parts).strip()

        if is_pending:
            # Pending transactions have no real date yet — use today
            posting_date = datetime.now().strftime("%Y-%m-%d")
        else:
            posting_date = AffirmConnector._parse_date(date_str)

        return {
            "posting_date": posting_date,
            "amount": abs(amount),
            "signed_amount": amount,
            "direction": "debit" if amount < 0 else "credit",
            "description": description,
            "raw_description": label,
            "status": "pending" if is_pending else "posted",
        }

    @staticmethod
    def _parse_date(date_str: str) -> str:
        """Parse various date formats into ISO format."""
        # Clean up extra whitespace
        date_str = " ".join(date_str.split())
        for fmt in (
            "%B %d %Y",  # March 1 2026
            "%B %d, %Y",  # March 1, 2026
            "%b %d %Y",  # Mar 1 2026
            "%b %d, %Y",  # Mar 1, 2026
            "%m/%d/%Y",  # 03/01/2026
            "%m/%d/%y",  # 03/01/26
        ):
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        # Fallback: return as-is
        return date_str.strip()

    # ── BNPL Scraping ────────────────────────────────────────────────────

    def _scrape_bnpl(self, page: Page, acct: AccountConfig) -> None:
        """Scrape active BNPL contracts from the Affirm loans page.

        Navigates to /u/loans, enumerates active contracts, clicks each
        to expand the DETAILS tab, and extracts contract metadata.
        """
        log.info("[%s] Navigating to loans page...", self.institution)
        page.goto(AFFIRM_LOANS, wait_until="domcontentloaded", timeout=30000)

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            log.debug("[%s] Loans page networkidle timeout", self.institution)

        # Give the SPA time to render
        page.wait_for_timeout(2000)

        # ── Scrape total BNPL balance ────────────────────────────────
        total_balance = self._extract_total_bnpl_balance(page)
        if total_balance is not None:
            account_id = f"{self.institution}_{acct.last4}"
            self._result_balances[acct.last4] = {
                "name": "BNPL Total",
                "balance": total_balance,
            }
            with get_db() as conn:
                self._ensure_account(conn, account_id, acct)
                record_balance(conn, account_id, total_balance)
                conn.commit()
            log.info("[%s] Total BNPL balance: $%.2f", self.institution, total_balance)
            print(f"  💳  Total BNPL Balance: ${total_balance:,.2f}")

        # ── Enumerate and scrape individual contracts ────────────────
        contracts = self._enumerate_contracts(page)

        if not contracts:
            log.info("[%s] No active BNPL contracts found", self.institution)
            print("  📋  No active BNPL contracts")
            return

        print(f"  📋  Found {len(contracts)} active BNPL contract(s)")

        for contract in contracts:
            self._process_contract(page, contract)

    def _extract_total_bnpl_balance(self, page: Page) -> float | None:
        """Extract the total BNPL balance from the loans page.

        Looks for "TOTAL BALANCE" label followed by dollar amount.
        """
        try:
            result = page.evaluate("""
                (() => {
                    const body = document.body.innerText;
                    const match = body.match(
                        /TOTAL\\s+BALANCE[\\s\\n]*\\$([\\d,]+\\.\\d{2})/i
                    );
                    if (match) return parseFloat(match[1].replace(/,/g, ''));
                    return null;
                })()
            """)
            if result is not None:
                return float(result)
        except Exception as e:
            log.debug(
                "[%s] Total BNPL balance extraction failed: %s", self.institution, e
            )
        return None

    def _enumerate_contracts(self, page: Page) -> list[dict]:
        """Find ACTIVE BNPL contracts on the loans page.

        The loans page has two sections:
          - "Active" — current obligations (what we want)
          - "Past Payments" — fully paid contracts (skip these)

        Strategy: find the Y-position of the "Past Payments" heading
        and only return loan cards that appear above it.

        Loan card IDs follow the pattern loan-XXXX-XXXX
        (4 alphanumeric, hyphen, 4 alphanumeric).
        """
        contracts = []
        try:
            raw = page.evaluate("""
                (() => {
                    // Find the "Past Payments" heading's vertical position
                    let pastPaymentsY = Infinity;
                    const walker = document.createTreeWalker(
                        document.body,
                        NodeFilter.SHOW_TEXT,
                        null
                    );
                    while (walker.nextNode()) {
                        if (walker.currentNode.textContent.trim() === 'Past Payments') {
                            const rect = walker.currentNode.parentElement
                                .getBoundingClientRect();
                            pastPaymentsY = rect.top;
                            break;
                        }
                    }

                    const contracts = [];
                    const loanEls = document.querySelectorAll('[id^="loan-"]');
                    const loanIdPattern = /^loan-[A-Z0-9]{4}-[A-Z0-9]{4}$/i;

                    for (const el of loanEls) {
                        const id = el.getAttribute('id') || '';
                        if (!loanIdPattern.test(id)) continue;

                        // Only include loans ABOVE the "Past Payments" boundary
                        const elY = el.getBoundingClientRect().top;
                        if (elY >= pastPaymentsY) continue;

                        const text = el.innerText.trim();
                        const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);

                        const merchant = lines[0] || 'Unknown';
                        const amtMatch = text.match(/\\$([\\d,]+\\.\\d{2})/);
                        const dueMatch = text.match(/due\\s*[·:]?\\s*(\\w+\\s+\\d+)/i);

                        contracts.push({
                            loan_id: id.replace('loan-', ''),
                            element_id: id,
                            merchant: merchant,
                            category: lines[1] || '',
                            amount_due: amtMatch ? amtMatch[0] : null,
                            due_date: dueMatch ? dueMatch[1] : null,
                        });
                    }
                    return contracts;
                })()
            """)
            contracts = raw or []
            log.info(
                "[%s] Enumerated %d active contract(s)",
                self.institution,
                len(contracts),
            )
        except Exception as e:
            log.warning("[%s] Contract enumeration failed: %s", self.institution, e)

        return contracts

    def _process_contract(self, page: Page, contract: dict) -> None:
        """Scrape details for a single BNPL contract.

        Clicks the contract card, switches to DETAILS tab, extracts
        metadata, and persists to DB.
        """
        merchant = contract.get("merchant", "Unknown")
        loan_id = contract.get("loan_id", "")
        element_id = contract.get("element_id", "")

        # Create a clean identifier for this contract
        contract_slug = re.sub(r"[^a-z0-9]", "", merchant.lower())[:12]
        if not contract_slug:
            contract_slug = loan_id.lower().replace("-", "") if loan_id else "bnpl"
        account_id = f"{self.institution}_{contract_slug}"

        details = {
            "merchant": merchant,
            "loan_id": loan_id,
            "category": contract.get("category", ""),
        }

        # Add amount from the card listing
        if contract.get("amount_due"):
            details["amount_due"] = contract["amount_due"]
        if contract.get("due_date"):
            details["next_payment_date"] = contract["due_date"]

        # Click the loan card to open details panel
        try:
            if element_id:
                loan_el = page.query_selector(f"#{element_id}")
                if loan_el:
                    loan_el.click()
                    page.wait_for_timeout(1500)

                    # Click the DETAILS tab
                    details_tab = page.query_selector(
                        '#details-tab, button:has-text("DETAILS"), '
                        '[role="tab"]:has-text("DETAILS")'
                    )
                    if details_tab:
                        details_tab.click()
                        page.wait_for_timeout(1000)

                    # Extract detail fields
                    panel_details = self._extract_contract_details(page)
                    details.update(panel_details)
        except Exception as e:
            log.warning(
                "[%s] Could not expand contract %s: %s",
                self.institution,
                merchant,
                e,
            )

        # Extract remaining balance from details
        balance = None
        for key in ("remaining", "remaining_balance", "amount_due"):
            val = details.get(key, "")
            if val:
                try:
                    balance = float(re.sub(r"[^0-9.]", "", str(val)))
                    break
                except (ValueError, TypeError):
                    continue

        # Persist to DB
        with get_db() as conn:
            # Dynamically create account record for this contract
            conn.execute(
                """
                INSERT OR IGNORE INTO accounts
                    (id, institution_id, name, last4, type)
                VALUES (?, ?, ?, ?, ?)
            """,
                (account_id, self.institution, merchant, contract_slug, "bnpl"),
            )

            if balance is not None:
                record_balance(conn, account_id, balance)

            if details:
                record_loan_details(conn, account_id, details)

            conn.commit()

        # Update result tracking
        self._result_loan_details[contract_slug] = details

        log.info(
            "[%s] BNPL: %s (ID: %s) — balance=%s, %d fields",
            self.institution,
            merchant,
            loan_id,
            f"${balance:,.2f}" if balance else "N/A",
            len(details),
        )
        print(
            f"  🛒  {merchant}: "
            f"{'$' + f'{balance:,.2f}' if balance else 'N/A'} "
            f"({len(details)} detail fields)"
        )

    def _extract_contract_details(self, page: Page) -> dict:
        """Extract loan detail fields from the DETAILS tab panel.

        Affirm's DETAILS tab shows:
          - Purchase price: $X,XXX.XX
          - Interest (X.XX% APR): +$XX.XX
          - Total of payments: $X,XXX.XX
          - Loan ID: XXXX-XXXX
          - Paid to date / Remaining amounts
          - Payments left count
        """
        details = {}
        try:
            raw = page.evaluate("""
                (() => {
                    const data = {};
                    const body = document.body.innerText;

                    // Purchase price
                    const purchaseMatch = body.match(
                        /Purchase\\s+price[\\s\\S]*?\\$([\\d,]+\\.\\d{2})/i
                    );
                    if (purchaseMatch) data.original_amount = '$' + purchaseMatch[1];

                    // Interest + APR
                    const interestMatch = body.match(
                        /Interest\\s*\\(([\\d.]+%\\s*APR)\\)[\\s\\S]*?\\+?\\$([\\d,]+\\.\\d{2})/i
                    );
                    if (interestMatch) {
                        data.apr = interestMatch[1];
                        data.total_interest = '$' + interestMatch[2];
                    }

                    // Total of payments
                    const totalMatch = body.match(
                        /Total\\s+of\\s+payments[\\s\\S]*?\\$([\\d,]+\\.\\d{2})/i
                    );
                    if (totalMatch) data.total_payments = '$' + totalMatch[1];

                    // Remaining balance
                    const remainMatch = body.match(
                        /Remaining[\\s\\S]*?\\$([\\d,]+\\.\\d{2})/i
                    );
                    if (remainMatch) data.remaining = '$' + remainMatch[1];

                    // Paid to date
                    const paidMatch = body.match(
                        /Paid\\s+to\\s+date[\\s\\S]*?\\$([\\d,]+\\.\\d{2})/i
                    );
                    if (paidMatch) data.paid_to_date = '$' + paidMatch[1];

                    // Payments left
                    const leftMatch = body.match(
                        /(\\d+)\\s+payments?\\s+left/i
                    );
                    if (leftMatch) data.remaining_payments = leftMatch[1];

                    // Monthly payment (from amount due)
                    const monthlyMatch = body.match(
                        /\\$([\\d,]+\\.\\d{2})\\s+due/i
                    );
                    if (monthlyMatch) data.monthly_payment = '$' + monthlyMatch[1];

                    return data;
                })()
            """)
            details = raw or {}
        except Exception as e:
            log.debug(
                "[%s] Contract detail extraction failed: %s",
                self.institution,
                e,
            )

        return details

    # ── DB Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _ensure_account(
        conn: sqlite3.Connection, account_id: str, acct: AccountConfig
    ) -> None:
        """Ensure the account record exists in the database.

        Also ensures the institution record exists (prevents FK errors).
        """
        # Ensure institution exists
        conn.execute(
            """
            INSERT OR IGNORE INTO institutions (id, display_name)
            VALUES (?, ?)
        """,
            ("affirm", "Affirm"),
        )

        # Ensure account exists
        conn.execute(
            """
            INSERT OR IGNORE INTO accounts
                (id, institution_id, name, last4, type)
            VALUES (?, ?, ?, ?, ?)
        """,
            (account_id, "affirm", acct.name, acct.last4, acct.type),
        )

    # ── Logout ───────────────────────────────────────────────────────────

    def _perform_logout(self, page: Page) -> None:
        """Log out of Affirm after export.

        Strategy:
          1. Click Profile menu (aria-label="Profile menu")
          2. Click Sign Out link (id="sign-out-link")
          3. Fallback: navigate to /user/signout
        """
        # Strategy 1: Profile menu → Sign Out link
        try:
            profile_btn = page.query_selector('[aria-label="Profile menu"]')
            if profile_btn and profile_btn.is_visible():
                profile_btn.click()
                page.wait_for_timeout(1000)

                signout_link = page.query_selector("#sign-out-link")
                if signout_link and signout_link.is_visible():
                    signout_link.click()
                    try:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    log.info("[%s] Logged out successfully", self.institution)
                    print(f"  🔓  Logged out of {self.display_name}")
                    return
        except Exception as e:
            log.debug("[%s] Menu-based logout failed: %s", self.institution, e)

        # Strategy 2: Selector registry fallback
        try:
            reg = load_selectors()
            signout_group = get_selector_group(
                reg, f"{self.institution}.logout.signout_link"
            )
            signout_el = resilient_find(page, signout_group)
            if signout_el and signout_el.is_visible():
                signout_el.click()
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                log.info("[%s] Logged out via registry selector", self.institution)
                print(f"  🔓  Logged out of {self.display_name}")
                return
        except Exception as e:
            log.debug("[%s] Registry-based logout failed: %s", self.institution, e)

        # Strategy 3: Direct logout URL
        try:
            page.goto(AFFIRM_SIGN_OUT, wait_until="domcontentloaded", timeout=15000)
            log.info("[%s] Logged out via direct URL", self.institution)
            print(f"  🔓  Logged out of {self.display_name} (direct URL)")
        except Exception as e:
            log.warning("[%s] Logout failed: %s", self.institution, e)
