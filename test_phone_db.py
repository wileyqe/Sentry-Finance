import sqlite3
import shutil
from extractors.sms_otp import _find_phone_link_db


def run():
    source = _find_phone_link_db()
    dest = "phone_copy.db"
    try:
        shutil.copy2(source, dest)
        conn = sqlite3.connect(dest)

        rows = conn.execute(
            "SELECT body, timestamp FROM message ORDER BY timestamp DESC LIMIT 20"
        ).fetchall()

        with open("phone_out_utf8.txt", "w", encoding="utf-8") as f:
            for r in rows:
                f.write(f"{r}\n")

    except Exception as e:
        print("DB error:", e)


if __name__ == "__main__":
    run()
