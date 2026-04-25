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
from extractors.nfcu._login_mixin import NFCULoginMixin
from extractors.nfcu._balances_mixin import NFCUBalancesMixin
from extractors.nfcu._download_mixin import NFCUDownloadMixin


class NFCUConnector(NFCULoginMixin, NFCUBalancesMixin, NFCUDownloadMixin, InstitutionConnector):
    """Navy Federal Credit Union connector.

    Implements the 3-phase export process:
      Phase 1: Scrape balances from the accounts overview page
      Phase 2: Download transaction CSVs for each configured account
      Phase 3: Extract loan details from account detail pages
    """

    @property
    def institution(self) -> str:
        return "nfcu"

    @property
    def display_name(self) -> str:
        return "Navy Federal Credit Union"

    @property
    def export_url(self) -> str:
        return "https://digitalomni.navyfederal.org/accounts"

    @property
    def login_url(self) -> str:
        return "https://digitalomni.navyfederal.org/signin/"

    def _is_session_valid(self, page) -> bool:
        """Check if we're already authenticated with NFCU.

        Navigates to the login URL (SPA root) and checks DOM to see if
        the login form is present (not authenticated) or if dashboard
        content is showing (authenticated).

        Overrides the base class because:
          - export_url (/accounts) returns 404 when accessed directly
          - NFCU's SPA uses the same URL (/signin/) for both login
            and post-login dashboard views
        """
        try:
            response = page.goto(
                self.login_url, wait_until="domcontentloaded", timeout=30000
            )
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception as e:
                log.debug("Wait timed out: %s", e)

            # Give the SPA a moment to render
            page.wait_for_timeout(2000)

            # Check if we're on the dashboard (already logged in)
            if self._is_post_login(page):
                log.info("[%s] Session valid — already on dashboard", self.institution)
                return True

            log.info("[%s] Session not valid — login form detected", self.institution)
            return False

        except Exception as e:
            log.warning("[%s] Session check failed: %s", self.institution, e)
            return False

    def _is_post_login(self, page) -> bool:
        """Detect NFCU post-login state via DOM inspection.

        NFCU's SPA keeps the URL at /signin/ even after login.
        We detect the authenticated state by checking:
          1. No visible password field (login form is gone)
          2. Page body contains NFCU account-related content
        """
        try:
            # If a password field is visible, we're on the login form
            pw_visible = page.query_selector('input[type="password"]:visible')
            if pw_visible:
                return False

            # Check page body for dashboard/account content
            body = page.inner_text("body").strip().lower()
            if len(body) < 200:
                return False  # Too short to be a dashboard

            # NFCU dashboard markers
            markers = (
                "checking",
                "savings",
                "credit card",
                "mortgage",
                "loan",
                "available balance",
                "current balance",
                "account ending in",
                "my accounts",
                "account summary",
            )
            if any(m in body for m in markers):
                log.info(
                    "[%s] Dashboard content detected (post-login)", self.institution
                )
                return True
        except Exception as e:
            log.debug("NFCU post-login check error: %s", e)

        return False
