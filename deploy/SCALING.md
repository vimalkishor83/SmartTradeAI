# Scaling & Deployment Runbook

How to run SmartTradeAI as a horizontally-scalable service, and how to deploy
and roll back safely. Complements `deploy/README.md` (the single-machine
IIS runbook), which remains valid for a LAN deployment.

## The one rule

**Exactly one process runs background work. Every other process serves HTTP.**

`create_app()` used to start the APScheduler roster *and* the Delta Exchange
WebSocket ingest in every process. That is why the Dockerfile was pinned to
`-w 1`: a second worker meant a second copy of every scheduled job — double the
outbound exchange polling (risking upstream rate-limit bans), double the
nightly backups, retrains, and notification dispatch.

That work is now gated on `RUN_SCHEDULER`:

| Process | `RUN_SCHEDULER` | Runs scheduler + market stream | Serves HTTP |
|---|---|---|---|
| `worker.py` (exactly one) | `1` | yes | no |
| web replicas (scale freely) | `0` | no | yes |
| single-process deployment (default) | unset → `1` | yes | yes |

`RUN_SCHEDULER` defaults to `1`, so existing single-process deployments are
unaffected by this split.

## Topologies

### Single process (default — unchanged behaviour)

```bash
docker run -p 8000:8000 --env-file .env smarttradeai
# or: python serve.py   (IIS reverse-proxy deployment)
```

### Scaled out (web tier + one worker)

```bash
docker compose up -d          # web (RUN_SCHEDULER=0, 4 gunicorn workers) + worker + db + redis
docker compose up -d --scale app=3
```

**Never `--scale worker=2`.** That reintroduces exactly the duplication this
split exists to prevent.

## What scaling out requires

Horizontal scale is only correct with shared state. `REDIS_URL` is what makes
these shared; without it each process keeps its own copy:

| Concern | Without Redis | With `REDIS_URL` |
|---|---|---|
| Rate limiting | per-process; limits N× weaker | global |
| Cache (`CACHE_TYPE`) | per-process; instances disagree | shared |
| Socket.IO delivery | process-local; clients miss events emitted by other processes | fanned out via `SOCKETIO_MESSAGE_QUEUE` |

The app logs a warning at boot when running in production without these.

### Still process-local (known limitation)

`app/services/data/fetcher.py` keeps its OHLCV/ticker caches and per-provider
circuit breakers in module-level dicts. With N web replicas these are **not**
shared, so upstream fetches and circuit-breaker state are duplicated per
process. This is bounded (the worker owns the scheduled prewarm fetches), but
moving them onto the Redis-backed cache is the next scaling step before going
much beyond a handful of replicas.

## Health endpoints

- `GET /api/v1/system/health` — liveness. Cheap, never touches dependencies.
- `GET /api/v1/system/ready` — readiness. 503 if DB, Redis (when
  `CACHE_TYPE=RedisCache`), or the scheduler is unusable.

`/ready` is scheduler-role-aware: a web replica with `RUN_SCHEDULER=0` reports
the scheduler as healthy/not-applicable, so it is not pulled from the load
balancer for not running jobs it was never meant to run.

Wire orchestrators to `/ready`, not `/health` — `/health` reports "up" even
when the database is unreachable. Both Dockerfile `HEALTHCHECK` and the
compose healthchecks already point at `/ready`.

## Deploy procedure

Order matters: migrations first, while the old code is still serving.

```bash
# 1. Verify CI is green on the commit being deployed.

# 2. Back up the database. Non-negotiable — this is the rollback path.
pg_dump "$DATABASE_URL" > backup-$(date +%F-%H%M).sql

# 3. Apply migrations BEFORE new code. Migrations must be backward-compatible
#    with the currently-running version so the old code keeps working
#    mid-deploy (add columns nullable; never drop a column in the same
#    release that stops writing it — drop it a release later).
flask db upgrade

# 4. Roll out the new image.
docker compose up -d --build

# 5. Confirm readiness before considering the deploy done.
curl -fsS localhost:8000/api/v1/system/ready | jq .
```

## Rollback

```bash
# Code-only regression (no schema change): redeploy the previous image.
docker compose up -d --build   # with the previous tag

# Schema change to undo — every migration in this repo has a real downgrade(),
# and CI proves upgrade->downgrade->upgrade round-trips on Postgres.
flask db downgrade -1
```

If a migration was destructive (dropped a column or table), `downgrade()`
restores the *schema* but not the *data* — restore the dump from step 2
instead. This is why step 2 is not optional.

## Environments

The audit that prompted this document found `FLASK_ENV=production` pointed at a
**SQLite file shared with local development**, with no staging environment.
Before treating any deployment as production:

1. Give production its own Postgres instance (`DATABASE_URL`), never a shared
   SQLite file.
2. Stand up a staging environment matching production, and apply every
   migration there first.
3. Set `SEED_ADMIN_PASSWORD` — the initial admin seed refuses to run in
   production without it rather than installing the well-known demo password.
4. Set `CORS_ORIGINS` to an explicit allowlist. A wildcard causes credentialed
   CORS to be disabled (safe, but cross-origin browser clients will break).
