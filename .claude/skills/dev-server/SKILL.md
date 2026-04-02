---
name: dev-server
description: Start backend and frontend dev servers with dummy data seeded, open UI in browser. Use for development, troubleshooting, or verifying UI changes.
user-invocable: true
---

# Dev Server Startup

Launch the full Sentry Finance dev stack in the browser with dummy data.

## Step 1: Kill existing servers

Check ports 8000 (backend) and 1420 (frontend). Kill any processes holding them.

```bash
# Check and kill port 8000
netstat -ano | grep ":8000 " | head -5
# Check and kill port 1420
netstat -ano | grep ":1420 " | head -5
```

If ports are occupied, kill the PIDs with `taskkill /PID <pid> /F`.

## Step 2: Seed dummy data

The backend reads from `data/dummy.db` (configured in `.claude/launch.json`).
The seed script must target the same DB path via `SENTRY_DB_PATH`.

```bash
cd "/c/Users/chang/OneDrive/Desktop/Projects/Personal Finance Project"
SENTRY_DB_PATH=data/dummy.db python scripts/seed_dummy_data.py
```

If this fails with a foreign key constraint, check that `vehicle_valuations` is
deleted before `vehicle_assets` in the seed script.

## Step 3: Start the backend API (background)

```bash
cd "/c/Users/chang/OneDrive/Desktop/Projects/Personal Finance Project"
SENTRY_DB_PATH=data/dummy.db python -m uvicorn backend.api_server:app --host 127.0.0.1 --port 8000
```

Run this in the background. Wait a few seconds, then verify:

```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/accounts
```

Expected: `200`. If the backend fails to start, check for import errors or
missing dependencies (`pip install -r requirements.txt`).

## Step 4: Start the frontend dev server (background)

Use `npm run dev` (Vite only, no Tauri) so the app opens in a browser rather
than the desktop wrapper.

```bash
cd "/c/Users/chang/OneDrive/Desktop/Projects/Personal Finance Project/frontend"
node node_modules/vite/bin/vite.js dev --host 127.0.0.1 --port 1420
```

Run in background. Wait for Vite to report ready.

## Step 5: Open browser and verify

```bash
start http://localhost:1420
```

Verify frontend is serving:
```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:1420/
```

Expected: `200`.

## Final state

Report to the user:
- Backend: http://127.0.0.1:8000 (status)
- Frontend: http://127.0.0.1:1420 (status)
- Database: `data/dummy.db` (seeded/existing)

## Known issues

- `SENTRY_DB_PATH` must be set for BOTH the seed script and the backend server,
  otherwise they use different databases and the UI shows no data.
- Python 3.14 emits a SyntaxWarning about `\s` in the seed script docstring.
  This is cosmetic and does not affect execution.
- The seed script is safe to re-run (deletes seeded rows first).
- If `npm run dev` fails with `EADDRINUSE`, the port check in Step 1 missed a
  process. Vite uses `strictPort: true` so it will not pick an alternate port.
