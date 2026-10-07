# One container: the built web app is served by the FastAPI process.

FROM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
WORKDIR /app/api
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY api/pyproject.toml api/uv.lock api/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY api/ ./
RUN uv sync --frozen --no-dev
COPY --from=web /web/dist /app/web/dist

ENV HOST=0.0.0.0 PORT=8000 DATA_DIR=/data WEB_DIST=/app/web/dist
RUN useradd --create-home sideways && mkdir -p /data && chown sideways /data
USER sideways
VOLUME /data
EXPOSE 8000
CMD ["sh", "-c", "uv run --no-sync uvicorn sideways.main:app --host $HOST --port $PORT --proxy-headers --forwarded-allow-ips='*'"]
