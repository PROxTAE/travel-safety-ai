# syntax=docker/dockerfile:1.7
#
# `docker build ./services/agent` (no --target, per .github/workflows/agent.yml) must land on the
# runtime stage below, so it stays the LAST stage in this file. The runtime image copies only
# `.venv` (built --no-dev), `app` and `migrations` from the builder — never `tests`, `uv.lock`, or
# a dev-enabled `.venv` — so the workflow's "no forbidden files in the image" check has something
# real to verify rather than something to work around.

FROM ghcr.io/astral-sh/uv:0.8.17 AS uv-bin

FROM python:3.12.14-slim-trixie AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY --from=uv-bin /uv /uvx /bin/
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
RUN uv sync --frozen --no-dev

FROM builder AS dev

RUN uv sync --frozen
COPY tests ./tests
COPY migrations ./migrations
ENV PATH=/app/.venv/bin:$PATH
CMD ["pytest", "-q", "-m", "not integration"]

FROM python:3.12.14-slim-trixie AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --home-dir /nonexistent --no-create-home app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app app ./app
COPY --chown=app:app migrations ./migrations

USER app
EXPOSE 8001

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health/live', timeout=2)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--no-server-header", "--no-access-log"]
