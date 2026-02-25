---
---

name: InstitutionConnector
version: 2.0
architecture: Persistent Session Export Automation
--------------------------------------------------

# InstitutionConnector Skill (Sentry Finance v2)

## Philosophy Shift

This skill no longer attempts aggressive browser "infiltration" or stealth scraping.

Instead, it implements:

> Persistent session management + deterministic export automation

The objective is stability, low detection risk, and minimal manual interaction — not bot evasion.

This is a **personal-use financial ingestion layer**, not a scraping engine.

---

# Core Design Principles

1. **Session Reuse Over Re-Login**
   Login is automated only when required. Most runs reuse an existing authenticated browser session.

2. **Persistent Browser Profiles Per Institution**
   Each institution has a dedicated Playwright persistent context directory.

3. **Export, Don’t Scrape**
   We use official CSV/QFX export mechanisms. We do not scrape HTML transaction tables.

4. **Human MFA, Never Bypassed**
   If MFA is required, the script pauses and waits for human approval.

5. **Refresh Cadence Control**
   Each institution has its own refresh interval (e.g., NFCU every 2 days, others weekly).

6. **Minimal Detection Surface**
   No rotating user agents. No stealth plugins. No IP manipulation. Consistency is safer than obfuscation.

---

# Architecture Overview

```
skills/
├── SKILL.md
├── __init__.py
└── institution_connector.py

profiles/
├── nfcu/
├── chase/
├── fidelity/
├── tsp/
├── acorns/
└── affirm/

state.json   # Tracks last successful refresh per institution
```

---

# Persistent Session Model

Each institution uses:

```python
p.chromium.launch_persistent_context(
    user_data_dir="./profiles/nfcu",
    headless=False
)
```

This stores:

* Cookies
* Trusted device flags
* Local storage
* Device fingerprint

Result:

* MFA frequency decreases
* Login attempts decrease
* Behavioral consistency increases

---

# Connector Lifecycle

Each connector follows this deterministic flow:

1. Launch persistent context
2. Navigate directly to export or account activity URL
3. If redirected to login → perform automated login
4. Wait for MFA (human approval)
5. Trigger CSV/QFX export
6. Save file with standardized naming
7. Update `state.json`
8. Close browser

---

# Session Validation Logic

Before attempting login:

```python
page.goto(EXPORT_URL)

if "login" in page.url:
    perform_login()
else:
    print("Session valid. Skipping login.")
```

Login is conditional, not routine.

---

# Refresh Orchestration

A refresh policy controls when connectors run.

Example:

```json
{
  "nfcu": {"interval_days": 2},
  "chase": {"interval_days": 7},
  "fidelity": {"interval_days": 7},
  "tsp": {"interval_days": 7},
  "acorns": {"interval_days": 7},
  "affirm": {"interval_days": 14}
}
```

Before execution:

* Check last successful run timestamp in `state.json`
* Only run institutions exceeding their interval

Opening Sentry Finance does NOT automatically hit all institutions.

---

# Automated Login Policy

Login automation is allowed but constrained:

* Uses stored credentials (local `.env` during development)
* Executes only if session expired
* Never bypasses MFA
* Waits for human approval when challenged

Future enhancement:

* Abstract credential provider to support GCP Secret Manager

---

# Secrets Handling

## Development

Credentials may be loaded from `.env`.

## Future Production Hardening

Introduce a `SecretProvider` abstraction:

* LocalEnvSecretProvider
* GCPSecretManagerProvider

Connector code should not directly call `os.getenv()`.

---

# Download Handling Pattern

Exports must use deterministic download handling:

```python
with page.expect_download() as download_info:
    page.click("Export CSV")

download = download_info.value
download.save_as("./raw_exports/nfcu_2026-02-12.csv")
```

No DOM scraping of transaction tables.

---

# Logging & Observability

Each run should:

* Log structured events (JSON preferred)
* Capture screenshots on failure
* Classify errors:

  * Session expired
  * Login failure
  * MFA timeout
  * Export selector change
  * Download failure

---

# Risk Posture

This architecture:

* Mimics normal human behavior
* Uses consistent IP and device fingerprint
* Minimizes login frequency
* Avoids stealth escalation

It is significantly lower risk than:

* Full headless scraping
* Rotating user agents
* Aggregator-style data center automation

---

# Scope Clarification

This system is:

* Personal infrastructure
* Not a commercial scraper
* Not intended for multi-tenant use

If expanded beyond personal use, API-based integrations should be evaluated.

---

# Long-Term Vision

Once ingestion is stable, value shifts to:

* Transaction normalization
* Category intelligence
* Recurring detection
* Cashflow modeling
* Behavioral analytics
* Investment drift analysis

Automation’s purpose is data acquisition stability — not browser warfare.

---

End of Skill Specification (v2).


