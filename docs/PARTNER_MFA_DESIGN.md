# Partner MFA — Design & Build Plan

> **Status:** Design closed; build deferred until partner banking ingestion is
> the active phase. Authored 2026-04-14 during the investments-rebuild branch
> as a forward-looking decision document. No code changes were made for this
> design — only the architecture was settled.

## Why This Matters

The whole reason this app exists is to defeat the limiting factor of
aggregators (Plaid/Mint/Monarch) by bringing data collection in-house. That
works because the sole user is also the sole MFA destination — login codes hit
*his* phone, captured by *his* Windows Phone Link, on *his* logged-in Windows
account.

Adding Amy breaks every one of those assumptions:

- Her bank texts go to *her* phone.
- Her credentials shouldn't be readable by his Windows session.
- She's only sometimes physically near the household machine.
- The existing `mfa_bridge.py` only holds one pending MFA at a time and has no
  owner context at all.

If we don't solve this deliberately, we get one of three failure modes:
data goes stale because nobody can complete Amy's MFA, credentials leak across
the partner boundary, or the UX is so painful Amy stops engaging.

## What's Single-User Today

| Layer | Current single-user assumption |
|-------|-------------------------------|
| `backend/mfa_bridge.py` | Global thread-event, one institution pending at a time, no `owner_id` |
| `backend/routers/mfa.py` (`/api/mfa/submit`) | No owner context; whoever POSTs sets the code |
| `backend/credential_broker.py` | Reads from Windows Credential Manager of the running Windows user only |
| `extractors/sms_otp.py` | Captures from Windows Phone Link — bound to the running Windows user's paired phone |
| Phone Link itself | Pairs to **one** phone per Windows user account |
| `backend/refresh_orchestrator.py` | On-demand, assumes user-at-keyboard; 30-min wall-clock cap |
| Refresh workflow | One "Refresh All" button, no per-owner gating |

**One thing that's NOT broken: the `owners` data model.** `dal/owners.py`
already threads `owner_id` cleanly through DAL → API → frontend. The plumbing
for "this account belongs to Amy" exists. What's missing is the *credential
and MFA path* for Amy's accounts.

## The Five Real Problems (in priority order)

1. **Where does Amy's bank send the code, and how does the app receive it?**
   Her phone. The current SMS capture is one-phone-only.
2. **Who's holding Amy's bank passwords?** Currently nobody; her credentials
   don't exist in the broker. Need to extend the broker's namespace to support
   per-owner credentials without letting one owner's session read the other's
   secrets.
3. **Is Amy physically present when her accounts refresh?** If yes, problem 1
   reduces to "she reads code off her phone, types it into the app." If no,
   you need a routing mechanism.
4. **Can two MFA prompts be in-flight simultaneously?** Right now no
   (`mfa_bridge` global single-pending). For multi-account refresh this
   becomes a problem.
5. **Does Amy trust the household machine with her credentials at all?** Soft
   factor but real. Some partners draw a line here.

## Constraints That Drove the Recommendation

Settled during the design discussion:

- Amy uses **Android** → Tasker auto-forwarding is viable.
- Amy is **sometimes not at the household machine** → can't rely on
  walk-over-and-type model alone.
- Refresh cadence target is **daily** (4–5×/week minimum) → can't queue-
  until-she-opens-the-app.
- Tolerance for setup is **"whatever it takes for hands-off"** → Tailscale +
  Tasker + dedicated endpoint is acceptable.

## Recommended Architecture

```
Amy's Android phone                Household Windows PC
───────────────────                ─────────────────────
                                   ┌─ Sentry FastAPI :8000 ──────────┐
NFCU SMS arrives                   │                                 │
  ↓                                │  POST /api/mfa/forward          │
Tasker matches sender ────HTTPS────┼─→ {sender, body, ts, hmac}      │
  ↓                                │      ↓                          │
Tasker extracts 6-digit OTP        │  Auth (HMAC-SHA256)             │
  ↓                                │      ↓                          │
Tasker POSTs over Tailscale        │  Sender → (owner, institution)  │
http://sentry-pc.tailnet:8000/...  │      ↓                          │
                                   │  Idempotency check              │
                                   │      ↓                          │
                                   │  mfa_bridge.submit_code(        │
                                   │    owner_id="amy",              │
                                   │    institution="nfcu",          │
                                   │    code="123456")               │
                                   │      ↓                          │
                                   │  TSP/NFCU/etc connector unblocks│
                                   └─────────────────────────────────┘
```

### Why Tailscale, Not the Public Internet

Tailscale is a WireGuard mesh. Both devices have private addresses on a
shared tailnet. Traffic between them never traverses Tailscale's servers
(after the initial handshake). It's the practical equivalent of "Amy's phone
is always on the household LAN" without opening any public ports. The
local-first guardrail in `CLAUDE.md` is preserved because no third-party
service holds household financial data — Tailscale only routes packets and
never sees their contents.

### Why HMAC on Top of Tailscale

Belt-and-suspenders. If the Tailscale layer ever fails or is misconfigured,
the endpoint won't accept arbitrary POSTs. Replay attacks are also bounded
by the OTP's 5-minute bank-side TTL.

## Build Phases

### Phase 1 — Multi-owner plumbing (foundation)

**Files:**

- `backend/mfa_bridge.py` — replace global single-pending state with
  `dict[(owner_id, institution_id), {event, code, created_at}]`. New
  signatures:
  - `wait_for_code(owner_id, institution, timeout_seconds=300) -> str | None`
  - `submit_code(owner_id, institution, code) -> bool`
  - `is_pending(owner_id=None, institution=None) -> list[(owner, inst)]`
  - Reject duplicate `(owner, institution, code)` submitted within 60s
    (Tasker retry idempotency).
- `backend/routers/mfa.py` — `/api/mfa/submit` accepts `owner_id` field;
  `/api/mfa/status` returns list of pending MFAs.
- `backend/events.py` — `mfa_required` SSE events include `owner_id`.
- `backend/credential_broker.py` — namespace credential keys as
  `SentryFinance:{owner_id}:{institution_id}`. Backward-compat shim: keys
  without owner segment resolve to primary owner.
- `extractors/*_connector.py` — each connector takes `owner_id` in its
  constructor and passes it through to `wait_for_code()` calls. Where
  connectors call `wait_for_otp()` from `sms_otp.py`, that path stays as the
  Phone Link fallback (Quintin's existing flow unchanged).
- `frontend/src/components/MfaPromptModal.tsx` — show owner name in the
  prompt header so it's clear whose account is waiting.

### Phase 2 — Per-owner refresh control

**Files:**

- `backend/refresh_orchestrator.py` — accept `owner_filter: str | None` in
  `run()`; only refresh accounts where `owner_id` matches.
- `backend/routers/refresh.py` — `/api/refresh/start` accepts `owner_id`
  query param.
- `frontend/src/components/RefreshButton.tsx` — when active view is "Amy" or
  "Quintin," refresh scopes to that owner. "Household" refreshes all.

### Phase 3 — SMS forwarding endpoint

**New file:** `backend/routers/mfa_forward.py`

- `POST /api/mfa/forward`
- Request body: `{"sender": "FRM-NFCU", "body": "Your NFCU code is 123456", "received_at": "2026-04-14T18:32:11Z"}`
- Headers: `X-Sentry-HMAC: <hex>` (HMAC-SHA256 of body with shared secret).
- Endpoint logic:
  1. Verify HMAC. Reject 401 if invalid.
  2. Look up `sender` in a config-driven map (`config/sms_routing.yaml`):
     - `"FRM-NFCU"` → `(owner_id="amy", institution_id="nfcu")`
     - `"Chase"`     → `(owner_id="amy", institution_id="chase")`
     - etc.
  3. If sender unmapped → 200 OK, no-op (silently ignore — Tasker can be
     greedy). Log the unknown sender for the user to add later.
  4. Extract OTP via regex (`\b\d{6}\b` default; per-institution overrides).
  5. Idempotency: if `(owner, institution, code)` was just processed within
     60 seconds, return 200 OK without re-submitting.
  6. Call `mfa_bridge.submit_code(owner_id, institution, code)`. If no MFA
     is pending for that pair, return 200 OK with
     `{"status": "no_pending_mfa"}` — Tasker shouldn't retry.

**New file:** `config/sms_routing.yaml`

- Sender → (owner, institution) mapping
- Per-institution OTP regex overrides (Chase uses 8 digits, etc.)
- Shared HMAC secret reference (actual secret stored in Windows Credential
  Manager, not in the file)

### Phase 4 — Tailscale overlay

Setup-only (no code). Documentation in `docs/MULTI_USER_SETUP.md`:

- Install Tailscale on household Windows machine. Note its tailnet hostname
  (e.g., `sentry-pc.taile1234.ts.net`).
- Install Tailscale on Amy's Android phone. Sign into the same tailnet.
- Verify reachability:
  `curl http://sentry-pc.taile1234.ts.net:8000/api/health` from her phone's
  browser.
- Configure FastAPI to bind on `0.0.0.0:8000` for tailnet exposure (currently
  localhost-only). Add tailnet IP allowlist middleware so only tailnet
  sources can hit the API.

### Phase 5 — Tasker profile on Amy's phone

**Configuration (deliverable: a Tasker XML export Amy can import):**

- **Profile**: Event → Phone → Received Text → Sender Filter
- **Senders**: configured per institution (NFCU, Chase, etc.)
- **Task action 1**: Variables → Variable Set
  - `%CODE` ← regex match `\d{6}` from `%SMSRB`
- **Task action 2**: HTTP Request
  - Method: POST
  - URL: `http://sentry-pc.taile1234.ts.net:8000/api/mfa/forward`
  - Headers: `Content-Type: application/json`, `X-Sentry-HMAC: %HMAC`
    (computed via Tasker JavaScriptlet using stored secret)
  - Body: `{"sender": "%SMSRF", "body": "%SMSRB", "received_at": "%TIMES"}`
  - Timeout: 10 seconds
- **Task action 3**: on failure (non-200), log to Tasker log only — do NOT
  retry. App will time out and fall back to manual entry.

### Phase 6 — Failure-mode handling & UI surfacing

- If MFA bridge times out (300s), connector aborts with `AUTH_REQUIRED`
  state and SSE emits a notification: "Amy's NFCU refresh failed — no MFA
  code received. Tap to retry manually."
- Frontend Notifications panel surfaces these distinctly per owner.
- Manual entry path stays as today (UI modal, type code in) — used both as
  Tasker's safety net and as Quintin's existing flow.

### Phase 7 — Optional symmetry for Quintin

Quintin's Phone Link path keeps working unchanged. If he wants to retire it
later and use Tasker on his phone too, the same `/api/mfa/forward` endpoint
serves both — just add his sender mappings to `sms_routing.yaml`. Not
required; listed for symmetry.

## Critical Files to Modify (Build Time)

| Layer | File | Change type |
|-------|------|-------------|
| Bridge | `backend/mfa_bridge.py` | Rewrite (multi-owner state) |
| API | `backend/routers/mfa.py` | Add `owner_id` to existing endpoints |
| API | `backend/routers/mfa_forward.py` | **New** — Tasker endpoint |
| API | `backend/routers/refresh.py` | Add `owner_filter` param |
| Orchestrator | `backend/refresh_orchestrator.py` | Honor `owner_filter` |
| Credentials | `backend/credential_broker.py` | Owner-namespaced keys |
| Connectors | `extractors/*_connector.py` | Pass `owner_id` through |
| Events | `backend/events.py` | `owner_id` in `mfa_required` event |
| Config | `config/sms_routing.yaml` | **New** — sender map |
| Frontend | `frontend/src/components/MfaPromptModal.tsx` | Show owner name |
| Frontend | `frontend/src/components/RefreshButton.tsx` | Per-owner scoping |
| Docs | `docs/MULTI_USER_SETUP.md` | **New** — Tailscale + Tasker setup |
| Docs | `docs/ARCHITECTURE.md` §3.3 | Document multi-owner MFA flow |

## Reuse Notes

- `backend/credential_broker.py` IPC contract (UAC elevation, secure delete)
  is reused as-is — only the key namespace changes.
- `extractors/sms_otp.py` Phone Link path stays for Quintin; not removed.
- `dal/owners.py::build_account_filter()` already does the
  `None`-vs-`[]` distinction needed for owner-scoped refreshes.
- Existing SSE event bus (`backend/events.py`) already broadcasts
  `mfa_required`; we're just adding `owner_id` to the payload, not building
  a new channel.

## Verification Scenario (Build Time)

End-to-end test scenario, post-implementation:

1. Quintin clicks "Refresh All" from the Household view.
2. NFCU connector starts for Quintin's account → his Phone Link captures the
   SMS as it does today → submitted via existing path. (Regression: must
   still work.)
3. NFCU connector starts for Amy's account in parallel → SSE emits
   `mfa_required` with `owner_id="amy"`.
4. Amy's NFCU SMS arrives on her Android phone → Tasker matches sender →
   POSTs to `/api/mfa/forward`.
5. Endpoint validates HMAC, looks up sender → `(amy, nfcu)`, extracts OTP,
   submits to `mfa_bridge`. Connector unblocks, completes scrape.
6. Repeat for a second institution simultaneously to confirm multi-pending
   bridge state works.
7. Verify per-owner UI badges and notifications surface correctly.
8. Negative test: kill Tasker, run again, confirm fallback prompt appears
   in UI and Amy can type code manually.
9. Negative test: send SMS from spoofed sender, confirm endpoint rejects
   (sender not in routing map → no_pending_mfa response, no submit).
10. Run from off-network (Amy on cellular only) to confirm Tailscale
    routing works the same as on-LAN.

Tests:

- `pytest tests/test_mfa_bridge.py` — multi-owner state, dedup, timeout
- `pytest tests/test_mfa_forward.py` — HMAC, sender routing, regex
  extraction
- Manual: full end-to-end with real Tasker + Tailscale (one-time setup
  test)

## Security Properties

- **HMAC** means even if Tailscale is misconfigured, random POSTs are
  rejected.
- **Sender allowlist** in `sms_routing.yaml` means spam SMS can't trigger
  arbitrary submits.
- **Idempotency window** prevents Tasker retries from double-submitting.
- **Quintin's existing Phone Link path is unchanged** — no regression risk
  for the working single-user flow.
- **Bank-side OTP TTL** (~5 min) bounds replay risk if anything leaks.
- **Cred broker stays UAC-elevated**; per-owner namespacing means
  Quintin's Windows session can read both, but that's the trust model of
  "single shared household machine" anyway. If Amy ever wants stronger
  isolation, the upgrade path is to give her her own Windows user account
  on the household machine (Phase 1's broker change is forward-compatible).
