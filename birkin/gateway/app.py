"""FastAPI application factory for the Birkin gateway."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from birkin.gateway.routes import router

_WEB_DIR = Path(__file__).resolve().parent.parent / "web" / "static"


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    app = FastAPI(
        title="Birkin Agent",
        version="0.1.0",
        description="API backend for the Birkin AI agent.",
    )

    app.include_router(router)

    # Serve the web UI static files at root when they exist.
    if _WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")

    return app
