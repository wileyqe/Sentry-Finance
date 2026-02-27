import sqlite3
import shutil
import os


def run():
    source = os.path.expandvars(
        r"%LOCALAPPDATA%\Packages\Microsoft.YourPhone_8wekyb3d8bbwe\LocalCache\Indexed\bb5c5345-f74f-4ab7-aa9d0-3f69819f7c87\System\Database\phone.db"
    )
    dest = "phone_copy.db"
    try:
        shutil.copy2(source, dest)
        conn = sqlite3.connect(dest)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        ).fetchall()
        print("Tables:", rows)

        if ("Message",) in rows or ("message",) in rows:
            print("Message table rows:")
            data = conn.execute(
                "SELECT * FROM Message ORDER BY rowid DESC LIMIT 1"
            ).fetchall()
            print(data)
    except Exception as e:
        print("DB error:", e)


if __name__ == "__main__":
    run()
