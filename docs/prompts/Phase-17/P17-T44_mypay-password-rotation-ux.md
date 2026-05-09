# P17-T44: myPay Password Rotation UX

## Context

myPay periodically forces a password-change decision after login. P17-T42
made the connector safe by selecting `Remind Me Later` and recording a
`credential_action_needed` notification. That keeps refresh from blocking, but
it leaves the actual rotation as a manual follow-up.

The user is currently inside the countdown window before myPay requires the
change. This task adds the pieces needed to let the dashboard offer the choice
at the moment the connector sees the prompt.

## Task

Implement a human-in-the-loop credential action flow:

- emit a non-secret SSE action request when myPay shows the password-change
  prompt,
- show a persistent dashboard toast with `Change now` and `Remind me later`,
- default to `Remind me later` when the UI is absent or the prompt times out,
- when `Change now` is selected, leave the live myPay browser for the user to
  rotate the password and wait for the page to return to a post-login state,
- provide a convenient secure way to update the OS credential entry after the
  website accepts the new password,
- never send the updated password through the dashboard or browser app.

## Security Boundary

The dashboard may send only choices (`change_now` or `remind_later`) and a
request to open the local credential broker. The updated myPay password must be
typed into `backend/credential_broker.py --store mypay`, which writes to the
existing OS-backed credential store.

## Verification

Unit/compile verification:

```powershell
python -m py_compile backend\credential_action_bridge.py backend\routers\credential_actions.py extractors\mypay_connector.py
python -m pytest tests\test_credential_action_bridge.py tests\test_credential_actions_router.py tests\test_mypay_connector.py -q
npm --prefix frontend run build
```

Live verification should be limited. myPay may begin throttling or blocking
after repeated login attempts.

## Outcome

Implemented and partially live-tested.

- Added a `credential_action_required` SSE topic and in-memory bridge.
- Added `/api/credential-actions/respond` for the toast choice.
- Added `/api/credential-actions/launch-credential-store` to open the local
  credential broker without transporting credential values through the UI.
- Added root-level dashboard toast handling for myPay password prompts.
- Updated the connector to wait for a browser-completed password change when
  selected, or click `Remind Me Later` and record the durable notification.
- Live test on 2026-05-09 showed the first failure was not a myPay cert issue:
  the connector attached to a stale default Chrome process on CDP port 9222
  instead of launching `C:\ChromeAutomationProfile`. The automation profile
  could load myPay normally. `extractors/chrome_cdp.py` now refuses an active
  debug port unless the owning Chrome command line includes the automation
  profile path.
- Gmail OTP capture worked against the live myPay email challenge.
- The myPay password-change prompt was detected. When tested through direct
  `run_all.py`, the dashboard toast did not receive the SSE because `run_all.py`
  runs in a separate process from `backend.api_server`; the in-memory SSE
  subscriber list is process-local. Toast verification must use a backend/API
  refresh path, or the credential-action bridge needs a cross-process transport
  before CLI runs can surface dashboard toasts.
- After `Remind Me Later` and the DoD consent screen, myPay landed on the
  `Marine Military Retiree` page with RAS navigation hidden. A screenshot showed
  the hamburger account menu and top-right overflow menu; the connector now
  opens both menus before declaring the RAS link missing.
