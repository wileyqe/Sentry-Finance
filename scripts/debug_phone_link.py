"""
scripts/debug_phone_link.py — Phone Link SQLite diagnostic probe.

Reads the 5 most recent messages from the Windows Phone Link database
and writes them to logs/phone_link_debug.txt for inspection.

This is a read-only diagnostic tool — it uses ?mode=ro and never
modifies any data. It is NOT a test; do not run it in CI.

Usage:
    python scripts/debug_phone_link.py
"""

import sqlite3
from pathlib import Path

# Ensure project root is on the path so imports work when run as a script
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extractors.sms_otp import _find_phone_link_db

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "phone_link_debug.txt"


def run():
    db_path = _find_phone_link_db()
    if not db_path:
        print("  ✗  Phone Link database not found")
        print("     Is the Microsoft Phone Link app installed and paired?")
        return

    print(f"  📱  Found Phone Link DB: {db_path}")

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
        rows = conn.execute(
            "SELECT body, timestamp FROM message ORDER BY timestamp DESC LIMIT 5"
        ).fetchall()
        conn.close()
    except Exception as e:
        print(f"  ✗  DB error: {e}")
        print("     The database may be locked by the Phone Link app.")
        return

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        f.write(f"Phone Link diagnostic — {db_path}\n")
        f.write(f"{'─' * 60}\n")
        for r in rows:
            f.write(f"{r}\n")

    print(f"  ✔  {len(rows)} message(s) written to: {LOG_PATH.name}")


if __name__ == "__main__":
    run()
