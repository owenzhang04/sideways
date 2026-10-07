"""`uv run sideways` starts the API server."""

import uvicorn

from sideways.config import settings


def main() -> None:
    uvicorn.run("sideways.main:app", host=settings.host, port=settings.port, reload=settings.dev)
