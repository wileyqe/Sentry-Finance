"""
dal/seed.py — Seed institutions and accounts from accounts.yaml.

Reads the YAML configuration and populates the institutions, accounts,
and institution_refresh_status tables with initial data.  Safe to
re-run (uses INSERT OR IGNORE / ON CONFLICT).
"""

import logging
from pathlib import Path

from dal.connection import BASE_DIR, get_db, resolve_db_path

log = logging.getLogger("sentry.dal")


def seed_institutions(
    db_path: Path = None,
    *,
    accounts_file: Path | None = None,
    ownership_overrides_path: Path | None = None,
    apply_ownership_overrides: bool = True,
) -> None:  # noqa: C901
    """Seed the institutions table from accounts.yaml if empty."""
    import yaml

    db_path = resolve_db_path(db_path)

    accounts_path = Path(accounts_file) if accounts_file is not None else BASE_DIR / "accounts.yaml"
    if not accounts_path.exists():
        log.warning("accounts.yaml not found, skipping seed")
        return

    with open(accounts_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # Institution metadata
    _INST_META = {
        "nfcu": {
            "display_name": "Navy Federal Credit Union",
            "login_url": "https://www.navyfederal.org/signin/",
            "refresh_interval_hours": 4,
            "mfa_expected": "sms",
            "extraction_method": "csv",
        },
        "chase": {
            "display_name": "Chase",
            "login_url": "https://www.chase.com/",
            "refresh_interval_hours": 4,
            "mfa_expected": "app",
            "extraction_method": "csv",
        },
        "acorns": {
            "display_name": "Acorns",
            "login_url": "https://app.acorns.com/login",
            "refresh_interval_hours": 24,  # Run daily after market close
            "mfa_expected": "sms",
            "extraction_method": "scrape",
        },
        "fidelity": {
            "display_name": "Fidelity",
            "login_url": "https://www.fidelity.com/",
            "refresh_interval_hours": 24,
            "mfa_expected": "totp",
            "extraction_method": "csv_import",
        },
        "tsp": {
            "display_name": "Thrift Savings Plan",
            "login_url": "https://www.tsp.gov/",
            "refresh_interval_hours": 24,
            "mfa_expected": "none",
            "extraction_method": "statement_api",
        },
        "affirm": {
            "display_name": "Affirm",
            "login_url": "https://www.affirm.com/user/signin",
            "refresh_interval_hours": 48,
            "mfa_expected": "sms",
            "extraction_method": "scrape",
        },
    }

    with get_db(db_path) as conn:
        # Seed owners first (FK target for accounts.owner_id)
        try:
            from dal.owners import seed_owners
            seed_owners(conn)
        except Exception as e:
            log.warning("Could not seed owners: %s", e)

        for inst_id, accounts in data.items():
            meta = _INST_META.get(inst_id, {})
            conn.execute(
                """
                INSERT OR IGNORE INTO institutions (id, display_name,
                    login_url, refresh_interval_hours, mfa_expected,
                    extraction_method)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    inst_id,
                    meta.get("display_name", inst_id),
                    meta.get("login_url"),
                    meta.get("refresh_interval_hours", 4),
                    meta.get("mfa_expected", "none"),
                    meta.get("extraction_method", "scrape"),
                ),
            )

            for acct in accounts:
                acct_id = str(acct.get("id") or f"{inst_id}_{acct['last4']}").strip()
                owner_id = acct.get("owner")
                if owner_id is None:
                    owner_id = acct.get("owner_id")
                conn.execute(
                    """
                    INSERT INTO accounts
                        (id, institution_id, name, last4, type, owner_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE
                        SET name = excluded.name,
                            owner_id = COALESCE(excluded.owner_id, accounts.owner_id)
                """,
                    (
                        acct_id,
                        inst_id,
                        acct["name"],
                        acct["last4"],
                        acct.get("type", "unknown"),
                        owner_id,
                    ),
                )

            # Seed refresh status
            conn.execute(
                """
                INSERT OR IGNORE INTO institution_refresh_status
                    (institution_id)
                VALUES (?)
            """,
                (inst_id,),
            )

        if apply_ownership_overrides:
            from dal.owners import apply_account_ownership_overrides

            stats = apply_account_ownership_overrides(
                conn,
                path=ownership_overrides_path,
            )
            if stats["loaded"]:
                log.info(
                    "Applied %d/%d account ownership override(s) "
                    "(%d missing account(s))",
                    stats["applied"],
                    stats["loaded"],
                    stats["missing_accounts"],
                )

        conn.commit()
        log.info("Seeded %d institutions and their accounts", len(data))
