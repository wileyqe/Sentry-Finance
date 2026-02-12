"""
extractors/browser_manager.py — Playwright browser lifecycle and anti-detection.

Provides a managed browser context with:
  - Stealth configuration to minimize bot detection
  - Download directory monitoring
  - Human-in-the-loop pause/resume for 2FA and CAPTCHAs
  - Random delays between actions
  - Screenshot capture for debugging

Usage:
    from extractors.browser_manager import BrowserManager
    from extractors.session_manager import SessionManager

    sm = SessionManager()
    bm = BrowserManager(download_dir=Path("downloads"))

    with bm.launch() as (browser, context, page):
        # If we have a saved session, restore it
        if sm.has_session("nfcu"):
            context = bm.restore_session(browser, sm.load("nfcu"))
            page = context.pages[0] if context.pages else context.new_page()

        page.goto("https://example.com")
        bm.random_delay(1, 3)  # Human-like pause

        # Wait for human to complete 2FA
        bm.wait_for_human("Complete 2FA, then press Enter")

        # Save session after login
        sm.save_from_context("nfcu", context)
"""
import logging
import random
import time
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from playwright.sync_api import (
    sync_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
)

log = logging.getLogger("antigravity")

# ── Stealth Configuration ────────────────────────────────────────────────────
# These settings make the browser appear more like a real user's browser.
# They won't defeat enterprise-grade fingerprinting (Akamai, etc.) but help
# with basic bot detection.

STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-infobars",
    "--no-sandbox",
]

# Realistic viewport and user agent
DEFAULT_VIEWPORT = {"width": 1440, "height": 900}
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Timezone and locale to match a real user
DEFAULT_LOCALE = "en-US"
DEFAULT_TIMEZONE = "America/New_York"


class BrowserManager:
    """Manages Playwright browser lifecycle with anti-detection and utilities.

    Key features:
      - Stealth browser configuration
      - Download directory monitoring
      - Human-in-the-loop for 2FA / CAPTCHA
      - Random delays for human-like behavior
      - Screenshot capture for debugging
    """

    def __init__(
        self,
        download_dir: Path | None = None,
        screenshot_dir: Path | None = None,
        headless: bool = False,
        slow_mo: int = 50,
    ):
        """
        Args:
            download_dir: Where downloaded files land. Created if needed.
            screenshot_dir: Where debug screenshots are saved.
            headless: Run browser without visible window (not recommended for
                      sites with bot detection — use headed mode).
            slow_mo: Milliseconds to slow down every Playwright action (helps
                     with bot detection and debugging).
        """
        base = Path(__file__).resolve().parent.parent
        self._download_dir = download_dir or base / "downloads"
        self._screenshot_dir = screenshot_dir or base / "screenshots"
        self._headless = headless
        self._slow_mo = slow_mo

        # Ensure directories exist
        self._download_dir.mkdir(parents=True, exist_ok=True)
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def download_dir(self) -> Path:
        return self._download_dir

    @property
    def screenshot_dir(self) -> Path:
        return self._screenshot_dir

    # ── Lifecycle ─────────────────────────────────────────────────────────

    @contextmanager
    def launch(self, storage_state: dict | None = None) -> Generator[
        tuple[Browser, BrowserContext, Page], None, None
    ]:
        """Launch a browser with stealth config as a context manager.

        Args:
            storage_state: Optional Playwright storage state dict to restore
                           a previous session (cookies, localStorage).

        Yields:
            (browser, context, page) tuple.

        Example:
            with bm.launch() as (browser, context, page):
                page.goto("https://...")
        """
        self._playwright = sync_playwright().start()

        try:
            self._browser = self._playwright.chromium.launch(
                headless=self._headless,
                slow_mo=self._slow_mo,
                args=STEALTH_ARGS,
            )

            context_kwargs: dict[str, Any] = {
                "viewport": DEFAULT_VIEWPORT,
                "user_agent": DEFAULT_USER_AGENT,
                "locale": DEFAULT_LOCALE,
                "timezone_id": DEFAULT_TIMEZONE,
                "accept_downloads": True,
                "ignore_https_errors": True,
            }

            if storage_state:
                context_kwargs["storage_state"] = storage_state

            context = self._browser.new_context(**context_kwargs)

            # Inject stealth scripts to hide automation indicators
            context.add_init_script("""
                // Remove navigator.webdriver flag
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });

                // Fix Chrome runtime
                window.chrome = {
                    runtime: {},
                    loadTimes: function() {},
                    csi: function() {},
                    app: {}
                };

                // Fix permissions
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) =>
                    parameters.name === 'notifications'
                        ? Promise.resolve({ state: Notification.permission })
                        : originalQuery(parameters);

                // Fix plugins length
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });

                // Fix languages
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en']
                });
            """)

            page = context.new_page()

            log.info("Browser launched (headless=%s, slow_mo=%dms)",
                     self._headless, self._slow_mo)

            yield self._browser, context, page

        finally:
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
            log.info("Browser closed")

    def restore_session(self, browser: Browser,
                        storage_state: dict) -> BrowserContext:
        """Create a new context with a restored session.

        Use this when you want to swap from a fresh context to one with
        saved cookies/localStorage.

        Returns the new BrowserContext (caller should create a page from it).
        """
        context = browser.new_context(
            viewport=DEFAULT_VIEWPORT,
            user_agent=DEFAULT_USER_AGENT,
            locale=DEFAULT_LOCALE,
            timezone_id=DEFAULT_TIMEZONE,
            accept_downloads=True,
            storage_state=storage_state,
        )
        log.info("Restored session with %d cookies",
                 len(storage_state.get("cookies", [])))
        return context

    # ── Human-in-the-Loop ─────────────────────────────────────────────────

    @staticmethod
    def wait_for_human(prompt: str = "Complete the action, then press Enter",
                       timeout: float | None = None) -> bool:
        """Pause execution and wait for human input.

        Used for 2FA, CAPTCHAs, or any step requiring manual intervention.

        Args:
            prompt: Message to display to the user.
            timeout: Max seconds to wait (None = wait forever).

        Returns:
            True if human responded, False if timed out.
        """
        print(f"\n  ⏸️   {prompt}")
        print(f"  👉  Press ENTER when ready to continue...\n")

        if timeout is None:
            input()
            return True

        import select
        import sys

        # On Windows, select doesn't work on stdin, so we just use input()
        try:
            input()
            return True
        except EOFError:
            return False

    # ── Delays ────────────────────────────────────────────────────────────

    @staticmethod
    def random_delay(min_seconds: float = 0.5, max_seconds: float = 2.0):
        """Sleep for a random duration to simulate human behavior.

        Adds slight randomness to avoid detection patterns.
        """
        delay = random.uniform(min_seconds, max_seconds)
        time.sleep(delay)

    @staticmethod
    def type_like_human(page: Page, selector: str, text: str,
                        min_delay: int = 50, max_delay: int = 150):
        """Type text character by character with random delays.

        More human-like than Playwright's default fill().
        """
        page.click(selector)
        for char in text:
            page.keyboard.type(char, delay=random.randint(min_delay, max_delay))

    # ── Download Monitoring ───────────────────────────────────────────────

    def wait_for_download(self, page: Page, trigger_action,
                          timeout: float = 30.0) -> Path | None:
        """Wait for a file download triggered by an action.

        Args:
            page: Active Playwright page.
            trigger_action: Callable that triggers the download (e.g., clicking
                            a download button). Called with no args.
            timeout: Max seconds to wait for download to complete.

        Returns:
            Path to the downloaded file, or None if download failed/timed out.
        """
        try:
            with page.expect_download(timeout=timeout * 1000) as download_info:
                trigger_action()

            download = download_info.value
            suggested_name = download.suggested_filename
            target = self._download_dir / suggested_name

            # Save to our download directory
            download.save_as(str(target))
            log.info("Downloaded: %s (%s)", suggested_name, target)
            return target

        except Exception as e:
            log.error("Download failed: %s", e)
            self.screenshot(page, "download_failed")
            return None

    def list_downloads(self) -> list[Path]:
        """List all files currently in the download directory."""
        return sorted(self._download_dir.iterdir())

    def clear_downloads(self):
        """Remove all files from the download directory."""
        for f in self._download_dir.iterdir():
            if f.is_file():
                f.unlink()
        log.info("Cleared download directory")

    # ── Screenshots ───────────────────────────────────────────────────────

    def screenshot(self, page: Page, name: str = "debug") -> Path:
        """Capture a screenshot for debugging.

        Args:
            page: Active Playwright page.
            name: Base name for the screenshot file.

        Returns:
            Path to the saved screenshot.
        """
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{name}_{timestamp}.png"
        path = self._screenshot_dir / filename
        page.screenshot(path=str(path), full_page=True)
        log.info("Screenshot saved: %s", path.name)
        return path

    # ── Navigation Helpers ────────────────────────────────────────────────

    @staticmethod
    def safe_goto(page: Page, url: str, wait_until: str = "domcontentloaded",
                  timeout: float = 30.0) -> bool:
        """Navigate to a URL with error handling.

        Returns True if navigation succeeded, False otherwise.
        """
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout * 1000)
            log.info("Navigated to %s", url)
            return True
        except Exception as e:
            log.error("Navigation failed for %s: %s", url, e)
            return False

    @staticmethod
    def wait_for_element(page: Page, selector: str,
                         timeout: float = 10.0) -> bool:
        """Wait for an element to appear on the page.

        Returns True if found, False if timed out.
        """
        try:
            page.wait_for_selector(selector, timeout=timeout * 1000)
            return True
        except Exception:
            log.warning("Element not found: %s (timeout: %ss)", selector, timeout)
            return False

    def __repr__(self):
        return (f"<BrowserManager headless={self._headless} "
                f"downloads={self._download_dir}>")
