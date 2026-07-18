# Deploying SmartTradeAI on IIS (this machine, LAN-only)

## Why this shape, not classic wfastcgi

This app uses WebSockets (live price stream) and a background job scheduler
that must run in exactly **one** process (duplicate schedulers would
double-generate signals). Classic wfastcgi hosts Python directly inside IIS's
worker process, which can't do WebSockets and makes "exactly one process"
hard to guarantee. So instead:

- The app keeps running exactly as it does today — as its own long-lived
  Python process (`serve.py`, bound to `127.0.0.1:5000` only).
- IIS's only job is to be the public listener on port 80 and reverse-proxy
  everything to that process (via Application Request Routing + URL Rewrite).

```
[ Browser ]  --port 80-->  [ IIS + ARR + URL Rewrite ]  --127.0.0.1:5000-->  [ serve.py ]
```

## What's already done

- `.env` — production secrets generated, `FLASK_ENV=production`,
  `DATABASE_URL` pointed at the same DB the dev server has been using
  (`instance/smarttrade_dev.db`) so existing users/signals carry over.
  `FORCE_INSECURE_COOKIES=true` is set because there's no TLS cert yet —
  **remove that line the moment you add HTTPS to the IIS site.**
- `serve.py` — production entry point, binds to `127.0.0.1` only (verified
  it boots and serves correctly).
- `deploy/iis_site/web.config` — the reverse-proxy rule IIS will use.
- `deploy/setup_iis.ps1` — one-time IIS setup (idempotent, safe to re-run).
- `deploy/install_service.ps1` — registers `serve.py` as an auto-starting,
  auto-restarting Windows service via NSSM.

## What you need to run yourself (all require admin / a UAC prompt)

### 1. Install ARR and URL Rewrite (no silent installer available)

Download and run both installers:
- Application Request Routing: https://www.iis.net/downloads/microsoft/application-request-routing
- URL Rewrite: https://www.iis.net/downloads/microsoft/url-rewrite

### 2. Run the IIS setup script (elevated PowerShell)

```powershell
cd D:\Claude\SmartTradeAI\deploy
.\setup_iis.ps1
```

This enables the IIS + WebSocket Windows features, turns on ARR's proxy
mode, and creates an IIS site named `SmartTradeAI` on port 80 pointing at
`deploy\iis_site`. Re-run anytime — every step checks current state first.

Pass `-Port 8080` (or similar) if port 80 is already taken on this machine.

### 3. Get the app process running as a service

**Option A — NSSM (recommended, auto-restarts on crash):**

Download NSSM from https://nssm.cc/download (grab the win64 build), then:

```powershell
cd D:\Claude\SmartTradeAI\deploy
.\install_service.ps1 -NssmPath "C:\path\to\nssm.exe"
```

**Option B — Task Scheduler (no download needed, slightly less robust):**

1. Open Task Scheduler → Create Task
2. General tab: "Run whether user is logged on or not", check "Run with
   highest privileges"
3. Triggers tab: New → "At startup"
4. Actions tab: New → Program: `C:\Program Files\Python312\python.exe`,
   Arguments: `serve.py`, Start in: `D:\Claude\SmartTradeAI`
5. Settings tab: check "Restart the task every 1 minute" with a high retry
   count, so it comes back if it crashes

### 4. Verify

From this machine: http://localhost/
From another device on the LAN: `http://<this-machine's-LAN-IP>/`
(find the LAN IP with `ipconfig`)

Log in with the existing admin account (unchanged — same DB as dev).

## If something's wrong

- **Blank page / 502-ish behavior**: check the app process is actually
  running (`nssm status SmartTradeAI` or Task Scheduler's task history) and
  listening on 5000 — `curl http://127.0.0.1:5000/login` from that machine
  should return HTML.
- **Live price stream not updating / console WebSocket errors**: confirm the
  `IIS-WebSockets` Windows feature is enabled and ARR's proxy mode is on
  (`setup_iis.ps1` does both — re-run it).
- **Logs**: `logs\app.log` (application) and `logs\service_stdout.log` /
  `service_stderr.log` (process-level, only if using NSSM).

## Moving to a real domain + HTTPS later

When you're ready to expose this beyond the LAN:
1. Get a TLS certificate for your domain, bind it to the IIS site (IIS
   Manager → site → Bindings → Add → https).
2. Remove `FORCE_INSECURE_COOKIES=true` from `.env` and restart the service.
3. Tighten `CORS_ORIGINS` in `.env` to your real domain instead of `*`.
