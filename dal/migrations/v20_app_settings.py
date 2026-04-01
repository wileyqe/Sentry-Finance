"""V20 — App settings key-value store."""

VERSION = 20


def run(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- Seed defaults
        INSERT OR IGNORE INTO app_settings (key, value) VALUES
            ('multi_user_enabled', 'false'),
            ('refresh_intervals', '{}'),
            ('notification_preferences', '{"budget_alerts": true, "staleness_alerts": true, "document_nudges": true, "bill_reminders": true}'),
            ('expected_monthly_docs', '["mypay_ras"]'),
            ('expected_annual_docs', '["dfas_1099r", "fidelity_1099", "acorns_1099", "affirm_1099int", "nfcu_1098"]'),
            ('archival_months', '36');
    """)
