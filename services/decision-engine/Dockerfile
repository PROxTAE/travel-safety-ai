FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir --disable-pip-version-check \
    asyncpg==0.31.0 fastapi==0.141.1 pydantic==2.13.5 pydantic-settings==2.15.0 \
    prometheus-client==0.26.0 pyyaml==6.0.3 uvicorn[standard]==0.53.0
COPY app ./app
COPY policies ./policies
COPY migrations ./migrations
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8005
HEALTHCHECK --interval=10s --timeout=3s --retries=10 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8005/health/live', timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005"]