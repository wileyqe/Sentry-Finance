import sqlite3
import shutil
import os


def run():
    source = os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\Windows\Notifications\wpndatabase.db"
    )
    dest = "wpn_copy2.db"
    try:
        shutil.copy2(source, dest)
        conn = sqlite3.connect(dest)

        data = conn.execute(
            "SELECT Payload FROM Notification ORDER BY ArrivalTime DESC LIMIT 20"
        ).fetchall()

        with open("wpn_out.txt", "w", encoding="utf-8") as f:
            for row in data:
                payload = row[0]
                if isinstance(payload, bytes):
                    payload = payload.decode("utf-8", errors="ignore")
                f.write(f"{payload}\n")
    except Exception as e:
        print("DB error:", e)


if __name__ == "__main__":
    run()
