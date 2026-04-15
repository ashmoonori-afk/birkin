"""FastAPI application factory for the Birkin gateway."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from birkin.gateway.routes import router

_WEB_DIR = Path(__file__).resolve().parent.parent / "web" / "static"


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    app = FastAPI(
        title="Birkin Agent",
        version="0.1.0",
        description="API backend for the Birkin AI agent.",
    )

    # API routes first — must take priority over static files
    app.include_router(router)

    if _WEB_DIR.is_dir():
        # Serve static assets (JS, CSS, etc.) under /static
        app.mount(
            "/static",
            StaticFiles(directory=str(_WEB_DIR)),
            name="static-assets",
        )

        # Serve index.html for the root and any non-API path (SPA fallback)
        index_path = _WEB_DIR / "index.html"

        @app.get("/")
        async def serve_index():
            return FileResponse(str(index_path))

    return app
