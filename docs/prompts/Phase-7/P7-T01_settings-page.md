# P7-T01: Settings Page

## Context

You are working on Sentry Finance, a local-first personal finance app
for a two-person household. The app has no settings page. Configuration
lives in YAML files (`config/refresh_policy.yaml`, `config/owner_config.yaml`,
`config/budgets.yaml`, `config/accounts.yaml`) which are developer-facing,
not user-facing.

The user needs a settings page that surfaces the most commonly adjusted
configurations in the UI:

1. **Multi-user toggle** — enable/disable the household view selector
2. **Refresh policy** — per-institution refresh interval
3. **Notification preferences** — which alerts to surface
4. **Expected documents** — which monthly/annual docs to nudge for
5. **Archival policy** — how long to retain transaction history

### Design principle

Settings are stored in a new `app_settings` table (key-value store).
The YAML config files remain the **source of truth for connector and
account configuration** — the settings page does NOT replace them.
Instead, `app_settings` stores user-facing preferences that overlay the
defaults.

## Starting State

- `config/refresh_policy.yaml` — per-institution refresh intervals
- `config/owner_config.yaml` — primary_owner + owners
- `config/budgets.yaml` — default budget targets
- `dal/freshness.py` — tier classification (Tier 1 = automated, Tier 3 = doc drop)
- `dal/yearly_wrapup.py` — `_EXPECTED_TAX_DOCS` list
- `backend/routers/alerts.py` — alert rules CRUD
- No `app_settings` table exists
- No settings page exists
- Sidebar has a placeholder settings button (href="#")

## Task

### 1. Migration: `dal/migrations/v20_app_settings.py`

```python
"""V20 — App settings key-value store."""

def migrate(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key       TEXT PRIMARY KEY,
            value     TEXT NOT NULL,           -- JSON-encoded value
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- Seed defaults
        INSERT OR IGNORE INTO app_settings (key, value) VALUES
            ('multi_user_enabled', 'false'),
            ('refresh_intervals', '{}'),       -- overrides per institution
            ('notification_preferences', '{"budget_alerts": true, "staleness_alerts": true, "document_nudges": true, "bill_reminders": true}'),
            ('expected_monthly_docs', '["mypay_ras"]'),
            ('expected_annual_docs', '["dfas_1099r", "fidelity_1099", "acorns_1099", "affirm_1099int", "nfcu_1098"]'),
            ('archival_months', '36');
    """)
```

### 2. DAL: `dal/settings.py`

```python
"""
dal/settings.py — App settings read/write.

Settings are stored as JSON strings in a key-value table.
"""

import json
import sqlite3
import logging

log = logging.getLogger("sentry.dal.settings")


def get_setting(conn: sqlite3.Connection, key: str) -> any:
    """Get a single setting value, JSON-decoded. Returns None if not found."""
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = ?", (key,)
    ).fetchone()
    if row:
        return json.loads(row["value"])
    return None


def set_setting(conn: sqlite3.Connection, key: str, value: any) -> None:
    """Set a single setting value, JSON-encoded."""
    conn.execute(
        """INSERT INTO app_settings (key, value, updated_at)
           VALUES (?, ?, datetime('now'))
           ON CONFLICT(key) DO UPDATE SET value = excluded.value,
           updated_at = excluded.updated_at""",
        (key, json.dumps(value)),
    )
    conn.commit()


def get_all_settings(conn: sqlite3.Connection) -> dict:
    """Get all settings as a dict of {key: decoded_value}."""
    rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
    return {r["key"]: json.loads(r["value"]) for r in rows}
```

### 3. Backend: `backend/routers/settings.py`

New router with these endpoints:

```python
@router.get("/api/settings")
def get_settings():
    """Return all app settings."""
    with get_db() as conn:
        return get_all_settings(conn)


@router.patch("/api/settings/{key}")
def update_setting(key: str, body: dict):
    """
    Update a single setting.

    Body: {"value": <new_value>}

    Valid keys:
      - multi_user_enabled (bool)
      - refresh_intervals (dict of institution_id -> hours)
      - notification_preferences (dict of pref_name -> bool)
      - expected_monthly_docs (list of parser_type strings)
      - expected_annual_docs (list of parser_type strings)
      - archival_months (int)
    """
    VALID_KEYS = {
        "multi_user_enabled",
        "refresh_intervals",
        "notification_preferences",
        "expected_monthly_docs",
        "expected_annual_docs",
        "archival_months",
    }
    if key not in VALID_KEYS:
        raise HTTPException(400, f"Unknown setting: {key}")

    with get_db() as conn:
        set_setting(conn, key, body["value"])
    return {"status": "updated", "key": key}


@router.get("/api/settings/refresh-policy")
def get_refresh_policy():
    """
    Return the effective refresh policy: base YAML config merged with
    any per-institution overrides from app_settings.
    """
    from config import load_refresh_policy   # existing YAML loader
    base_policy = load_refresh_policy()

    with get_db() as conn:
        overrides = get_setting(conn, "refresh_intervals") or {}

    for inst_id, hours in overrides.items():
        if inst_id in base_policy:
            base_policy[inst_id]["refresh_interval_hours"] = hours

    return base_policy
```

Register in `api_server.py`:
```python
from backend.routers import settings
app.include_router(settings.router)
```

### 4. Frontend: `frontend/src/pages/SettingsPage.tsx`

New page at route `/settings`.

**Layout (vertical sections):**

#### Section 1: Multi-User Mode
- Toggle switch: "Enable Household Mode"
- Description text: "Show a view selector in the sidebar (Mine / Partner / Household)"
- When toggled on, the sidebar view selector (P7-T03) becomes visible
- When off, all data is shown unfiltered (current behavior)
- **This toggle is hidden until at least 2 owners exist in the system.**
  Query `GET /api/owners` — if only 1 owner, show a muted "Add a partner
  in the Accounts page to enable household mode" message instead.

#### Section 2: Refresh Policy
- Table: Institution | Current Interval | Override
- Each row shows the institution name, the base interval from YAML,
  and an editable number input for the override.
- "Reset to Default" button per row clears the override.
- Save button patches `refresh_intervals` setting.

#### Section 3: Notification Preferences
- Four toggle switches:
  - Budget alerts (over-budget notifications)
  - Staleness alerts (institution data age warnings)
  - Document nudges (monthly/annual upload reminders)
  - Bill reminders (upcoming/overdue bills)
- Each toggle patches `notification_preferences` setting on change.

#### Section 4: Expected Documents
- Two sub-sections:
  - **Monthly**: List of expected monthly documents (e.g., myPay RAS).
    Each item has a remove button. "Add document type" dropdown to add.
  - **Annual**: List of expected annual tax documents. Same UI.
- Available document types come from the registered parsers.
- Save patches `expected_monthly_docs` / `expected_annual_docs`.

#### Section 5: Data Retention
- Single number input: "Keep transaction history for X months"
- Description: "Transactions older than this are archived on refresh."
- Default: 36 months.
- Save patches `archival_months` setting.

**Fetch strategy**: `GET /api/settings` on mount, populate all sections.
Individual PATCH calls on save/toggle.

**Wire the sidebar settings button** (currently `href="#"`) to `/settings`.

### 5. Integration: Wire Settings into Existing Code

**Notification preferences** — Modify `backend/routers/documents.py`
(pending-nudges endpoint) to check `notification_preferences.document_nudges`
before returning nudges. If disabled, return empty list.

**Refresh intervals** — Modify `backend/routers/refresh.py` (staleness
check) to merge `refresh_intervals` overrides from `app_settings` into
the staleness computation.

**Multi-user toggle** — Add `GET /api/settings/multi-user-enabled`
convenience endpoint that returns just the boolean. The frontend sidebar
checks this to show/hide the view selector (P7-T03).

## Files to Create

1. `dal/migrations/v20_app_settings.py`
2. `dal/settings.py`
3. `backend/routers/settings.py`
4. `frontend/src/pages/SettingsPage.tsx`

## Files to Modify

1. `backend/api_server.py` — register settings router
2. `backend/routers/documents.py` — check notification pref before nudges
3. `backend/routers/refresh.py` — merge refresh interval overrides
4. `frontend/src/App.tsx` — add `/settings` route
5. `frontend/src/components/layout/Sidebar.tsx` — wire settings link

## Files NOT to Modify

- `config/*.yaml` — YAML remains source of truth; settings overlay
- `dal/owners.py` — owner management already complete
- `dal/migrations/v05_ownership.py` — existing schema is fine

## Constraints

- The `app_settings` table is a generic key-value store. Do NOT create
  separate tables for each setting type.
- All values are JSON-encoded. The DAL handles encoding/decoding — routers
  and frontend never deal with raw JSON strings.
- The `VALID_KEYS` set in the PATCH endpoint must be enforced — reject
  unknown keys to prevent injection of arbitrary settings.
- The multi-user toggle must be hidden when < 2 owners exist. Do NOT
  show it and disable it — hide it entirely with an explanatory message.
- Refresh interval overrides layer on top of YAML — they don't replace
  the YAML file. Removing an override reverts to the YAML default.
- The settings page must not require a page reload to take effect.
  All toggles should feel instant (optimistic UI updates + PATCH).

## Done Checklist

- [ ] V20 migration creates `app_settings` table with seed defaults
- [ ] `dal/settings.py` with get/set/get_all functions
- [ ] `backend/routers/settings.py` with GET/PATCH endpoints
- [ ] VALID_KEYS enforcement on PATCH
- [ ] `GET /api/settings/refresh-policy` merges YAML + overrides
- [ ] `SettingsPage.tsx` with all 5 sections
- [ ] Multi-user toggle hidden when < 2 owners
- [ ] Notification prefs wired to pending-nudges endpoint
- [ ] Refresh intervals wired to staleness check
- [ ] Settings router registered in api_server.py
- [ ] `/settings` route and sidebar link wired
- [ ] All existing tests still pass

## Verification

After completion, Claude will:
1. Verify V20 migration creates table and seeds defaults
2. Verify `get_all_settings()` returns all 6 keys
3. Verify PATCH rejects unknown keys
4. Verify refresh policy merge works (base + override)
5. Run import check on all new modules
6. Write pytest tests:
   a. `get_setting()` returns seeded default
   b. `set_setting()` + `get_setting()` round-trips correctly
   c. PATCH endpoint rejects invalid key
   d. Refresh policy merge applies override correctly
7. All tests pass
