# syntax=docker/dockerfile:1
# Build context: the repository root (so the workspace lockfile and libs/ are available).

# ---- stage 1: build the virtual environment with uv ----
FROM ghcr.io/astral-sh/uv:0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c AS uv
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# 1) dependencies only (cached until uv.lock changes)
COPY pyproject.toml uv.lock ./
COPY libs/rag-common/pyproject.toml libs/rag-common/
COPY services/rag-api/pyproject.toml services/rag-api/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package rag-api --no-install-workspace
# 2) then our own code
COPY libs/rag-common libs/rag-common
COPY services/rag-api services/rag-api
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package rag-api --no-editable

# ---- stage 2: the small runtime image (no uv, no compilers, no source tree) ----
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
RUN useradd --system --uid 10001 --no-create-home app
COPY --from=build /app/.venv /app/.venv
# The reviewed, locked registry (Step 24). Owned by root, so the app user (10001) can read but not change it.
COPY prompts /app/prompts
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
CMD ["uvicorn", "rag_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
