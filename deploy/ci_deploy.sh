#!/usr/bin/env bash
# CI/CD deploy script, run ON THE SERVER by GitHub Actions over SSH.
# Usage: ci_deploy.sh <environment>
#   environment: "development" or "production"
#
# Never run this by hand for a normal deploy — GitHub Actions calls it
# after tests have already passed in CI. It re-runs the test suite once
# more against the built image as a final gate before touching the live
# containers, and refuses to proceed if that gate fails.
set -euo pipefail

ENVIRONMENT="${1:?usage: ci_deploy.sh <development|production>}"

case "$ENVIRONMENT" in
  development)
    REPO_DIR="/home/ubuntu/SmartTradeAI-development"
    RUNTIME_DIR="/home/ubuntu/SmartTradeAI-development-runtime"
    IMAGE="smarttrade-development-app:latest"
    BRANCH="development"
    HEALTH_URL="https://smarttradeai.info/api/v1/system/ready"
    ;;
  production)
    REPO_DIR="/home/ubuntu/SmartTradeAI"
    RUNTIME_DIR="/home/ubuntu/SmartTradeAI"
    IMAGE="smarttradeai-app:latest"
    BRANCH="main"
    HEALTH_URL="https://smarttradeai.online/api/v1/system/ready"
    ;;
  *)
    echo "Unknown environment: $ENVIRONMENT (expected development or production)" >&2
    exit 1
    ;;
esac

DOCKER_COMPOSE="/usr/libexec/docker/cli-plugins/docker-compose"
[ -x "$DOCKER_COMPOSE" ] || DOCKER_COMPOSE="docker compose"

log() { echo "[ci_deploy:$ENVIRONMENT] $*"; }

log "Pulling latest $BRANCH into $REPO_DIR"
cd "$REPO_DIR"
git fetch origin "$BRANCH"
# A clean fast-forward only -- if the working tree has drifted (manual
# edits, a stray untracked file colliding with an incoming path), this
# fails loudly instead of silently discarding something. Investigate by
# hand rather than teaching the pipeline to force past it.
git merge --ff-only "origin/$BRANCH"

log "Building $IMAGE"
cd "$RUNTIME_DIR"
$DOCKER_COMPOSE build app

log "Running full test suite against the freshly built image (final gate before touching live containers)"
docker run --rm --network none "$IMAGE" python -m pytest -q --no-cov

log "Tests passed. Deploying app + worker."
$DOCKER_COMPOSE up -d --build app worker

log "Running pending database migrations"
$DOCKER_COMPOSE exec -T app flask db upgrade

log "Waiting for containers to report healthy"
for _ in $(seq 1 30); do
  STATUS=$($DOCKER_COMPOSE ps app --format '{{.Health}}' 2>/dev/null || echo "")
  [ "$STATUS" = "healthy" ] && break
  sleep 2
done
if [ "$STATUS" != "healthy" ]; then
  echo "app container did not report healthy in time" >&2
  exit 1
fi

log "Checking public health endpoint: $HEALTH_URL"
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' "$HEALTH_URL" || echo "000")
if [ "$HTTP_CODE" != "200" ]; then
  echo "Health check failed with HTTP $HTTP_CODE" >&2
  exit 1
fi

log "Deploy complete and healthy."
