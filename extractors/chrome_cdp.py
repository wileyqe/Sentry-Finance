"""
extractors/chrome_cdp.py — Chrome DevTools Protocol connection helper.

Ensures Chrome is running with remote debugging enabled using a
**dedicated automation profile** (separate --user-data-dir).

Why a separate profile?
  Chrome blocks --remote-debugging-port on the default User Data directory.
  App-Bound Encryption prevents copying the default profile elsewhere.
  The solution: a persistent secondary profile where the user signs into
  Google once, enabling Chrome Sync to bring over saved passwords and
  Password Manager autofill.

First-time setup:
  1. Run:  chrome.exe --remote-debugging-port=9222
              --user-data-dir="C:\\ChromeAutomationProfile"
  2. In the Chrome window that opens, sign into your Google account
  3. Enable Chrome Sync (passwords, autofill, etc.)
  4. From then on, this module handles everything automatically

Usage:
    from extractors.chrome_cdp import ensure_chrome_debuggable

    endpoint = ensure_chrome_debuggable()
    # Returns "http://localhost:9222" or None
"""

import json
import logging
import os
import shutil
import subprocess
import time
import urllib.request
import urllib.error

log = logging.getLogger("sentry.extractors.cdp")

DEFAULT_PORT = 9222

# Dedicated automation profile — NOT the default Chrome User Data dir
AUTOMATION_PROFILE_DIR = os.environ.get(
    "CHROME_AUTOMATION_PROFILE", r"C:\ChromeAutomationProfile"
)

# Common Chrome paths on Windows
_CHROME_PATHS = [
    os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
]


def _find_chrome() -> str | None:
    """Locate the Chrome executable on this system."""
    chrome_on_path = shutil.which("chrome") or shutil.which("google-chrome")
    if chrome_on_path:
        return chrome_on_path

    for path in _CHROME_PATHS:
        if os.path.isfile(path):
            return path

    return None


def _is_chrome_debuggable(port: int = DEFAULT_PORT) -> bool:
    """Check if Chrome is listening on the debug port."""
    try:
        url = f"http://localhost:{port}/json/version"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
            browser = data.get("Browser", "unknown")
            log.info("Chrome debug port active: %s", browser)
            return True
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return False


def _launch_chrome_with_debugging(port: int = DEFAULT_PORT) -> bool:
    """Launch Chrome with remote debugging using the automation profile.

    Uses a dedicated --user-data-dir so that --remote-debugging-port
    is not blocked by Chrome's default-directory restriction.
    """
    chrome_path = _find_chrome()
    if not chrome_path:
        log.error("Could not find Chrome installation")
        return False

    profile_dir = AUTOMATION_PROFILE_DIR
    is_first_run = not os.path.isdir(profile_dir)

    log.info(
        "Launching Chrome with --remote-debugging-port=%d --user-data-dir=%s",
        port,
        profile_dir,
    )

    subprocess.Popen(
        [
            chrome_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for Chrome to start accepting connections
    for i in range(15):
        time.sleep(1)
        if _is_chrome_debuggable(port):
            if is_first_run:
                _print_first_run_setup()
            return True

    log.error("Chrome launched but debug port never became available")
    return False


def _print_first_run_setup():
    """Print one-time setup instructions for the automation profile."""
    print()
    print("  ┌─────────────────────────────────────────────────┐")
    print("  │  🆕  First-Time Automation Profile Setup        │")
    print("  │                                                 │")
    print("  │  A new Chrome window opened with a fresh        │")
    print("  │  profile. To enable Password Manager:           │")
    print("  │                                                 │")
    print("  │  1. Sign into your Google account               │")
    print("  │  2. Enable Chrome Sync (passwords + autofill)   │")
    print("  │  3. Wait ~30s for passwords to sync             │")
    print("  │  4. Close this Chrome window                    │")
    print("  │  5. Re-run the script                           │")
    print("  │                                                 │")
    print("  │  This only needs to be done once.               │")
    print("  └─────────────────────────────────────────────────┘")
    print()


def ensure_chrome_debuggable(port: int = DEFAULT_PORT) -> str | None:
    """Ensure Chrome is running with remote debugging and return the endpoint.

    Returns:
        CDP endpoint URL (e.g., "http://localhost:9222") if successful,
        None if Chrome cannot be made debuggable.
    """
    endpoint = f"http://localhost:{port}"

    # Fast path: Chrome already has debugging enabled
    if _is_chrome_debuggable(port):
        log.info("Chrome debug connection available at %s", endpoint)
        return endpoint

    # Launch Chrome with the automation profile
    if _launch_chrome_with_debugging(port):
        return endpoint

    return None


def close_chrome(port: int = DEFAULT_PORT) -> bool:
    """Shut down the Chrome instance used for automation.

    Strategy:
      1. Close every tab via CDP /json/close/{id} — when the last
         tab closes, Chrome normally exits on its own.
      2. If Chrome is still alive after 3 seconds, kill the process
         tree that uses our automation profile directory.

    Returns True if Chrome was successfully shut down.
    """
    try:
        # Step 1: Close all tabs via CDP
        tabs_url = f"http://localhost:{port}/json"
        req = urllib.request.Request(tabs_url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            tabs = json.loads(resp.read())

        for tab in tabs:
            tab_id = tab.get("id")
            if tab_id:
                try:
                    close_url = f"http://localhost:{port}/json/close/{tab_id}"
                    urllib.request.urlopen(close_url, timeout=2)
                except Exception as e:
                    log.debug("Ignored exception: %s", e)

        # Wait for Chrome to exit after last tab closes
        for _ in range(6):
            time.sleep(0.5)
            if not _is_chrome_debuggable(port):
                log.info("Chrome automation window closed")
                return True

    except (urllib.error.URLError, OSError):
        # Chrome already not responding — might be gone
        if not _is_chrome_debuggable(port):
            return True

    # Step 2: Force kill Chrome processes using our profile.
    # wmic doesn't reliably populate CommandLine; use PowerShell instead.
    try:
        ps_script = (
            f"Get-CimInstance Win32_Process "
            f"-Filter \"name='chrome.exe'\" | "
            f"Where-Object {{ $_.CommandLine -like '*{AUTOMATION_PROFILE_DIR}*' }} | "
            f"Select-Object -ExpandProperty ProcessId"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=10,
        )

        pids = [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip().isdigit()
        ]

        if pids:
            for pid in pids:
                try:
                    subprocess.run(
                        ["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=5
                    )
                except Exception as e:
                    log.debug("Ignored exception: %s", e)

            time.sleep(1)
            log.info("Chrome automation killed (%d processes)", len(pids))
            return True

    except Exception as e:
        log.debug("Chrome process kill failed: %s", e)

    log.warning("Chrome did not shut down cleanly")
    return False
