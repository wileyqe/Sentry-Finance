"""
extractors/sms_otp.py — Windows Phone Link SMS OTP capture.

Used for institutions that require SMS-based 2FA (specifically Affirm).

Strategy (in priority order):
  1. PowerShell — Read from Windows Notification Center history via
     Get-WinEvent or the Phone Link notification database.
  2. Phone Link DB — Query the SQLite database maintained by the
     Microsoft Phone Link app at:
     %LocalAppData%\\Packages\\Microsoft.YourPhone_8wekyb3d8bbwe\\
       LocalCache\\Indexed\\...\\System\\Database\\phone.db
  3. CLI fallback — Prompt the user to enter the code manually.

Rules (windows-native-integrations.md):
  - NEVER use Twilio, Vonage, Nexmo, or any external SMS API.
  - NEVER attempt to intercept SMS at the carrier level.
  - Regex for OTP extraction: r'\\b\\d{6}\\b'
  - Always fall back to CLI prompt if programmatic access fails.

Usage (from an Affirm connector):
    from extractors.sms_otp import wait_for_otp

    code = wait_for_otp(timeout=120, hint="Affirm")
    if code:
        page.fill("#otp-input", code)
    else:
        # wait_for_otp already prompted the user — code was entered manually
        pass
"""

import logging
import os
import re
import subprocess
import time
from pathlib import Path

log = logging.getLogger("sentry")

# Regex for 6-digit or 8-digit OTP codes (per windows-native-integrations.md + 8-digit Chase)
_OTP_PATTERN = re.compile(r"\b(\d{6}|\d{8})\b")

# Phone Link app package path
_PHONE_LINK_BASE = Path(os.environ.get("LOCALAPPDATA", "")) / (
    "Packages/Microsoft.YourPhone_8wekyb3d8bbwe/LocalCache"
)

# PowerShell script to read recent toast notifications from the
# Windows Notification Center history (Action Center log)
_PS_TOAST_SCRIPT = r"""
$source = "Microsoft.YourPhone"
try {
    $events = Get-WinEvent -ProviderName $source -MaxEvents 10 -ErrorAction Stop
    foreach ($e in $events) { $e.Message }
} catch {
    # Fallback: read from notification platform log
    $log = "$env:LOCALAPPDATA\Microsoft\Windows\Notifications\wpndatabase.db"
    if (Test-Path $log) { Write-Output "PHONE_LINK_DB:$log" }
}
"""


def _extract_otp(text: str) -> str | None:
    """Extract a 6-digit OTP from a string. Returns first match or None."""
    match = _OTP_PATTERN.search(text)
    return match.group(1) if match else None


def _try_powershell_toast(hint: str = "", timeout_per_attempt: int = 5) -> str | None:
    """Attempt to read OTP from Windows Notification Center via PowerShell.

    Returns the OTP string if found, None otherwise.
    """
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                _PS_TOAST_SCRIPT,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_per_attempt,
        )
        output = result.stdout.strip()
        if not output:
            return None

        # Filter lines that mention our hint keyword (e.g. "Affirm")
        lines = output.splitlines()
        for line in lines:
            if hint.lower() in line.lower() or not hint:
                otp = _extract_otp(line)
                if otp:
                    log.info("[sms_otp] OTP found via PowerShell toast: %s***", otp[:2])
                    return otp

    except subprocess.TimeoutExpired:
        log.debug("[sms_otp] PowerShell toast query timed out")
    except Exception as e:
        log.debug("[sms_otp] PowerShell toast query failed: %s", e)

    return None


def _find_phone_link_db() -> Path | None:
    """Locate the Phone Link SQLite database.

    The exact path varies by Windows version and Phone Link version.
    Searches common locations under the Phone Link package directory.
    """
    if not _PHONE_LINK_BASE.exists():
        return None

    # Search for phone.db or similar under the package
    for pattern in ["**/phone.db", "**/sms.db", "**/messages.db"]:
        matches = list(_PHONE_LINK_BASE.glob(pattern))
        if matches:
            # Return the most recently modified one
            return max(matches, key=lambda p: p.stat().st_mtime)

    return None


def _try_phone_link_db(hint: str = "", lookback_seconds: int = 120) -> str | None:
    """Attempt to read OTP from the Phone Link SQLite database.

    NOTE: The Phone Link database is often locked by the app. This
    method will fail gracefully and fall through to the CLI prompt.

    Returns the OTP string if found, None otherwise.
    """
    db_path = _find_phone_link_db()
    if not db_path:
        log.debug("[sms_otp] Phone Link database not found")
        return None

    try:
        import sqlite3

        # Use a short timeout — if locked, fail fast
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
        try:
            # Query recent SMS messages
            # Windows Phone Link DB uses FileTime (100-nanosecond intervals since Jan 1, 1601)
            filetime_now = (int(time.time()) + 11644473600) * 10000000
            cutoff = filetime_now - (lookback_seconds * 10000000)
            rows = conn.execute(
                "SELECT body FROM message "
                "WHERE timestamp > ? ORDER BY timestamp DESC LIMIT 20",
                (cutoff,),
            ).fetchall()

            for (body,) in rows:
                if not body:
                    continue
                otp = _extract_otp(body)
                if otp:
                    if hint and hint.lower() not in body.lower():
                        log.debug(
                            "[sms_otp] Found OTP %s*** but hint '%s' not in message. Using it anyway.",
                            otp[:2],
                            hint,
                        )
                    log.info("[sms_otp] OTP found via Phone Link DB: %s***", otp[:2])
                    return otp
        finally:
            conn.close()

    except Exception as e:
        log.debug("[sms_otp] Phone Link DB query failed: %s", e)

    return None


def _cli_fallback(hint: str = "") -> str | None:
    """Prompt the user to enter the OTP manually.

    Per windows-native-integrations.md: always provide this fallback
    if programmatic access fails.
    """
    label = f" ({hint})" if hint else ""
    print()
    print(f"  📱  SMS OTP required{label}")
    print("      Check your phone for a 6-digit code.")
    print()
    try:
        code = input("  Enter the code: ").strip()
        otp = _extract_otp(code)
        if otp:
            return otp
        # Accept raw 6-digit input even without surrounding text
        if re.fullmatch(r"\d{6}", code):
            return code
        log.warning("[sms_otp] Input '%s' does not contain a 6-digit code", code)
        return None
    except (KeyboardInterrupt, EOFError):
        return None


def wait_for_otp(
    timeout: int = 120, hint: str = "", poll_interval: int = 3
) -> str | None:
    """Wait for an SMS OTP, trying all available strategies.

    Strategy order:
      1. PowerShell toast notification history (preferred)
      2. Phone Link SQLite database (if accessible)
      3. CLI prompt (always available fallback)

    Args:
        timeout: Seconds to poll before falling back to CLI prompt.
        hint: Keyword to filter SMS messages (e.g. "Affirm", "Verification").
        poll_interval: Seconds between polling attempts.

    Returns:
        6-digit OTP string, or None if user cancelled.
    """
    log.info("[sms_otp] Waiting for OTP (hint=%r, timeout=%ds)", hint, timeout)

    deadline = time.time() + timeout
    attempt = 0

    while time.time() < deadline:
        attempt += 1

        # Strategy 1: PowerShell toast
        otp = _try_powershell_toast(hint=hint)
        if otp:
            return otp

        # Strategy 2: Phone Link DB (only try every 3rd poll to reduce lock contention)
        if attempt % 3 == 0:
            otp = _try_phone_link_db(hint=hint)
            if otp:
                return otp

        remaining = int(deadline - time.time())
        if remaining > 0:
            log.debug(
                "[sms_otp] No OTP yet, retrying in %ds (%ds remaining)",
                poll_interval,
                remaining,
            )
            time.sleep(poll_interval)

    # Strategy 3: CLI fallback
    log.info("[sms_otp] Timed out waiting for OTP — falling back to CLI prompt")
    return _cli_fallback(hint=hint)
