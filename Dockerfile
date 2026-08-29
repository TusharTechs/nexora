# NEXORA API — Cloud Run image
# Build context is the repo root so both `apps/api` (the service) and
# `packages/` (shared models) are available on PYTHONPATH.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# Dependencies first (better layer caching)
COPY apps/api/requirements.txt ./apps/api/requirements.txt
RUN pip install --no-cache-dir -r apps/api/requirements.txt

# Application code
COPY packages ./packages
COPY apps/api ./apps/api

WORKDIR /app/apps/api

# Cloud Run injects PORT (default 8080). EXECUTION_MODE / GEMINI_API_KEY /
# GCP_PROJECT_ID / NEXORA_REPO / NEXORA_DISPATCHER come from the service config.
EXPOSE 8080
CMD exec uvicorn nexora.main:app --host 0.0.0.0 --port ${PORT:-8080}
