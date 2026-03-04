"""
config/logging_config.py — Centralized logging setup for Sentry Finance.

Call setup_logging() once per entry point (run_all.py, api_server.py, etc.).
All other modules simply use:

    import logging
    log = logging.getLogger("sentry.extractors.chase")  # hierarchical name

Handlers:
  - Console (StreamHandler)        → INFO+ by default, human-readable format
  - All-level file (weekly rotate) → DEBUG+ to logs/sentry.log (keep 4 weeks)
  - Errors-only file (weekly)      → WARNING+ to logs/sentry_errors.log (keep 8 weeks)
"""

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

# Retention: rotate every Monday at midnight, keep N weeks of history
_ALL_LOG_BACKUP_COUNT = 4  # ~1 month of full logs
_ERR_LOG_BACKUP_COUNT = 8  # ~2 months of error history


def setup_logging(console_level: str = "INFO") -> None:
    """Configure the 'sentry' logger hierarchy with console + file handlers.

    Safe to call multiple times — subsequent calls are no-ops.

    Args:
        console_level: Minimum level shown on the console.
                       Pass "DEBUG" when using --verbose or during development.
    """
    LOG_DIR.mkdir(exist_ok=True)

    root = logging.getLogger("sentry")

    # Guard: don't double-attach handlers on re-import
    if root.handlers:
        return

    root.setLevel(logging.DEBUG)

    # ── Console handler (user-visible, concise) ──────────────────────────
    console_fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(message)s",
        datefmt="%H:%M:%S",
    )
    console = logging.StreamHandler()
    console.setLevel(getattr(logging, console_level.upper(), logging.INFO))
    console.setFormatter(console_fmt)
    root.addHandler(console)

    # ── All-level file handler (weekly rotation) ─────────────────────────
    file_fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    all_fh = TimedRotatingFileHandler(
        LOG_DIR / "sentry.log",
        when="W0",  # rotate every Monday
        backupCount=_ALL_LOG_BACKUP_COUNT,  # keep 4 weeks
        encoding="utf-8",
    )
    all_fh.setLevel(logging.DEBUG)
    all_fh.setFormatter(file_fmt)
    root.addHandler(all_fh)

    # ── Errors-only file handler (weekly rotation) ───────────────────────
    err_fh = TimedRotatingFileHandler(
        LOG_DIR / "sentry_errors.log",
        when="W0",  # rotate every Monday
        backupCount=_ERR_LOG_BACKUP_COUNT,  # keep 8 weeks
        encoding="utf-8",
    )
    err_fh.setLevel(logging.WARNING)
    err_fh.setFormatter(file_fmt)
    root.addHandler(err_fh)
