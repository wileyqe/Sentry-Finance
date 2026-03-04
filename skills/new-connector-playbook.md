---
name: new-connector-playbook
description: Step-by-step playbook for building a new institution connector, based on lessons from the Acorns pipeline development
---

# New Connector Development Playbook

A tactical guide for building a new `InstitutionConnector` subclass from scratch.
Based on the Acorns pipeline development (Feb–Mar 2026) and hardened by NFCU/Chase.

---

## Phase 1: Reconnaissance (Before Writing Code)

### 1.1 — Map the Login Flow

Open the institution's website in a normal browser and trace the full login journey:

- **Starting URL** — note any redirects (e.g., Acorns redirected `app.acorns.com/login` → `oak.acorns.com/sign-in` — a different domain entirely)
- **Form field attributes** — inspect each field: `id`, `name`, `type`, `autocomplete`, `placeholder`, `aria-label`. Don't assume `type="email"` — Acorns uses `type="text"` with `inputmode="email"`
- **MFA mechanism** — SMS, TOTP, push notification, or email? Does it use a custom UI or native input?
  - **SMS OTP** — fully automated via `wait_for_otp()` from `extractors/sms_otp.py` (Phone Link capture)
  - **Authenticator app (TOTP)** — **NOT YET AUTOMATABLE**. Fidelity and TSP use authenticator apps (e.g., Symantec VIP, Google Authenticator). There is no secure automation path for this yet. The connector must pause and wait for manual code entry. Design the `_wait_for_mfa()` override to detect the TOTP input field and halt gracefully:
    ```python
    def _wait_for_mfa(self, page, timeout_seconds=300):
        """Pause for manual authenticator code entry."""
        print("  📱  Enter your authenticator code in the browser.")
        # Poll for post-login state — user enters code manually
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if self._is_post_login(page):
                return
            page.wait_for_timeout(2000)
    ```
  - **Research ongoing**: Exploring TOTP secret export + `pyotp` generation, but security implications need evaluation before implementation
- **Post-login landing URL** — what URL confirms a successful login? This is your `_is_post_login` signal
- **SPA vs Traditional** — SPAs don't reload on navigation; you need `wait_for_selector` or `wait_for_url` instead of `wait_for_load_state`

> **Lesson learned**: Always browse to the ACTUAL login page in the browser subagent first and inspect the DOM before writing selectors. Login pages change domains and field types without warning.

### 1.2 — Map the Data Export

Identify what data you need and how to get it:

| Export Type | Strategy | Example |
|---|---|---|
| CSV/QFX download | `page.expect_download()` | NFCU, Chase |
| DOM scraping | `page.evaluate()` JS | Acorns portfolio values |
| API interception | `page.route()` or network events | (future) |

- **Navigation pattern** — does the site use URL-based routing or click-based SPA navigation?
- **Dynamic content** — does the data render immediately or require scrolling/clicking to load?
- **Detail pages** — do you need to navigate into detail views for additional data (like Acorns per-fund share counts)?

### 1.3 — Map the Logout

- Look for "Sign Out" / "Log Out" links, often under a profile/user menu
- Check if there's a direct logout URL (e.g., NFCU: `/signin/signout/`, Chase: `#/dashboard/signOut`)
- Note any popups that appear during navigation (surveys, upsells, "before you go" modals)

---

## Phase 2: Scaffold the Connector

### 2.1 — Create the File

```
extractors/{institution}_connector.py
```

Start from the base class `InstitutionConnector` in `skills/institution_connector.py`. The minimum required overrides:

```python
class FidelityConnector(InstitutionConnector):
    @property
    def institution(self) -> str:
        return "fidelity"

    @property
    def display_name(self) -> str:
        return "Fidelity"

    @property
    def export_url(self) -> str:
        return "https://..."  # Dashboard / portfolio URL

    @property
    def login_url(self) -> str:
        return "https://..."  # Direct login page URL (after any redirects)

    def _is_post_login(self, page) -> bool:
        ...

    def _perform_login(self, page, credentials=None) -> bool:
        ...

    def _trigger_export(self, page, accounts) -> list[Path]:
        ...

    def _perform_logout(self, page) -> None:
        ...
```

### 2.2 — Register the Connector

1. **`run_all.py`** — add to `CONNECTORS` dict
2. **`config/accounts.yaml`** — add accounts with `last4`, `type`, `name`
3. **`config/refresh_policy.yaml`** — set refresh interval
4. **`dal/database.py`** — add to `INSTITUTION_METADATA` seed data
5. **`extractors/selector_registry.yaml`** — add login + logout selector groups

### 2.3 — Add Selectors to Registry

Always add selectors **before** writing the connector code. This forces you to confirm the actual DOM structure:

```yaml
fidelity:
  login:
    username:
      intent: "Username field on Fidelity login page"
      selectors:
        - 'input#userId'
        - 'input[name="username"]'
    password:
      intent: "Password field on Fidelity login page"
      selectors:
        - 'input#password'
        - 'input[type="password"]'
    submit:
      intent: "Log In button on Fidelity login page"
      selectors:
        - 'button[type="submit"]'
        - 'button:has-text("Log In")'
  logout:
    signout_link:
      intent: "Log Out button on Fidelity"
      selectors:
        - 'a:has-text("Log Out")'
```

---

## Phase 3: Iterative Development

### 3.1 — Use `--dev` Mode

```
python run_all.py --institutions fidelity --force --dev
```

`--dev` mode:
- Skips browser cleanup (preserves existing session)
- Skips logout (preserves authenticated state)
- Allows rapid re-runs without re-authenticating

### 3.2 — Build in Stages

Do **not** try to implement everything at once. Build and test each lifecycle phase independently:

1. **Login first** — get credentials flowing, MFA handled, post-login detected
2. **Navigation second** — confirm you can reach the data pages
3. **Scraping third** — extract the actual data
4. **Persistence fourth** — write to DB / delta-log
5. **Logout last** — add cleanup only after the core flow works

### 3.3 — Debug with Browser Subagent

When selectors break or the DOM is unclear:
- Use the browser subagent to navigate to the page and inspect DOM
- Take screenshots at each step
- Use `execute_browser_javascript` to query elements and get their attributes
- Don't guess at selectors — verify them live

---

## Phase 4: Common Pitfalls & Solutions

### SPA Navigation Timing

**Problem**: SPA pages fire `domcontentloaded` before the actual content renders.

**Solution**: Always follow `.goto()` with an explicit wait:

```python
page.goto(url, wait_until="domcontentloaded", timeout=30000)
page.wait_for_selector("input#email", state="visible", timeout=10000)
```

### Login URL Redirects

**Problem**: `app.example.com/login` redirects to `auth.example.com/sign-in` — a different domain with different selectors.

**Solution**: Set `login_url` to the **final** destination, not the redirect source. Browse to the login page manually first to discover the real URL.

### Popup / Modal Blocking

**Problem**: Promotional popups, surveys, or "are you sure?" dialogs block logout or navigation.

**Solution**: The base class `_safe_logout()` calls `_dismiss_blocking_popups()` automatically, which tries common close/dismiss selectors. If an institution has a known recurring popup, add specific selectors to the connector or registry.

### New Tabs / Popups from Clicks

**Problem**: A click opens content in a new tab, creating a zombie tab.

**Solution**: Use `open_transient_tab` from the base class:

```python
with self.open_transient_tab(context, trigger=lambda: btn.click()) as new_page:
    # work with new_page
    data = new_page.inner_text("body")
# tab is auto-closed here
```

**Never** manually manage tab lifecycle with try/finally. See: `resource-session-management.md`.

### DOM Scraping Fragility

**Problem**: CSS selectors break when the site updates its UI.

**Solution**: Use multiple fallback strategies:
1. **Selector registry** with ordered fallbacks (tried first-to-last)
2. **JS evaluation** for robust extraction:
```python
value = page.evaluate("""
    (() => {
        const el = document.querySelector('h1');
        return el ? el.innerText.trim() : null;
    })()
""")
```
3. **AI backstop** (if available) — `resilient_find()` and `resilient_click()` call the DOM Healer when all selectors fail

### Investment Data: Delta-Logging Pattern

**Problem**: Investment connectors don't download CSVs — they scrape live portfolio data.

**Solution**: Use the delta-logging pattern from Acorns:
1. Scrape current positions (ticker, shares, value)
2. Compare to last snapshot in `investment_positions` table
3. Only log changes (new holdings, changed share counts)
4. Write snapshots to `investment_snapshots` table via DAL

```python
from dal.database import upsert_investment_snapshot, upsert_investment_position
```

### Phone Link OTP

When an institution uses SMS MFA:
- The `wait_for_otp()` function from `extractors/sms_otp.py` handles everything
- It wakes Phone Link, polls for the OTP, and auto-minimizes Phone Link after capture
- Usage: `from extractors.sms_otp import wait_for_otp`

---

## Phase 5: Finalize & Verify

### 5.1 — End-to-End Test

```
python run_all.py --institutions fidelity --force
```

Verify:
- ✅ Login succeeds (broker credentials + MFA)
- ✅ Data extraction completes (balances, transactions, or positions)
- ✅ Data persists to database
- ✅ Logout executes (`🔓 Logged out of Fidelity`)
- ✅ No zombie tabs remain
- ✅ Browser closes at pipeline end (`🧹 Browser closed`)

### 5.2 — Commit Checklist

- [ ] Connector file: `extractors/{institution}_connector.py`
- [ ] Selector registry: logout + login groups added
- [ ] Config files: `accounts.yaml`, `refresh_policy.yaml`
- [ ] Database seed: `dal/database.py` metadata
- [ ] Run registry: `run_all.py` CONNECTORS dict
- [ ] No temporary/debug files left behind
- [ ] No credentials in source code

---

## Quick Reference: Base Class Lifecycle

```
run(force, credentials, dev_mode)
  ├── _launch(context_manager)  →  opens tab, yields page, closes tab
  │   ├── _is_session_valid()   →  navigate to export_url, check redirect
  │   ├── _perform_login()      →  fill credentials, submit
  │   ├── _wait_for_mfa()       →  poll for post-login state
  │   ├── _trigger_export()     →  YOU IMPLEMENT THIS
  │   ├── _safe_logout()        →  _dismiss_blocking_popups() + _perform_logout()
  │   └── tab closed automatically
  └── state updated
```

Key methods to override: `_perform_login`, `_trigger_export`, `_perform_logout`, `_is_post_login`

Optional overrides: `_is_session_valid`, `_wait_for_mfa`
