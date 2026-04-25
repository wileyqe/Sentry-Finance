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
from extractors.chase._login_mixin import ChaseLoginMixin
from extractors.chase._balances_mixin import ChaseBalancesMixin
from extractors.chase._download_mixin import ChaseDownloadMixin


class ChaseConnector(ChaseLoginMixin, ChaseBalancesMixin, ChaseDownloadMixin, InstitutionConnector):
    """Chase Bank connector.

    Implements a 4-phase export process:
      Phase 1: Scrape balances from the accounts dashboard
      Phase 2: Download transaction CSVs for each configured account
      Phase 3: Scrape per-account detail fields (APR, credit limits,
               APY, statement balances, etc.) via Account Details view
      Phase 4: Scrape VantageScore from Chase Credit Journey
    """

    @property
    def institution(self) -> str:
        return "chase"

    @property
    def display_name(self) -> str:
        return "Chase"

    @property
    def export_url(self) -> str:
        return "https://secure.chase.com/web/auth/#/dashboard"

    @property
    def login_url(self) -> str:
        return "https://secure.chase.com"

    def _is_session_valid(self, page) -> bool:
        """Check if the Chase session is still authenticated.

        Override needed because Chase's dashboard URL contains '/auth/'
        which the base class interprets as a login redirect.
        """
        try:
            response = page.goto(
                self.export_url, wait_until="domcontentloaded", timeout=30000
            )
            # Wait for Chase redirects to settle
            try:
                # We do not wait for a full networkidle because Chase's SPA constantly streams metrics
                page.wait_for_timeout(2000)
            except Exception as e:
                log.debug("Wait timed out: %s", e)

            current = page.url.lower()
            print(f"  🔍  Session check landed on: {current[:80]}")
            self._screenshot(page, "session_check", error_only=True)

            # If we landed on the system requirements page or main site,
            # session is invalid
            if "system-requirements" in current:
                log.info(
                    "[%s] Redirected to system requirements — session invalid",
                    self.institution,
                )
                return False

            if current.startswith("https://www.chase.com"):
                # Redirected away from secure.chase.com — not authenticated
                if "secure.chase.com" not in current:
                    log.info(
                        "[%s] Redirected to public site — session invalid",
                        self.institution,
                    )
                    return False

            # If we end up on a login/signin page (not the dashboard)
            # Chase uses /logon/ for their actual signin SPA
            if any(kw in current for kw in ("signin", "login", "sso", "logon")):
                log.info("[%s] Session expired — redirected to login", self.institution)
                return False

            # HTTP error status
            if response and response.status >= 400:
                log.info(
                    "[%s] Session check got HTTP %d", self.institution, response.status
                )
                return False

            # If we're on secure.chase.com with dashboard in the URL,
            # verify the SPA has actually rendered account content.
            # (A blank page means no auth tokens — session is invalid.)
            if "secure.chase.com" in current and "dashboard" in current:
                # Wait up to 10s for content to appear
                for _ in range(5):
                    try:
                        body = page.inner_text("body").strip()
                        if re.search(r"\$[\d,]+\.\d{2}", body) or len(body) > 500:
                            log.info(
                                "[%s] Session valid — skipping login", self.institution
                            )
                            return True
                    except Exception as e:
                        log.debug("Ignored exception: %s", e)
                    page.wait_for_timeout(2000)

                # Page stayed blank — session is invalid
                log.info(
                    "[%s] Dashboard URL valid but page blank — session invalid",
                    self.institution,
                )
                self._screenshot(page, "session_blank")
                return False

            # Otherwise, assume invalid
            log.info(
                "[%s] Unexpected URL after session check: %s", self.institution, current
            )
            return False

        except Exception as e:
            log.warning("[%s] Session check failed: %s", self.institution, e)
            return False
