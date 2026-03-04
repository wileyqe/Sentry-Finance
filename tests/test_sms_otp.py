from config.logging_config import setup_logging

setup_logging("DEBUG")


def run_tests():
    print("Testing Strategy 1: PowerShell Toast")
    from extractors.sms_otp import _try_powershell_toast, _PS_TOAST_SCRIPT
    import subprocess

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            _PS_TOAST_SCRIPT,
        ],
        capture_output=True,
        text=True,
    )
    print("Raw output:")
    print(result.stdout)
    print("Errors:")
    print(result.stderr)

    print("\nTesting Strategy 2: Phone Link DB")
    from extractors.sms_otp import _find_phone_link_db

    db_path = _find_phone_link_db()
    print("DB Path:", db_path)

    if db_path:
        import sqlite3
        import time

        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
            cutoff = int(time.time()) - (120 * 60)  # check last 120 mins
            rows = conn.execute(
                "SELECT body, timestamp FROM messages "
                "WHERE timestamp > ? ORDER BY timestamp DESC LIMIT 5",
                (cutoff,),
            ).fetchall()
            print("Recent DB records:")
            for row in rows:
                print(row)
        except Exception as e:
            print("DB error:", e)


if __name__ == "__main__":
    run_tests()
