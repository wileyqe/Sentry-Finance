"""
tests/test_institution_connector.py - Base connector lifecycle guards.
"""

from __future__ import annotations

import pytest

from skills.institution_connector import _is_closeable_orphan_tab_url


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "about:blank",
        "about:srcdoc",
        "chrome://newtab/",
        "chrome://omnibox-popup.top-chrome/",
        "chrome-untrusted://new-tab-page/",
        "chrome-extension://abcdef/popup.html",
        "devtools://devtools/bundled/inspector.html",
    ],
)
def test_orphan_cleanup_skips_internal_chrome_pages(url):
    """Internal Chrome pages can hang when closed through the CDP page API."""
    assert _is_closeable_orphan_tab_url(url) is False


@pytest.mark.parametrize(
    "url",
    [
        "https://mypay.dfas.mil/",
        "https://digitalomni.navyfederal.org/accounts",
        "http://127.0.0.1:8000/debug",
        "file:///C:/tmp/report.html",
    ],
)
def test_orphan_cleanup_closes_content_pages(url):
    """Real content pages from crashed connector runs should still be cleaned up."""
    assert _is_closeable_orphan_tab_url(url) is True
