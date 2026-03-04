"""
skills/institution_connector.py — InstitutionConnector (Sentry Finance v2)

Persistent session export automation for financial institutions.

Philosophy:
  - Session reuse over re-login
  - Persistent browser profiles per institution
  - Export, don't scrape (use official CSV/QFX downloads)
  - Human MFA, never bypassed
  - Refresh cadence control (don't hit every institution every run)
  - Minimal detection surface (no stealth tricks, consistency > obfuscation)

Usage:
    from skills.institution_connector import InstitutionConnector

    connector = InstitutionConnector("nfcu", export_url="https://...")
    result = connector.run()
"""

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Generator

import yaml

from playwright.sync_api import TimeoutError
from playwright.sync_api import (
    sync_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
)

from extractors.chrome_cdp import ensure_chrome_debuggable

log = logging.getLogger("sentry.extractors")

BASE_DIR = Path(__file__).resolve().parent.parent
PROFILES_DIR = BASE_DIR / "profiles"
RAW_EXPORTS_DIR = BASE_DIR / "raw_exports"
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
STATE_FILE = BASE_DIR / "state.json"
ACCOUNTS_FILE = BASE_DIR / "accounts.yaml"

# Default refresh intervals (days) per institution
DEFAULT_REFRESH_POLICY = {
    "nfcu": 2,
    "chase": 7,
    "fidelity": 7,
    "tsp": 7,
    "acorns": 7,
    "affirm": 14,
}


# ─── Account Configuration ───────────────────────────────────────────────────


@dataclass
class AccountConfig:
    """Configuration for a single account to export.

    Loaded from accounts.yaml. Controls what data the connector
    pulls for each account.
    """

    name: str
    last4: str
    type: str = "unknown"  # checking, savings, credit_card, loan
    balance: bool = True  # scrape balance from overview
    transactions: bool = False  # download transaction CSV
    loan_details: list[str] = field(default_factory=list)  # loan-specific fields

    @property
    def wants_loan_details(self) -> bool:
        return bool(self.loan_details)

    def __repr__(self):
        parts = []
        if self.balance:
            parts.append("bal")
        if self.transactions:
            parts.append("txn")
        if self.loan_details:
            parts.append(f"loan({len(self.loan_details)})")
        return f"<Account {self.name} [{self.last4}] {'+'.join(parts or ['none'])}>"


def load_account_configs(
    institution: str, config_file: Path = ACCOUNTS_FILE
) -> list[AccountConfig]:
    """Load account configs for an institution from accounts.yaml.

    Returns an empty list if the file doesn't exist or the institution
    isn't configured.
    """
    if not config_file.exists():
        log.warning("No accounts.yaml found at %s", config_file)
        return []

    try:
        data = yaml.safe_load(config_file.read_text())
    except Exception as e:
        log.error("Failed to parse accounts.yaml: %s", e)
        return []

    institution_accounts = data.get(institution, [])
    configs = []

    for entry in institution_accounts:
        export = entry.get("export", {})
        configs.append(
            AccountConfig(
                name=entry["name"],
                last4=entry["last4"],
                type=entry.get("type", "unknown"),
                balance=export.get("balance", True),
                transactions=export.get("transactions", False),
                loan_details=export.get("loan_details", []),
            )
        )

    return configs


# ─── Secret Provider Abstraction ─────────────────────────────────────────────


class SecretProvider(ABC):
    """Abstract base for credential retrieval.

    Connector code should never call os.getenv() directly.
    This layer allows swapping between local .env and GCP Secret Manager
    without changing connector logic.
    """

    @abstractmethod
    def get(self, key: str) -> str | None:
        """Retrieve a secret by key. Returns None if not found."""
        ...


class LocalEnvSecretProvider(SecretProvider):
    """Loads secrets from .env file and/or system environment variables."""

    def __init__(self):
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            log.debug("python-dotenv not installed; using system env only")

    def get(self, key: str) -> str | None:
        return os.environ.get(key)


# Placeholder for future GCP integration (NEXT_STEPS item #5)
# class GCPSecretManagerProvider(SecretProvider):
#     def __init__(self, project_id: str):
#         from google.cloud import secretmanager
#         self.client = secretmanager.SecretManagerServiceClient()
#         self.project_id = project_id
#
#     def get(self, key: str) -> str | None:
#         name = f"projects/{self.project_id}/secrets/{key}/versions/latest"
#         try:
#             response = self.client.access_secret_version(request={"name": name})
#             return response.payload.data.decode("UTF-8")
#         except Exception as e:
#             log.warning("GCP secret lookup failed for %s: %s", key, e)
#             return None


# ─── Refresh State Manager ───────────────────────────────────────────────────


class RefreshState:
    """Tracks the last successful refresh timestamp per institution.

    Persisted to state.json so cadence survives restarts.
    """

    def __init__(self, state_file: Path = STATE_FILE):
        self._path = state_file
        self._data: dict[str, dict] = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError) as e:
                log.warning("Could not read state.json: %s", e)
        return {}

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2, default=str))

    def last_run(self, institution: str) -> datetime | None:
        """Get the timestamp of the last successful run."""
        entry = self._data.get(institution, {})
        ts = entry.get("last_success")
        if ts:
            return datetime.fromisoformat(ts)
        return None

    def is_due(self, institution: str, interval_days: int | None = None) -> bool:
        """Check whether this institution needs a refresh."""
        if interval_days is None:
            interval_days = DEFAULT_REFRESH_POLICY.get(institution, 7)

        last = self.last_run(institution)
        if last is None:
            return True  # Never run before

        return datetime.now() - last > timedelta(days=interval_days)

    def record_success(
        self, institution: str, files_downloaded: list[str] | None = None
    ):
        """Record a successful run."""
        self._data[institution] = {
            "last_success": datetime.now().isoformat(),
            "files": files_downloaded or [],
        }
        self._save()
        log.info(
            "State updated: %s last_success=%s",
            institution,
            self._data[institution]["last_success"],
        )

    def record_failure(self, institution: str, reason: str):
        """Record a failed run (does NOT update last_success)."""
        entry = self._data.setdefault(institution, {})
        entry["last_failure"] = datetime.now().isoformat()
        entry["last_failure_reason"] = reason
        self._save()


# ─── Connector Result ────────────────────────────────────────────────────────


class ConnectorResult:
    """Outcome of a single connector run."""

    def __init__(
        self,
        institution: str,
        status: str,
        files: list[Path] | None = None,
        balances: dict[str, Any] | None = None,
        loan_details: dict[str, dict] | None = None,
        error: str | None = None,
    ):
        self.institution = institution
        self.status = status  # "success" | "skipped" | "error"
        self.files = files or []
        self.balances = balances or {}  # {last4: {"name": ..., "balance": ...}}
        self.loan_details = loan_details or {}  # {last4: {field: value, ...}}
        self.error = error
        self.timestamp = datetime.now()

    def __repr__(self):
        return (
            f"<ConnectorResult {self.institution} "
            f"status={self.status} files={len(self.files)} "
            f"balances={len(self.balances)} loans={len(self.loan_details)}>"
        )


# ─── Base Institution Connector ──────────────────────────────────────────────


class InstitutionConnector(ABC):
    """Base class for all institution connectors.

    Implements the deterministic lifecycle:
      1. Connect to the user's running Chrome via CDP
      2. Open a new tab, navigate to export URL
      3. If redirected to login → navigate to login URL
      4. Wait for Google Password Manager autofill + click submit
      5. Wait for MFA (user provides via authenticator/biometrics)
      6. Trigger CSV/QFX export
      7. Save file with standardized naming
      8. Update state.json
      9. Close the tab (NOT the browser)

    Subclasses must implement:
      - institution:   property returning the institution key (e.g. "nfcu")
      - display_name:  property returning human-readable name
      - export_url:    property returning the target export/activity URL
      - login_url:     property returning the login page URL
      - _perform_login: method to navigate to login and wait for autofill
      - _trigger_export: method to initiate the CSV/QFX download
    """

    def __init__(
        self,
        headless: bool = False,
        secret_provider: SecretProvider | None = None,
        account_configs: list[AccountConfig] | None = None,
        credentials: dict | None = None,
    ):
        self._headless = headless
        self._secrets = secret_provider or LocalEnvSecretProvider()
        self._state = RefreshState()
        self._pw: Playwright | None = None
        self._browser: Browser | None = None

        # Credentials from the Credential Broker (or None for autofill)
        # Format: {"username": "...", "password": "..."}
        self._credentials = credentials

        # Load account configs from YAML (or use provided overrides)
        self._accounts = account_configs or load_account_configs(self.institution)

        # Ensure directories exist
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        self._export_dir.mkdir(parents=True, exist_ok=True)
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Abstract properties (subclasses must define) ─────────────────────

    @property
    @abstractmethod
    def institution(self) -> str:
        """Institution key, e.g. 'nfcu', 'chase'."""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name, e.g. 'Navy Federal Credit Union'."""
        ...

    @property
    @abstractmethod
    def export_url(self) -> str:
        """URL to navigate to for triggering export."""
        ...

    @property
    @abstractmethod
    def login_url(self) -> str:
        """Login page URL."""
        ...

    # ── Derived paths ────────────────────────────────────────────────────

    @property
    def _profile_dir(self) -> Path:
        return PROFILES_DIR / self.institution

    @property
    def _export_dir(self) -> Path:
        return RAW_EXPORTS_DIR / self.institution

    # ── Credential helpers ───────────────────────────────────────────────

    def _get_secret(self, key: str) -> str | None:
        """Retrieve a secret through the provider abstraction."""
        return self._secrets.get(key)

    # ── Persistent Browser Context ───────────────────────────────────────

    @contextmanager
    def _launch(
        self, dev_mode: bool = False
    ) -> Generator[tuple[BrowserContext, Page], None, None]:
        """Launch Chrome and yield (context, page).

        Strategy (in order of preference):
          1. CDP — connect to Chrome running with --remote-debugging-port
             and a dedicated automation profile (--user-data-dir).
             Google Password Manager works via Chrome Sync.
          2. Playwright persistent context — fallback that launches Chrome
             with a local Playwright-managed profile. No Password Manager
             but sessions persist between runs.

        On cleanup, closes ONLY the tab — the Chrome process stays open
        so the next connector can reuse it. The orchestrator calls
        close_chrome() after all institutions are done.
        """
        self._pw = sync_playwright().start()
        page = None
        self._launched_persistent = False

        try:
            # ── Strategy 1: CDP (automation profile) ──────────────────
            endpoint = ensure_chrome_debuggable()
            if endpoint:
                try:
                    self._browser = self._pw.chromium.connect_over_cdp(endpoint)
                    context = self._browser.contexts[0]
                    page = context.new_page()
                    log.info(
                        "[%s] Connected to Chrome via CDP (new tab opened)",
                        self.institution,
                    )
                    yield context, page
                    return
                except Exception as cdp_err:
                    log.warning(
                        "[%s] CDP connect failed (%s), trying fallback",
                        self.institution,
                        cdp_err,
                    )

            # ── Strategy 2: Playwright persistent context (fallback) ──
            log.info(
                "[%s] Falling back to Playwright persistent profile", self.institution
            )
            work_profile = self._profile_dir / "playwright"
            work_profile.mkdir(parents=True, exist_ok=True)

            page = None  # Ensure page is defined in case context creation fails
            context = self._pw.chromium.launch_persistent_context(
                str(work_profile),
                channel="chrome",
                headless=self._headless,
                accept_downloads=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            self._launched_persistent = True
            page = context.pages[0] if context.pages else context.new_page()
            log.info(
                "[%s] Launched Chrome with Playwright profile (no "
                "Password Manager — log in manually)",
                self.institution,
            )

            yield context, page

        finally:
            if dev_mode:
                log.info(
                    "[%s] Dev mode active — leaving browser session open",
                    self.institution,
                )
                return

            if self._launched_persistent:
                # Fallback path: we own the whole context, close it
                try:
                    context.close()
                except Exception as e:
                    log.debug("Ignored exception: %s", e)
            else:
                # CDP path: only close our tab — leave Chrome running
                # for the next connector. The orchestrator calls
                # close_chrome() after all institutions finish.
                if page:
                    try:
                        page.close()
                    except Exception as e:
                        log.debug("Ignored exception: %s", e)
            if self._pw:
                self._pw.stop()
            log.info("[%s] Browser session closed", self.institution)

    @contextmanager
    def open_transient_tab(
        self, context: BrowserContext, trigger=None
    ) -> Generator[Page, None, None]:
        """Open a temporary page and ensure it is fully closed on exit.

        Use this whenever a connector needs to interact with a new tab.
        If the tab is opened via a UI action (e.g., clicking a button),
        pass the action as a lambda to the `trigger` parameter.

        Usage:
            with self.open_transient_tab(context, trigger=lambda: btn.click()) as temp_page:
                temp_page.wait_for_load_state("networkidle")
                # ...
        """
        if trigger:
            with context.expect_page(timeout=15000) as page_info:
                trigger()
            page = page_info.value
        else:
            page = context.new_page()

        try:
            yield page
        finally:
            try:
                page.close()
            except Exception as e:
                log.debug("Ignored exception: %s", e)

    # ── Session Validation ───────────────────────────────────────────────

    def _is_session_valid(self, page: Page) -> bool:
        """Check if the current session is still authenticated.

        Navigate directly to the export URL and verify we actually
        landed on an authenticated page. Checks:
          1. URL — redirected to login/auth page?
          2. HTTP status — got a 4xx/5xx error page?
          3. Page content — contains error indicators?
        """
        try:
            response = page.goto(
                self.export_url, wait_until="domcontentloaded", timeout=30000
            )
            # Wait for redirects to settle
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception as e:
                log.debug("Wait timed out: %s", e)

            # Check 1: URL contains login/auth keywords
            current = page.url.lower()
            if any(kw in current for kw in ("signin", "login", "auth", "sso")):
                log.info("[%s] Session expired — redirected to login", self.institution)
                return False

            # Check 2: HTTP response status (404, 403, 500, etc.)
            if response and response.status >= 400:
                log.info(
                    "[%s] Session check got HTTP %d — treating as invalid",
                    self.institution,
                    response.status,
                )
                self._screenshot(page, "session_check_error")
                return False

            # Check 3: Page body contains error indicators
            try:
                body_text = page.inner_text("body").strip().lower()
                error_indicators = [
                    "not found",
                    "404",
                    "403",
                    "forbidden",
                    "access denied",
                    "session expired",
                    "timed out",
                    "unavailable",
                    "something went wrong",
                ]
                if len(body_text) < 200:  # Suspiciously short page
                    for indicator in error_indicators:
                        if indicator in body_text:
                            log.info(
                                "[%s] Session check found '%s' in page body",
                                self.institution,
                                indicator,
                            )
                            self._screenshot(page, "session_check_error")
                            return False
            except Exception as e:
                log.debug(
                    "Ignored exception: %s", e
                )  # If we can't read the body, don't fail the check

            log.info("[%s] Session valid — skipping login", self.institution)
            return True

        except Exception as e:
            log.warning("[%s] Session check failed: %s", self.institution, e)
            return False

    # ── Login (subclass implements the specifics) ────────────────────────

    @abstractmethod
    def _perform_login(self, page: Page, credentials: dict | None = None) -> bool:
        """Navigate to login and authenticate.

        This method should:
          1. Navigate to self.login_url
          2. If credentials are provided (from Credential Broker), fill
             username/password fields directly
          3. Otherwise, wait for Google Password Manager to autofill
          4. Click the submit/login button
          5. Return True (MFA is handled by the lifecycle's _wait_for_mfa)

        Args:
            page: Playwright Page object.
            credentials: Optional dict with 'username' and 'password'
                         from the Credential Broker. If None, fall back
                         to Password Manager autofill.
        """
        ...

    def _wait_for_mfa(self, page: Page, timeout_seconds: int = 300):
        """Auto-detect login/MFA completion by polling URL and page content.

        Polls every 2 seconds until either:
          - The URL no longer contains login/MFA keywords, OR
          - The page DOM indicates post-login content (login form gone,
            account elements present, etc.)

        Some SPAs (like NFCU) keep the same URL after login, so we must
        also check the page content. Subclasses can override _is_post_login()
        for institution-specific detection.
        """
        # Quick check: already past login?
        if self._is_post_login(page):
            return

        print()
        print(f"  ┌─────────────────────────────────────────────────┐")
        print(f"  │  [{self.display_name}] Waiting for login/MFA...  │")
        print(f"  │                                                  │")
        print(f"  │  Complete authentication in the browser.         │")
        print(f"  │  The script will continue automatically.         │")
        print(f"  └─────────────────────────────────────────────────┘")
        print()

        polls = timeout_seconds // 2
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

            # Progress indicator every 30 seconds
            if i > 0 and i % 15 == 0:
                elapsed = i * 2
                print(f"  ⏳  Still waiting... ({elapsed}s / {timeout_seconds}s)")

        log.warning(
            "[%s] MFA wait timed out after %ds", self.institution, timeout_seconds
        )

    def _is_post_login(self, page: Page) -> bool:
        """Detect whether the user has completed authentication.

        Uses two strategies:
          1. URL check — URL no longer contains login/MFA keywords
          2. DOM check — login form elements are gone and the page has
             substantive content (accounts, balances, etc.)

        Subclasses should override this for institution-specific detection
        (e.g., NFCU's SPA never changes the URL).
        """
        login_keywords = (
            "signin",
            "login",
            "verify",
            "mfa",
            "challenge",
            "otp",
            "logon",
        )

        current_url = page.url.lower()

        # Strategy 1: URL changed away from login keywords
        if not any(kw in current_url for kw in login_keywords):
            return True

        # Strategy 2: DOM-based detection — login form is gone AND
        # page has substantial content (not just the login form)
        try:
            # If a password field is still visible, we're still on login
            pw_field = page.query_selector('input[type="password"]:visible')
            if pw_field:
                return False

            # Check if the page body has enough content to be a dashboard
            body_text = page.inner_text("body").strip()
            if len(body_text) > 500:
                # Look for dashboard-like content
                lower_body = body_text.lower()
                dashboard_markers = (
                    "account",
                    "balance",
                    "transaction",
                    "checking",
                    "savings",
                    "credit",
                    "mortgage",
                    "loan",
                    "welcome",
                )
                if any(marker in lower_body for marker in dashboard_markers):
                    log.info(
                        "[%s] Post-login detected via DOM (no password "
                        "field, dashboard content found)",
                        self.institution,
                    )
                    return True
        except Exception as e:
            log.debug("DOM-based login check failed: %s", e)

        return False

    # ── Export (subclass implements the specifics) ────────────────────────

    @abstractmethod
    def _trigger_export(self, page: Page, accounts: list[AccountConfig]) -> list[Path]:
        """Execute the export process for the configured accounts.

        This method receives the list of AccountConfig objects from
        accounts.yaml. The subclass should:
          1. Scrape balances from the overview page (for accts with balance=True)
          2. Navigate to each account and download CSV (for accts with transactions=True)
          3. Extract loan details from detail pages (for accts with loan_details)

        Store results in self._result_balances and self._result_loan_details.
        Return a list of downloaded file paths.

        PAGE LIFECYCLE CONTRACT (resource-session-management.md):
          - The `page` argument is owned by the base class _launch() context manager.
            Do NOT close it here — it will be closed in the finally block.
          - If you open additional pages (e.g., popups, new tabs), you MUST close
            them in a try/finally block before returning:

              extra = context.new_page()
              try:
                  ...
              finally:
                  extra.close()

          - Never close the browser itself — it is a persistent singleton.
          - Never spawn threads or subprocesses from within this method.
        """
        ...

    def _perform_logout(self, page: Page) -> None:
        """Log out of the institution after export completes.

        Default is a no-op.  Subclasses should override to navigate
        to the institution's sign-out page or click the sign-out link.
        Failures here are caught by the caller and never block the
        pipeline.
        """
        pass

    def _safe_logout(self, page: Page) -> None:
        """Attempt logout, swallowing any exceptions.

        Called by the base lifecycle — subclasses override
        ``_perform_logout`` instead of this method.

        Before logout, dismisses any popups/modals/dialogs that
        could block the logout UI interaction.
        """
        try:
            # Dismiss any blocking popups before logout
            self._dismiss_blocking_popups(page)
            self._perform_logout(page)
        except Exception as e:
            log.warning("[%s] Logout failed (non-fatal): %s", self.institution, e)
            print(f"  ⚠️   Logout failed (non-fatal): {e}")

    def _dismiss_blocking_popups(self, page: Page) -> None:
        """Dismiss modals, overlays, and JS dialogs that may block logout.

        Handles:
          1. JavaScript dialogs (alert / confirm / prompt / beforeunload)
          2. Modal overlays with close / dismiss / cancel buttons
          3. Cookie banners, feedback surveys, etc.
        """
        # 1. Handle any pending JS dialog
        page.on("dialog", lambda d: d.dismiss())

        # 2. Try to close visible modal overlays
        dismiss_selectors = [
            '[aria-label="Close"]',
            '[aria-label="Dismiss"]',
            "button.close",
            'button:has-text("Close")',
            'button:has-text("Dismiss")',
            'button:has-text("Cancel")',
            'button:has-text("No Thanks")',
            'button:has-text("Not Now")',
            'button:has-text("Maybe Later")',
            'button:has-text("Skip")',
            ".modal-close",
            'div[role="dialog"] button[aria-label="Close"]',
        ]
        for sel in dismiss_selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.click()
                    log.info(
                        "[%s] Dismissed popup before logout: %s", self.institution, sel
                    )
                    page.wait_for_timeout(500)
                    break
            except Exception:
                continue

    # ── Screenshot helper ────────────────────────────────────────────────

    def _screenshot(self, page: Page, label: str) -> Path:
        """Capture a timestamped screenshot for debugging."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = SCREENSHOTS_DIR / f"{self.institution}_{label}_{ts}.png"
        page.screenshot(path=str(path), full_page=True)
        log.info("[%s] Screenshot: %s", self.institution, path.name)
        return path

    # ── Main Lifecycle ───────────────────────────────────────────────────

    def run(
        self,
        force: bool = False,
        credentials: dict | None = None,
        dev_mode: bool = False,
    ) -> ConnectorResult:
        """Execute the full connector lifecycle.

        Args:
            force: If True, ignore refresh cadence and run anyway.
            credentials: Optional dict from Credential Broker with
                         'username' and 'password'. Overrides any
                         credentials set in __init__.
            dev_mode: If True, do not tear down the browser session on exit.

        Returns:
            ConnectorResult with status, downloaded files, or error.
        """
        # Merge credentials (run-time takes precedence over init-time)
        creds = credentials or self._credentials
        self._force_run = force

        # ── Cadence check ────────────────────────────────────────────
        if not force and not self._state.is_due(self.institution):
            last = self._state.last_run(self.institution)
            print(
                f"  ⏭️   [{self.display_name}] Not due yet "
                f"(last run: {last:%Y-%m-%d %H:%M})"
            )
            return ConnectorResult(self.institution, "skipped")

        print(f"\n  ── {self.display_name} {'─' * (40 - len(self.display_name))}")

        # Print account config summary
        if self._accounts:
            print(f"  📋  {len(self._accounts)} accounts configured:")
            for acct in self._accounts:
                print(f"       • {acct}")
        else:
            print(f"  ⚠  No accounts configured in accounts.yaml")

        # Initialize result storage (subclass populates these)
        self._result_balances: dict[str, Any] = {}
        self._result_loan_details: dict[str, dict] = {}

        try:
            with self._launch(dev_mode=dev_mode) as (context, page):
                # ── Step 1: Session validation ───────────────────────
                if not self._is_session_valid(page):
                    if creds:
                        print(
                            f"  🔐  Logging in to {self.display_name} (broker credentials)..."
                        )
                    else:
                        print(
                            f"  🔐  Logging in to {self.display_name} (Password Manager)..."
                        )
                    success = self._perform_login(page, credentials=creds)
                    if not success:
                        self._screenshot(page, "login_failed")
                        self._state.record_failure(self.institution, "login_failed")
                        return ConnectorResult(
                            self.institution, "error", error="Login failed"
                        )

                    # ── Step 2: MFA wait ─────────────────────────────
                    self._wait_for_mfa(page)
                else:
                    print(f"  ✅  Session valid — no login needed")

                # ── Step 3: Export per account config ─────────────────
                print(f"  📥  Starting export...")
                try:
                    files = self._trigger_export(page, self._accounts)
                except Exception as e:
                    self._screenshot(page, "export_failed")
                    self._state.record_failure(self.institution, f"export_failed: {e}")
                    # Still attempt logout even after export failure
                    if not dev_mode:
                        self._safe_logout(page)
                    return ConnectorResult(
                        self.institution, "error", error=f"Export failed: {e}"
                    )

                # ── Step 4: Record success ───────────────────────────
                # Success if we got files OR balances (balance-only runs
                # are valid even without CSV downloads)
                has_data = files or self._result_balances or self._result_loan_details

                if not has_data:
                    self._screenshot(page, "no_data")
                    self._state.record_failure(self.institution, "no_data_collected")
                    if not dev_mode:
                        self._safe_logout(page)
                    return ConnectorResult(
                        self.institution, "error", error="No data collected"
                    )

                file_names = [f.name for f in files] if files else []
                self._state.record_success(self.institution, file_names)

                # Print summary
                if files:
                    print(f"  📄  {len(files)} file(s) downloaded:")
                    for f in files:
                        print(f"       • {f.name}")
                if self._result_balances:
                    print(f"  💰  {len(self._result_balances)} balance(s) scraped:")
                    for last4, info in self._result_balances.items():
                        print(
                            f"       • [{last4}] {info.get('name', '?')}: "
                            f"{info.get('balance', '?')}"
                        )
                if self._result_loan_details:
                    print(f"  🏦  {len(self._result_loan_details)} loan detail(s):")
                    for last4, details in self._result_loan_details.items():
                        print(f"       • [{last4}] {len(details)} fields")

                # ── Step 5: Logout ────────────────────────────────────
                if not dev_mode:
                    self._safe_logout(page)

                return ConnectorResult(
                    self.institution,
                    "success",
                    files=files or [],
                    balances=self._result_balances,
                    loan_details=self._result_loan_details,
                )

        except Exception as e:
            log.error("[%s] Unexpected error: %s", self.institution, e)
            self._state.record_failure(self.institution, str(e))
            return ConnectorResult(self.institution, "error", error=str(e))


# ─── Orchestrator ────────────────────────────────────────────────────────────


def run_connectors(
    connectors: list[InstitutionConnector], force: bool = False
) -> list[ConnectorResult]:
    """Run multiple connectors, respecting each institution's refresh cadence.

    Args:
        connectors: List of InstitutionConnector instances.
        force: If True, run all connectors regardless of cadence.

    Returns:
        List of ConnectorResult objects.
    """
    results = []
    print(f"\n  🚀  InstitutionConnector — {datetime.now():%Y-%m-%d %H:%M}")
    print(f"  📋  Connectors: {', '.join(c.display_name for c in connectors)}")
    if force:
        print(f"  ⚡  Force mode — ignoring refresh cadence")
    print()

    for connector in connectors:
        result = connector.run(force=force)
        results.append(result)

    # Summary
    print(f"\n  {'─' * 50}")
    success = sum(1 for r in results if r.status == "success")
    skipped = sum(1 for r in results if r.status == "skipped")
    errors = sum(1 for r in results if r.status == "error")
    print(f"  ✅ {success} succeeded  ⏭️ {skipped} skipped  ❌ {errors} errors")
    print()

    return results
