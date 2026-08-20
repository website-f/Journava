#!/usr/bin/env bash
# Journava deploy script — follows the shared-reverse-proxy recipe.
# Run from the project root on the VPS.
#
# Usage:
#   ./ops/deploy.sh            # standard deploy (pull + build + up)
#   ./ops/deploy.sh --no-cache # force rebuild without Docker layer cache
#   ./ops/deploy.sh --logs     # deploy then tail logs

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
ENV_FILE="$PROJECT_DIR/.env"

# --- Pre-flight checks -------------------------------------------------------
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: .env not found at $ENV_FILE"
    echo "Copy from template: cp ops/.env.example .env"
    exit 1
fi

cd "$PROJECT_DIR"

# Ports (match docker-compose.yml defaults; override in .env).
API_PORT="$(grep -E '^JOURNAVA_API_PORT=' "$ENV_FILE" | head -1 | cut -d= -f2 | tr -d ' ')"; API_PORT="${API_PORT:-8400}"
WEB_PORT="$(grep -E '^JOURNAVA_WEB_PORT=' "$ENV_FILE" | head -1 | cut -d= -f2 | tr -d ' ')"; WEB_PORT="${WEB_PORT:-8401}"
DOMAIN="$(grep -E '^JOURNAVA_DOMAIN=' "$ENV_FILE" | head -1 | cut -d= -f2 | tr -d ' ')"; DOMAIN="${DOMAIN:-journava.example.com}"

# --- Parse flags --------------------------------------------------------------
NO_CACHE=""
TAIL_LOGS=false
for arg in "$@"; do
    case $arg in
        --no-cache) NO_CACHE="--no-cache" ;;
        --logs)     TAIL_LOGS=true ;;
    esac
done

# --- Git pull -----------------------------------------------------------------
echo "==> Pulling latest from git..."
git pull --ff-only origin main || {
    echo "WARNING: git pull failed. Continuing with local changes."
}

# --- Build & deploy -----------------------------------------------------------
echo "==> Building images..."
docker compose -f "$COMPOSE_FILE" build $NO_CACHE

echo "==> Starting services..."
docker compose -f "$COMPOSE_FILE" up -d

# --- Health check wait --------------------------------------------------------
# /health always returns 200 (it reports degradation in the body rather than the
# status code), so reachability is the gate here and the body is printed below
# for the operator to read.
echo "==> Waiting for the API to serve /health..."
RETRIES=0
MAX_RETRIES=60
until curl -sf "http://127.0.0.1:${API_PORT}/health" > /dev/null 2>&1; do
    RETRIES=$((RETRIES + 1))
    if [ "$RETRIES" -ge "$MAX_RETRIES" ]; then
        echo "ERROR: API did not answer /health within ${MAX_RETRIES}s"
        docker compose -f "$COMPOSE_FILE" ps
        docker compose -f "$COMPOSE_FILE" logs --tail=40 api
        exit 1
    fi
    sleep 1
done

HEALTH="$(curl -s "http://127.0.0.1:${API_PORT}/health")"

echo ""
echo "==> Journava is running (single public entry point = web)"
echo "    App:  http://127.0.0.1:${WEB_PORT}   ← point ${DOMAIN} here in your reverse proxy"
echo "    API:  http://127.0.0.1:${API_PORT}/health  (direct, loopback only)"
echo "    Health: $HEALTH"
echo ""

# Surface degraded dependencies explicitly — the app boots without any of them,
# which is convenient but makes it easy to ship a half-wired stack unnoticed.
for dep in postgres redis gnosion camofox; do
    case "$HEALTH" in
        *"\"$dep\":false"*) echo "    ⚠  $dep is NOT available (running degraded)" ;;
    esac
done

case "$HEALTH" in
    *'"memory_backend":"in-process-fallback"'*)
        echo "    ⚠  memory is the in-process fallback, not Gnosion."
        echo "       Rebuild the api image with the 'brain' extra for real semantic memory."
        ;;
esac
echo ""

# --- Optional log tail --------------------------------------------------------
if [ "$TAIL_LOGS" = true ]; then
    echo "==> Tailing logs (Ctrl+C to stop)..."
    docker compose -f "$COMPOSE_FILE" logs -f
fi
