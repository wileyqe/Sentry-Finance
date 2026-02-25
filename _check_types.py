from dal.database import get_db

with get_db() as conn:
    rows = conn.execute(
        "SELECT institution_id, name, type, last4 FROM accounts WHERE institution_id = 'chase'"
    ).fetchall()
    for r in rows:
        print(dict(r))
