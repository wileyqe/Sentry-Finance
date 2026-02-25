import sqlite3
import time
from extractors.sms_otp import _find_phone_link_db


def run():
    db_path = _find_phone_link_db()
    if not db_path:
        print("db not found")
        return

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
        rows = conn.execute(
            "SELECT body, timestamp FROM message ORDER BY timestamp DESC LIMIT 5"
        ).fetchall()

        with open("live_db_out.txt", "w", encoding="utf-8") as f:
            for r in rows:
                f.write(f"{r}\n")

    except Exception as e:
        print("DB error:", e)


if __name__ == "__main__":
    run()
