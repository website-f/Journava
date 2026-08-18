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
echo "==> Waiting for health checks..."
RETRIES=0
MAX_RETRIES=30
until docker compose -f "$COMPOSE_FILE" ps | grep -q "api" && \
      curl -sf http://localhost:8400/health > /dev/null 2>&1; do
    RETRIES=$((RETRIES + 1))
    if [ $RETRIES -ge $MAX_RETRIES ]; then
        echo "ERROR: Services failed to become healthy within ${MAX_RETRIES}s"
        docker compose -f "$COMPOSE_FILE" logs --tail=30 api
        exit 1
    fi
    sleep 1
done

echo ""
echo "==> Journava is running!"
echo "    Web:  http://localhost:8401"
echo "    API:  http://localhost:8400"
echo "    Health: $(curl -s http://localhost:8400/health | head -c 200)"
echo ""

# --- Optional log tail --------------------------------------------------------
if [ "$TAIL_LOGS" = true ]; then
    echo "==> Tailing logs (Ctrl+C to stop)..."
    docker compose -f "$COMPOSE_FILE" logs -f
fi
