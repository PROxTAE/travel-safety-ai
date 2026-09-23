FROM ghcr.io/astral-sh/uv:0.8.17 AS uv-bin

FROM python:3.12.14-slim-trixie AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=uv-bin /uv /uvx /bin/
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
COPY emergency-directory ./emergency-directory
COPY tests ./tests
RUN UV_COMPILE_BYTECODE=0 uv sync --frozen

FROM builder AS dev

ENV PATH=/app/.venv/bin:$PATH \
    REPOSITORY_ROOT=/workspace

RUN UV_COMPILE_BYTECODE=0 uv sync --frozen
COPY tests ./tests
COPY migrations ./migrations

CMD ["pytest", "-q"]

FROM dev AS test
COPY --from=contracts . /workspace/packages/contracts

FROM python:3.12.14-slim-trixie AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app \
    UV_CACHE_DIR=/tmp/uv-cache \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_NO_SYNC=1 \
    UV_FROZEN=1 \
    RUFF_CACHE_DIR=/tmp/ruff-cache

COPY --from=uv-bin /uv /uvx /bin/

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --home-dir /nonexistent --no-create-home app

WORKDIR /app
COPY --from=builder --chown=app:app /app /app

USER app
EXPOSE 8006

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8006/health/live', timeout=2)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8006", "--no-server-header", "--no-access-log"]
