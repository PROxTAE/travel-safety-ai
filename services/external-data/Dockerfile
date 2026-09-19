# syntax=docker/dockerfile:1.7
# Module 04 — external-data. Delivery rules § 8 "Dockerfile baseline".

# ---------------------------------------------------------------- builder
FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5.14 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Lockfile first so a source edit does not invalidate the dependency layer.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# ---------------------------------------------------------------- runtime
FROM python:3.12-slim-bookworm AS runtime

# UTC everywhere: every timestamp this service emits is UTC, and a host-local
# container clock is a silent way to corrupt that.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=UTC \
    PATH="/app/.venv/bin:$PATH" \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

# ca-certificates: every provider is HTTPS, so an image without a trust store
# fails every call. tzdata keeps zoneinfo lookups working for IANA names.
RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && ln -snf /usr/share/zoneinfo/UTC /etc/localtime \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home /app --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app app ./app
COPY --chown=app:app config ./config
COPY --chown=app:app alembic.ini ./alembic.ini

USER app

EXPOSE 8002

# Liveness only — readiness is checked by compose/CI against /health/ready.
HEALTHCHECK --interval=10s --timeout=5s --retries=10 --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8002/health/live', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
