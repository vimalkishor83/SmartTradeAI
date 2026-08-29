# Going to Production — Config & Env Checklist

**Bottom line up front:** the *code* for production is already built — proper
WSGI server (gunicorn + eventlet), a dedicated background-job process, health
checks, at-rest credential encryption, and boot-time guardrails that refuse
to start with insecure defaults. What's actually missing before this is a
real production deployment is **configuration**: most of `.env.example`'s
production-relevant keys were never carried into the real `.env`. This
document is the checklist for that gap, plus where the database migrations
live and how to run them.

This complements, not replaces, the existing deploy docs:
- **[README.md](README.md)** — the IIS/Windows-service runbook (how this app
  is actually reachable today: `serve.py` behind IIS + ARR reverse proxy).
- **[SCALING.md](SCALING.md)** — Docker Compose horizontal scaling, the
  single-scheduler-process rule, backup/rollback procedure, and an existing
  audit of gaps (this checklist turns that audit into concrete action items).

---

## 1. Current state, verified directly (2026-08-29)

Checked the real `.env` (keys only, not values) against `.env.example` and
against what `app/config.py` actually reads. What's currently set:

```
CORS_ORIGINS, DATABASE_URL, ENCRYPTION_KEY, FLASK_ENV,
FORCE_INSECURE_COOKIES, JWT_SECRET_KEY, PORT, SECRET_KEY
```

That's 8 of the ~28 keys `.env.example` documents. The two concrete problems
this already causes, confirmed by the app's own boot-time warnings
(`app/config.py`'s `get_config()`):

1. **`FLASK_ENV=production` but `DATABASE_URL=sqlite:///smarttrade_dev.db`**
   — production and your local dev server are reading and writing the exact
   same SQLite file. There is currently no separation between dev data and
   production data. (A guardrail now logs a warning for this specific case —
   see `app/config.py`, the check right after the rate-limiter warning.)
2. **No `REDIS_URL`** — rate limiting, caching, and Socket.IO fan-out (the
   live price ticker, notifications) all silently degrade to single-process,
   in-memory behavior. Fine with exactly one process; breaks the moment you
   scale to more than one.

Neither of these crashes anything today because there's currently only one
process and no real separation between "dev" and "prod" — but both are
exactly the kind of thing that only surfaces as a problem once real users or
a second process are involved.

---

## 2. Env var checklist, by category

### Must set before treating this as real production

| Variable | Why | Current status |
|---|---|---|
| `SECRET_KEY`, `JWT_SECRET_KEY` | Session/JWT signing. App **refuses to boot** in production if either is still the placeholder default (`app/config.py`, `_INSECURE_DEFAULTS` check). | Set — confirmed present, not re-verified as non-default (can't check value without exposing a secret; if these were ever copied from `.env.example` literally, generate fresh random values). |
| `ENCRYPTION_KEY` | Encrypts stored credentials at rest (broker API keys, and now per-user Telegram bot tokens — `app/services/security/crypto.py`). Falls back to `SECRET_KEY` if unset, but a dedicated key means rotating `SECRET_KEY` later doesn't also break every stored credential. | Set. |
| `DATABASE_URL` | **Point this at a dedicated production database, not the dev SQLite file.** Postgres is already fully supported (`psycopg2-binary` is in `requirements.txt`, `docker-compose.yml`'s `db` service is Postgres 16). Format: `postgresql://user:password@host:5432/dbname`. | **Needs changing** — currently the dev SQLite file. |
| `SEED_ADMIN_PASSWORD` | On first boot against an *empty* database, the app seeds an admin account. In production it **refuses to boot** rather than use the well-known demo password (`admin@smarttradeai.com` / `Admin@123`, which is printed on the public login page). Only matters for a *fresh* database — the current dev DB already has an admin user, so this won't trigger until you point at a new, empty production database. | Not set — will block first boot against a fresh DB. |
| `CORS_ORIGINS` | Defaults to `*`. The app structurally disables credentialed CORS when this is `*` (so it isn't an open security hole), but that also means cross-origin browser clients relying on cookies won't work until this is a real allowlist. Only matters if the frontend and API end up on different origins — same-origin (the normal case here) is unaffected either way. | Set to `*` — fine for same-origin deployment (the IIS reverse-proxy setup makes everything same-origin already), revisit only if that changes. |
| `FORCE_INSECURE_COOKIES` | Currently `true`, which is correct for the current no-TLS-yet IIS/LAN setup (`deploy/README.md`) — **but must be removed the moment you put a TLS certificate in front of this**, or cookies stay non-Secure over HTTPS. | Set to `true` — tracked as a known temporary state in `deploy/README.md`'s own "moving to a real domain" checklist. |

### Should set once you're past a single-process deployment

| Variable | Why |
|---|---|
| `REDIS_URL` | Makes rate limiting, caching, and Socket.IO message delivery work correctly across more than one process. Required the moment you run more than one `app` container/worker (`docker-compose.yml` already wires this up — see `SCALING.md`). |
| `REDIS_PASSWORD` | Required by `docker-compose.yml` if you use it — Redis is started with `--requirepass`, not exposed on a host port. |
| `SOCKETIO_MESSAGE_QUEUE` | Defaults to `REDIS_URL` if unset. Only needs its own value if you want the Socket.IO queue on a different Redis instance/DB than caching. |
| `TRUSTED_PROXY_COUNT` | Defaults to `1` even when unset, which already matches the single-reverse-proxy topologies this app supports (IIS+ARR, or Docker behind one more proxy). Only change this if you add an *additional* proxy hop in front (e.g., a CDN in front of IIS) — count every hop or `X-Forwarded-For` becomes spoofable. |

### Optional features — dormant until configured, nothing breaks without them

| Variable | Feature |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Platform-wide fallback Telegram bot. As of this session, users can set their **own** bot token in Settings, which takes priority — this is only needed if you want a shared default bot for users who don't set their own. |
| `MAIL_SERVER` / `MAIL_PORT` / `MAIL_USERNAME` / `MAIL_PASSWORD` / `MAIL_DEFAULT_SENDER` | Email notifications. Without `MAIL_USERNAME`+`MAIL_PASSWORD`, the app sets `MAIL_SUPPRESS_SEND=True` automatically — emails are silently no-ops, not errors. |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_CLAIMS_EMAIL` | Web push notifications. Generate with `python scripts/gen_vapid_keys.py`. |
| `SENTRY_DSN` | Error tracking (`app/services/error_tracking.py` is fully wired, just dormant without this). Recommended before real users — it's the difference between hearing about a production error from a user report vs. from Sentry. |
| `BINANCE_API_KEY` / `BINANCE_SECRET` / `ALPHAVANTAGE_API_KEY` / `ZERODHA_API_KEY` / `ZERODHA_SECRET` / `NEWS_API_KEY` | Market data providers. Per `HOW_TO_RUN.md`, the app runs on free/keyless sources (Binance public API, Yahoo Finance) without any of these — only needed if you want a specific paid/authenticated provider instead. |
| `JWT_ACCESS_EXPIRES_HOURS` / `JWT_REFRESH_EXPIRES_DAYS` | Session length tuning. Defaults (24h / 30d) are reasonable; only change if you have a specific security requirement. |

---

## 3. Database migrations — where they are, how to run them

**Location:** `migrations/versions/*.py` — standard Alembic migrations (Python
scripts that generate SQL, not raw `.sql` files; this project doesn't hand-write
SQL). Managed by Flask-Migrate.

**Current state, verified directly against both the migration files and the
live dev database:**
```
$ python -m flask db heads
c9d1e2f3a4b5 (head)
```
One linear head, no branch conflicts. (The migration history does contain one
legitimate merge point further back — `d07e8fbd6e1c`, which already
reconciled an earlier fork — but the graph today resolves cleanly to a
single head.)

**To bring a new/existing production database up to date:**
```bash
# From the repo root, with DATABASE_URL pointed at the target database
python -m flask db upgrade
```
This is idempotent — running it against an already-current database is a
no-op. `SCALING.md`'s deploy procedure already sequences this correctly:
**back up the database, run `flask db upgrade`, *then* deploy the new code**
(migrations should land before the code that expects them, not after).

**To check what's pending without applying it:**
```bash
python -m flask db current   # what the target DB thinks its revision is
python -m flask db heads     # what the latest revision in the codebase is
```
If those two commands print different revisions, `flask db upgrade` has
something to do.

**Rollback:** `python -m flask db downgrade -1` for a code-only schema
revert. For anything that dropped or transformed data, `SCALING.md` is
explicit that a downgrade migration is *not* a substitute for restoring the
pre-migration backup — treat data-destructive migrations as one-way.

---

## 4. Choosing a deployment path

Both are already fully built; this isn't a build task, it's a choice:

- **Docker Compose** (`docker-compose.yml`) — `app` (gunicorn+eventlet,
  scalable), `worker` (exactly one, owns the scheduler — never scale this
  one), `db` (Postgres), `redis`. Best if you want horizontal scaling and are
  hosting somewhere Docker-friendly. Follow `SCALING.md` end to end.
- **IIS + Windows Service** (`serve.py`, `deploy/setup_iis.ps1`,
  `deploy/install_service.ps1`) — single-process, everything (web + scheduler
  + live price stream) in one Python process behind IIS as a reverse proxy.
  Matches the current LAN deployment. Follow `README.md` end to end; its
  final section is literally "moving to a real domain + HTTPS" with the
  `FORCE_INSECURE_COOKIES` removal already called out.

Don't run both against the same database at once — pick one, and if you
later migrate from IIS to Docker (or vice versa), that's the moment to also
resolve the SQLite → Postgres move from section 1.

---

## 5. Verifying a deployment

Both entry points expose the same two endpoints (`app/api/v1/system.py`):

- `GET /api/v1/system/health` — liveness (is the process up at all).
- `GET /api/v1/system/ready` — readiness: checks DB connectivity, Redis (if
  configured), and scheduler state; returns 503 if something's actually
  wrong. This is what `docker-compose.yml`'s healthchecks and the Dockerfile
  `HEALTHCHECK` already poll — same endpoint works for a manual `curl` check
  after any deploy.

---

## 6. Priority order, if doing this in one pass

1. Stand up a real production database (Postgres recommended) and point
   `DATABASE_URL` at it — stop sharing the dev SQLite file.
2. Run `python -m flask db upgrade` against it.
3. Set `SEED_ADMIN_PASSWORD` before that first boot.
4. Set `REDIS_URL` (and `REDIS_PASSWORD` if using Compose) — cheap to do now,
   expensive to debug later once you've already scaled past one process.
5. Set `SENTRY_DSN` — you want to hear about errors before users report them.
6. Everything else in the "optional features" table, as you actually need
   each feature.
7. When TLS is in place: remove `FORCE_INSECURE_COOKIES`, and if the frontend
   ever moves to a different origin than the API, tighten `CORS_ORIGINS`
   from `*` to an explicit allowlist.
