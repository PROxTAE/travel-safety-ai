# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5.14 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY --from=contracts /smart_travel_contracts ./smart_travel_contracts
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-install-project --no-dev
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=UTC PATH="/app/.venv/bin:$PATH"
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home /app --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/smart_travel_contracts ./smart_travel_contracts
COPY --chown=app:app app ./app
COPY --chown=app:app alembic.ini ./alembic.ini
USER app
EXPOSE 8003
HEALTHCHECK --interval=10s --timeout=5s --retries=10 --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8003/health/live', timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]

FROM builder AS dev
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --group dev
COPY tests ./tests
COPY alembic.ini ./alembic.ini
COPY app/migrations ./app/migrations
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003", "--reload"]
