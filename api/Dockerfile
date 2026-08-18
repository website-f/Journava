# Journava API — multi-stage Python + uv (FastAPI + LangGraph)
# Stage 1: install dependencies into a virtualenv via uv
# Stage 2: copy venv + app source, run uvicorn

# --------------------------------------------------------------------------- #
# Stage 1 — dependencies
# --------------------------------------------------------------------------- #
FROM python:3.12-slim AS deps

# Install uv (faster than pip, reads pyproject.toml natively)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy lock + project metadata first (Docker layer cache for deps)
COPY pyproject.toml uv.lock ./

# Install runtime dependencies into .venv.
# `--extra brain` pulls in Gnosion: without it the API still boots, but memory
# silently falls back to an in-process dict and the self-improvement story stops
# being true. Build with `--build-arg BRAIN_EXTRA=` to opt out deliberately.
ARG BRAIN_EXTRA="--extra brain"
RUN uv sync --frozen --no-dev --no-install-project ${BRAIN_EXTRA}

# --------------------------------------------------------------------------- #
# Stage 2 — runtime
# --------------------------------------------------------------------------- #
FROM python:3.12-slim AS runtime

# Keep the image lean
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the virtualenv from deps
COPY --from=deps /app/.venv /app/.venv

# Copy application source
COPY app/ ./app/

# Make the venv's python/pip the default on PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Journava API listens on 8400 (spec §11: port block 8400–8409)
EXPOSE 8400

# Health check — /health always returns 200 even when optional deps are down
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8400/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8400"]
