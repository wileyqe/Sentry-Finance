"""Tests for session manager and browser manager."""
import sys, os, json, tempfile, pathlib
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extractors.session_manager import SessionManager
from extractors.browser_manager import BrowserManager


# ─── Session Manager Tests ───────────────────────────────────────────────────

class TestSessionManager:

    def test_init_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = pathlib.Path(tmpdir) / "new_sessions"
            sm = SessionManager(sessions_dir=sessions_dir)
            assert sessions_dir.exists()

    def test_has_session_no_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SessionManager(sessions_dir=pathlib.Path(tmpdir))
            assert not sm.has_session("nfcu")

    def test_save_and_load_session(self):
        """Simulate saving and loading a session (without real browser)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SessionManager(sessions_dir=pathlib.Path(tmpdir))

            # Manually create a session file (simulating save_from_context)
            session_path = sm._session_path("nfcu")
            meta_path = sm._meta_path("nfcu")

            state = {
                "cookies": [{"name": "session_id", "value": "abc123"}],
                "origins": []
            }
            session_path.write_text(json.dumps(state))
            meta_path.write_text(json.dumps({
                "institution": "nfcu",
                "created_at": datetime.now().isoformat(),
                "cookie_count": 1,
                "origin_count": 0,
            }))

            assert sm.has_session("nfcu")
            loaded = sm.load("nfcu")
            assert loaded["cookies"][0]["name"] == "session_id"

    def test_expired_session(self):
        """Session should be considered expired after max_age."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SessionManager(
                sessions_dir=pathlib.Path(tmpdir),
                max_age=timedelta(seconds=1)
            )

            session_path = sm._session_path("chase")
            meta_path = sm._meta_path("chase")

            state = {"cookies": [{"name": "x"}], "origins": []}
            session_path.write_text(json.dumps(state))

            # Set creation time to 2 hours ago
            old_time = (datetime.now() - timedelta(hours=2)).isoformat()
            meta_path.write_text(json.dumps({
                "institution": "chase",
                "created_at": old_time,
                "cookie_count": 1,
                "origin_count": 0,
            }))

            assert not sm.has_session("chase")

    def test_expire_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SessionManager(sessions_dir=pathlib.Path(tmpdir))

            # Create files
            sm._session_path("test").write_text("{}")
            sm._meta_path("test").write_text("{}")

            assert sm.expire("test")
            assert not sm._session_path("test").exists()
            assert not sm._meta_path("test").exists()

    def test_list_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SessionManager(sessions_dir=pathlib.Path(tmpdir))

            for name in ["nfcu", "chase"]:
                sm._session_path(name).write_text('{"cookies":[]}')
                sm._meta_path(name).write_text(json.dumps({
                    "institution": name,
                    "created_at": datetime.now().isoformat(),
                    "cookie_count": 0,
                    "origin_count": 0,
                }))

            sessions = sm.list_sessions()
            assert len(sessions) == 2

    def test_corrupt_session_handled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SessionManager(sessions_dir=pathlib.Path(tmpdir))
            sm._session_path("bad").write_text("not json")
            sm._meta_path("bad").write_text(json.dumps({
                "institution": "bad",
                "created_at": datetime.now().isoformat(),
            }))
            assert not sm.has_session("bad")


# ─── Browser Manager Tests ──────────────────────────────────────────────────

class TestBrowserManager:

    def test_init_creates_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = pathlib.Path(tmpdir)
            bm = BrowserManager(
                download_dir=base / "dl",
                screenshot_dir=base / "ss",
            )
            assert (base / "dl").exists()
            assert (base / "ss").exists()

    def test_random_delay_executes(self):
        """Delay should complete without error."""
        import time
        start = time.time()
        BrowserManager.random_delay(0.05, 0.1)
        elapsed = time.time() - start
        assert elapsed >= 0.05

    def test_list_downloads_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bm = BrowserManager(download_dir=pathlib.Path(tmpdir))
            assert len(bm.list_downloads()) == 0

    def test_clear_downloads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dl_dir = pathlib.Path(tmpdir)
            (dl_dir / "test.csv").write_text("a,b,c")
            bm = BrowserManager(download_dir=dl_dir)
            assert len(bm.list_downloads()) == 1
            bm.clear_downloads()
            assert len(bm.list_downloads()) == 0

    def test_repr(self):
        bm = BrowserManager()
        assert "BrowserManager" in repr(bm)

    def test_launch_and_navigate(self):
        """Integration test: launch browser, navigate, close."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bm = BrowserManager(
                download_dir=pathlib.Path(tmpdir) / "dl",
                screenshot_dir=pathlib.Path(tmpdir) / "ss",
                headless=True,
                slow_mo=0,
            )
            with bm.launch() as (browser, context, page):
                assert browser.is_connected()
                success = bm.safe_goto(page, "https://example.com")
                assert success
                assert "Example Domain" in page.title()

    def test_screenshot_capture(self):
        """Integration test: capture screenshot."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ss_dir = pathlib.Path(tmpdir) / "screenshots"
            bm = BrowserManager(
                download_dir=pathlib.Path(tmpdir) / "dl",
                screenshot_dir=ss_dir,
                headless=True,
                slow_mo=0,
            )
            with bm.launch() as (browser, context, page):
                page.goto("https://example.com")
                path = bm.screenshot(page, "test")
                assert path.exists()
                assert path.suffix == ".png"
