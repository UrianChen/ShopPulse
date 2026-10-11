FROM python:3.12.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache
COPY backend/app/ ./app/
COPY backend/migrations/ ./migrations/
COPY backend/assets/ ./assets/
COPY backend/alembic.ini ./
COPY samples/*.csv samples/*.xlsx /app/samples/

FROM python:3.12.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends chromium fonts-liberation \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 app && mkdir -p /data/shoppulse && chown app:app /data/shoppulse
WORKDIR /app/backend
COPY --from=builder --chown=app:app /app/backend /app/backend
COPY --from=builder --chown=app:app /app/samples /app/samples
COPY LICENSE /app/LICENSE
COPY licenses/ /app/licenses/
ENV PATH="/app/backend/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
ENV PDF_CHROMIUM_PATH=/usr/bin/chromium HOME=/tmp
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
