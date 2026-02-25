import sqlite3


def run():
    print("Testing Live DB...")
    with open("wpn_raw_out.txt", "w", encoding="utf-8") as f:
        conn = sqlite3.connect("wpn_copy2.db")
        data = conn.execute(
            "SELECT Payload FROM Notification ORDER BY ArrivalTime DESC LIMIT 10"
        ).fetchall()
        for x in data:
            f.write(repr(x) + "\n")


if __name__ == "__main__":
    run()
