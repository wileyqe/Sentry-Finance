from datetime import datetime
from dal.database import get_db

now = datetime.utcnow().isoformat()
old = "2020-01-01T00:00:00"

with get_db() as conn:
    conn.execute(
        "UPDATE institution_refresh_status SET last_success = ? WHERE institution_id = 'chase'",
        (old,),
    )
    conn.execute(
        "UPDATE institution_refresh_status SET last_success = ? WHERE institution_id = 'nfcu'",
        (now,),
    )
    conn.commit()

print("Chase → stale, NFCU → fresh (will be skipped)")
