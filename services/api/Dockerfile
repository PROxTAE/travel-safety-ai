# Public API service — multi-stage, non-root, reproducible.
#
# The build stage resolves dependencies from the committed uv.lock so two builds of the same commit
# produce the same image. The runtime stage copies only the virtual environment and the application
# source: no compiler, no build cache, no lockfile, no tests, no .git.

# --- build -----------------------------------------------------------------------------------

FROM python:3.12.8-slim-bookworm AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# uv is copied from its own published image rather than installed with pip, which pins it by digest
# and keeps the build free of a package index round trip.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /app

# Dependencies first, in their own layer: application code changes far more often than the lock
# file, and this way a code change does not re-resolve the dependency tree.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- runtime ---------------------------------------------------------------------------------

FROM python:3.12.8-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    SERVICE_NAME=api

# A fixed uid/gid so a bind-mounted volume has predictable ownership across machines.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=build --chown=app:app /app/.venv /app/.venv
COPY --from=build --chown=app:app /app/app /app/app
COPY --from=build --chown=app:app /app/migrations /app/migrations
COPY --from=build --chown=app:app /app/alembic.ini /app/alembic.ini

USER app

EXPOSE 8000

# Liveness only. Readiness depends on PostgreSQL, Redis and Keycloak, and a container that
# restarts whenever one of those blinks turns a recoverable outage into a crash loop; compose and
# CI probe /health/ready separately.
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).status == 200 else 1)"]

# Exec form, so uvicorn is PID 1 and receives SIGTERM directly. Without it a shell swallows the
# signal and the container is killed after the grace period instead of draining.
CMD ["uvicorn", "app.main:create_app", \
     "--factory", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--no-access-log", \
     "--proxy-headers", \
     "--timeout-graceful-shutdown", "20"]
