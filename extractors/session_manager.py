"""
extractors/session_manager.py — Persistent browser session management.

Saves and restores Playwright browser state (cookies, localStorage, sessionStorage)
to avoid re-authentication on every run. Supports per-institution session files.

Usage:
    sm = SessionManager(sessions_dir=Path(".sessions"))

    # Check for valid session
    if sm.has_session("nfcu"):
        state = sm.load("nfcu")  # Returns storage state dict

    # After successful login, save session
    sm.save("nfcu", page)        # Saves cookies + storage from a live page

    # Expire stale sessions
    sm.expire("nfcu")
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger("antigravity")

# Default session lifetime before we consider it expired
DEFAULT_MAX_AGE = timedelta(hours=12)


class SessionManager:
    """Manages persistent browser sessions for financial institution extractors.

    Sessions are stored as JSON files containing Playwright's storageState
    (cookies, origins with localStorage). Each institution gets its own file.
    """

    def __init__(self, sessions_dir: Path | None = None,
                 max_age: timedelta = DEFAULT_MAX_AGE):
        """
        Args:
            sessions_dir: Directory to store session files. Created if missing.
            max_age: Maximum session age before forced re-authentication.
        """
        self._dir = sessions_dir or Path(__file__).resolve().parent.parent / ".sessions"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max_age = max_age
        log.debug("SessionManager initialized: dir=%s, max_age=%s", self._dir, max_age)

    # ── Path Helpers ──────────────────────────────────────────────────────

    def _session_path(self, institution: str) -> Path:
        """Return the session file path for an institution."""
        safe_name = institution.lower().replace(" ", "_")
        return self._dir / f"{safe_name}_session.json"

    def _meta_path(self, institution: str) -> Path:
        """Return the metadata file path (tracks creation time)."""
        safe_name = institution.lower().replace(" ", "_")
        return self._dir / f"{safe_name}_meta.json"

    # ── Public API ────────────────────────────────────────────────────────

    def has_session(self, institution: str) -> bool:
        """Check if a valid (non-expired) session exists for the institution."""
        session_path = self._session_path(institution)
        meta_path = self._meta_path(institution)

        if not session_path.exists():
            return False

        # Check expiry
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                created = datetime.fromisoformat(meta["created_at"])
                if datetime.now() - created > self._max_age:
                    log.info("Session expired for %s (created %s)", institution, created)
                    return False
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                log.warning("Corrupt session meta for %s: %s", institution, e)
                return False
        else:
            # No metadata = can't verify age, consider expired
            return False

        # Validate the session file is parseable
        try:
            data = json.loads(session_path.read_text())
            # Must have cookies key (Playwright storage state format)
            if "cookies" not in data:
                log.warning("Session file missing 'cookies' key for %s", institution)
                return False
        except json.JSONDecodeError:
            log.warning("Corrupt session file for %s", institution)
            return False

        log.info("Valid session found for %s", institution)
        return True

    def load(self, institution: str) -> dict[str, Any]:
        """Load the saved storage state for an institution.

        Returns the Playwright-compatible storageState dict.
        Raises FileNotFoundError if no session exists.
        """
        session_path = self._session_path(institution)
        if not session_path.exists():
            raise FileNotFoundError(f"No session saved for {institution}")

        data = json.loads(session_path.read_text())
        log.info("Loaded session for %s (%d cookies)",
                 institution, len(data.get("cookies", [])))
        return data

    def save_from_context(self, institution: str, context) -> Path:
        """Save browser context state for an institution.

        Args:
            institution: Institution name
            context: Playwright BrowserContext object

        Returns:
            Path to the saved session file.
        """
        session_path = self._session_path(institution)
        meta_path = self._meta_path(institution)

        # Save Playwright storage state
        state = context.storage_state()
        session_path.write_text(json.dumps(state, indent=2))

        # Save metadata
        meta = {
            "institution": institution,
            "created_at": datetime.now().isoformat(),
            "cookie_count": len(state.get("cookies", [])),
            "origin_count": len(state.get("origins", [])),
        }
        meta_path.write_text(json.dumps(meta, indent=2))

        log.info("Saved session for %s (%d cookies, %d origins) → %s",
                 institution, meta["cookie_count"], meta["origin_count"],
                 session_path.name)
        return session_path

    def expire(self, institution: str) -> bool:
        """Delete the saved session for an institution.

        Returns True if a session was deleted, False if none existed.
        """
        deleted = False
        for path in (self._session_path(institution), self._meta_path(institution)):
            if path.exists():
                path.unlink()
                deleted = True

        if deleted:
            log.info("Expired session for %s", institution)
        return deleted

    def expire_all(self) -> int:
        """Delete all saved sessions. Returns count of files deleted."""
        count = 0
        for f in self._dir.glob("*_session.json"):
            f.unlink()
            count += 1
        for f in self._dir.glob("*_meta.json"):
            f.unlink()
            count += 1
        log.info("Expired all sessions (%d files)", count)
        return count

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all saved sessions with their metadata."""
        sessions = []
        for meta_file in sorted(self._dir.glob("*_meta.json")):
            try:
                meta = json.loads(meta_file.read_text())
                created = datetime.fromisoformat(meta["created_at"])
                age = datetime.now() - created
                meta["age_hours"] = round(age.total_seconds() / 3600, 1)
                meta["expired"] = age > self._max_age
                meta["file"] = meta_file.stem.replace("_meta", "")
                sessions.append(meta)
            except (json.JSONDecodeError, KeyError):
                continue
        return sessions

    def __repr__(self):
        count = len(list(self._dir.glob("*_session.json")))
        return f"<SessionManager dir={self._dir} sessions={count}>"
