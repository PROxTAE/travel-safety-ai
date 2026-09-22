FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir --disable-pip-version-check \
    asyncpg==0.31.0 fastapi==0.141.1 jinja2==3.1.6 jsonschema[format]==4.25.1 openai==1.109.1 pydantic==2.13.5 pydantic-settings==2.15.0 \
    prometheus-client==0.26.0 pyyaml==6.0.3 redis==5.2.1 uvicorn[standard]==0.53.0
COPY app ./app
COPY policies ./policies
COPY prompts ./prompts
COPY migrations ./migrations
COPY schemas ./schemas
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8005
HEALTHCHECK --interval=10s --timeout=3s --retries=10 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8005/health/live', timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005"]

FROM runtime AS test
USER root
RUN pip install --no-cache-dir --disable-pip-version-check \
    asyncpg-stubs==0.30.0 hypothesis==6.131.9 jsonschema[format]==4.25.1 \
    mypy==1.18.1 pytest==9.1.1 ruff==0.13.0 \
    types-jsonschema==4.25.1.20250822 types-PyYAML==6.0.12.20250915
COPY tests ./tests
USER appuser
CMD ["pytest", "-q"]