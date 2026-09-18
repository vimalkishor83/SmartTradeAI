# Working on this repo as an AI agent (Claude / Codex)

This file exists so either agent can pick up mid-task without re-deriving
conventions the other agent already established. Read it before starting
work; update it when a convention changes.

## Deploy infrastructure (built by Codex, restored/documented by Claude)

Deploys go through root-owned scripts on the server, not raw `docker
compose` commands run by hand:

- `/usr/local/sbin/smarttrade-deploy-development` — pulls `development`
  (fast-forward only), builds, migrates, restarts app+worker, health-checks
  `http://127.0.0.1:8100/api/v1/system/ready`. No confirmation flags —
  meant to run unattended from CI.
- `/usr/local/sbin/smarttrade-deploy-production` — pulls `main`, builds,
  restarts app+worker, health-checks `https://smarttradeai.online/api/v1/system/ready`.
  Requires **both** `--confirm-production` and `--execute` flags to do
  anything; migrations are a separate opt-in `--run-migrations` flag.
  Deliberately not wired to auto-run from a push — production deploys are
  a conscious, explicit action.
- `/usr/local/sbin/smarttrade-deploy-rollback` — reverts to the last
  recorded pre-deployment state (see `/var/lib/smarttrade-deploy/records/`).
- `/usr/local/sbin/smarttrade-safe-cleanup` — disk hygiene (see below).
- Shared logic lives in `/usr/local/libexec/smarttrade-deploy-common`
  (root-readable only).

The `ubuntu` server user already has unrestricted passwordless sudo (cloud-init
default) — these scripts don't need a dedicated sudoers rule to be invoked
as `sudo -n -- <script>`.

### `development` branch → auto-deploy via GitHub Actions

`.github/workflows/deploy-development.yml` (originally authored by Codex,
committed `d6cf2b3`, reverted `67eebc6` only because the push required a
`workflow`-scoped token that wasn't available at the time — **not** because
the design was wrong) runs on every push to `development`:

1. Pins the server's SSH host key inline in the workflow (not a secret —
   host keys are public identity, this just prevents MITM on first
   connect).
2. SSHes in using the `secrets.DEVELOPMENT_DEPLOY_KEY` repo secret and
   runs `sudo -n -- /usr/local/sbin/smarttrade-deploy-development`.
3. Any failure (bad SSH, script exits non-zero, health check times out)
   fails the workflow run loudly; nothing about the live containers
   changes on failure.

Deploys to `https://smarttradeai.info`.

### `main` branch → **manual** deploy (by design)

There is intentionally no `deploy-production.yml` auto-triggering on push
to `main`. Run production deploys by hand over SSH:

```
ssh ubuntu@140.238.247.245 sudo -n -- /usr/local/sbin/smarttrade-deploy-production --confirm-production --execute --run-migrations
```

(drop `--run-migrations` if there's nothing new to migrate this deploy). If
a future agent or the user wants this automated too, that's a real design
decision to make together first — don't wire up a silent auto-deploy to
production without discussing it, even though the script itself supports
being called from CI the same way development's is.

## One agent at a time per area

Only one of Claude or Codex should be actively editing a given area at
once. Before starting non-trivial work:
1. `git fetch` and check `git log` on the branch you're about to touch —
   don't assume the state you last saw is still current.
2. Before building new infrastructure (deploy scripts, workflows, cleanup
   jobs), check `/usr/local/sbin/`, `/etc/sudoers.d/`, and recent git log
   on the server for something the other agent already built — duplicate
   infra is worse than no infra.
3. If you're not sure whether the other agent is mid-task, ask the user.

## Local workspace convention

Three folders only, on Windows (`D:\Claude\...`) — don't create ad-hoc
`-workflow`, `-merge-work`, `-main-merge` style folders that outlive a
single task:

- `SmartTradeAI-main` — checked out on `main`.
- `SmartTradeAI-development` — checked out on `development`.
- `SmartTradeAI-scratch` — created fresh for one-off merges/experiments,
  deleted again once its work is committed and pushed. Never left as a
  standing checkout.

Each agent may also keep its own dedicated worktree/sandbox outside this
convention if that's how the harness sets it up (e.g. a
`SmartTradeAI-development-workflow` owned by a different OS user) — those
are left alone by the other agent, full stop. The same applies on the
server to `SmartTradeAI-deploy` and `SmartTradeAI-production` — these are
Codex's staged checkouts for the deploy scripts above, not stray clutter.

## Testing before pushing

Push only after the full suite passes locally/in a container — CI will
catch it either way, but a red CI run on a shared branch blocks the other
agent's next deploy too. Run:

```
docker compose exec app python -m pytest -q --no-cov
```

(or `docker run --rm <image> python -m pytest -q --no-cov` against a
freshly built image, for a closer approximation of what CI does).

The baseline as of 2026-09-18 is 744 passed, 0 failed — any red run is a
real regression, not pre-existing test debt. Keep it that way: fix a
failing test's root cause (or the test itself, if the test is what's
stale) before pushing, not after.

## Disk hygiene

Docker build cache grows unbounded across repeated builds. Check
periodically:

```
docker system df
```

If `Build Cache` reclaimable is large (multiple GB), it's always safe to
clear:

```
docker system prune -f
```

This never touches running containers, volumes, or tagged images still in
use — only stopped/dangling layers. `/usr/local/sbin/smarttrade-safe-cleanup`
(Codex's, root-owned) likely already automates some of this — check its
timer/service unit before scheduling your own.

## SSH keys in use

**IMPORTANT for whichever agent reads this next**: the key that used to be
called `smarttradeai-development-actions` was replaced on 2026-09-18. Its
original private half had never actually been saved anywhere retrievable
(neither agent had it, so `DEVELOPMENT_DEPLOY_KEY` could never actually be
set), so it was rotated out rather than left as a dead end. Do not
regenerate or rotate it again without checking here first and updating
this note — a second silent rotation just reintroduces the same problem
for whoever reads this next.

- **`smarttradeai-common-key`** — the ONE shared key for both interactive
  SSH access to the server and the CI deploy pipeline, by explicit user
  request (single key is easier for a non-technical user to manage than
  several). Public half is in the server's `~/.ssh/authorized_keys`
  (fingerprint `SHA256:lwAcGc1PJzC/u6T7ufyVn0ODTPvlG1MY4aFv1amVe8w`).
  Private half:
  - lives in the GitHub repo secret `DEVELOPMENT_DEPLOY_KEY` (used by
    `deploy-development.yml`), and
  - is saved locally at `C:\Users\vimal\Downloads\keys\smarttradeai_common_key`
    on the user's machine, for manual/interactive SSH use by either agent
    from that machine.
  This deliberately trades the stronger-isolation approach (separate keys
  per purpose, so a leaked CI secret can't be used interactively and vice
  versa) for simplicity, since the user manages this directly and found
  multiple keys confusing. If that tradeoff ever needs revisiting, raise
  it with the user rather than silently splitting the key back apart.
- `~/.ssh/smarttradeai_github` — GitHub deploy key (push access to this
  repo), registered as a GitHub deploy key. Unrelated to the key above —
  this one is for `git push`, not server SSH.
- The user's original Oracle-provisioned key (`ssh-key-2026-08-29`) is
  still in `authorized_keys` too — that one is the user's own, don't
  remove it.
