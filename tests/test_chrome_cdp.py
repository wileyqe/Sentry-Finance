from __future__ import annotations

from unittest.mock import patch

from extractors import chrome_cdp


def test_ensure_chrome_debuggable_refuses_wrong_profile_owner():
    with patch.object(chrome_cdp, "_is_chrome_debuggable", return_value=True), \
         patch.object(
             chrome_cdp,
             "_debug_port_owned_by_automation_profile",
             return_value=False,
         ), patch.object(chrome_cdp, "_launch_chrome_with_debugging") as launch:
        assert chrome_cdp.ensure_chrome_debuggable() is None

    launch.assert_not_called()


def test_ensure_chrome_debuggable_accepts_automation_profile_owner():
    with patch.object(chrome_cdp, "_is_chrome_debuggable", return_value=True), \
         patch.object(
             chrome_cdp,
             "_debug_port_owned_by_automation_profile",
             return_value=True,
         ):
        assert chrome_cdp.ensure_chrome_debuggable() == "http://localhost:9222"


def test_debug_port_owner_matches_automation_profile(monkeypatch):
    monkeypatch.setattr(chrome_cdp, "AUTOMATION_PROFILE_DIR", r"C:\ChromeAutomationProfile")
    with patch.object(
        chrome_cdp,
        "_remote_debugging_command_lines",
        return_value=[
            (
                r'"C:\Program Files\Google\Chrome\Application\chrome.exe" '
                r"--remote-debugging-port=9222 "
                r'--user-data-dir="C:\ChromeAutomationProfile"'
            )
        ],
    ):
        assert chrome_cdp._debug_port_owned_by_automation_profile() is True


def test_debug_port_owner_rejects_default_profile(monkeypatch):
    monkeypatch.setattr(chrome_cdp, "AUTOMATION_PROFILE_DIR", r"C:\ChromeAutomationProfile")
    with patch.object(
        chrome_cdp,
        "_remote_debugging_command_lines",
        return_value=[
            (
                r'"C:\Program Files\Google\Chrome\Application\chrome.exe" '
                r"--remote-debugging-port=9222 --restore-last-session"
            )
        ],
    ):
        assert chrome_cdp._debug_port_owned_by_automation_profile() is False
