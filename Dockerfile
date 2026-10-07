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
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy HF_HOME=/app/hf
COPY api/pyproject.toml api/uv.lock api/.python-version ./
# The steer extra pulls CPU-only torch on Linux (see [tool.uv.sources] in pyproject.toml).
RUN uv sync --frozen --no-dev --extra steer --no-install-project
COPY api/ ./
RUN uv sync --frozen --no-dev --extra steer

# Bake the steering model into the image so a cold start doesn't download ~750 MB.
ARG STEER_MODEL=knowledgator/gliclass-base-v3.0
RUN uv run --no-sync python -c "from huggingface_hub import snapshot_download; snapshot_download('${STEER_MODEL}')"

COPY --from=web /web/dist /app/web/dist

ENV HOST=0.0.0.0 PORT=8000 DATA_DIR=/data WEB_DIST=/app/web/dist \
    STEER_MODEL=${STEER_MODEL} HF_HUB_OFFLINE=1
RUN useradd --create-home sideways && mkdir -p /data && chown -R sideways /data /app/hf
USER sideways
VOLUME /data
EXPOSE 8000
CMD ["sh", "-c", "uv run --no-sync uvicorn sideways.main:app --host $HOST --port $PORT --proxy-headers --forwarded-allow-ips='*'"]
