# Multi-stage build (ROADMAP §12): build the UI, then a slim Python image that serves API + UI as a non-root user.
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    DATABASE_URL=sqlite:////data/app.db LOG_FORMAT=json COOKIE_SECURE=true
WORKDIR /srv
COPY requirements.txt ./
RUN pip install -r requirements.txt "psycopg[binary]>=3.1" && useradd --system --uid 10001 --home /srv app \
    && mkdir -p /data && chown app /data
COPY app/ app/
COPY eval/ eval/
COPY scripts/ scripts/
COPY --from=ui /ui/dist frontend/dist
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=4)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
