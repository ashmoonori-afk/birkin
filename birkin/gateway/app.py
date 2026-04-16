"""FastAPI application factory for the Birkin gateway."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse, JSONResponse

from birkin import __version__
from birkin.gateway.auth import require_auth
from birkin.gateway.deps import (
    get_session_store,
    reset_dispatcher,
    reset_session_store,
    reset_telegram_adapter,
    reset_wiki_memory,
)
from birkin.gateway.routers import all_routers

_WEB_DIR = Path(__file__).resolve().parent.parent / "web" / "static"

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown for the FastAPI application."""
    # ── Startup ──
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        from birkin.gateway.routers.telegram import _health_check_loop

        asyncio.create_task(_health_check_loop())

    yield

    # ── Shutdown ──
    from birkin.core.agent import shutdown_executor

    shutdown_executor(wait=True)

    logger.info("Shutting down: closing all SQLite connections")
    try:
        get_session_store().close_all()
    except Exception:  # noqa: BLE001
        logger.warning("Error closing session store connections", exc_info=True)

    reset_session_store()
    reset_wiki_memory()
    reset_telegram_adapter()
    reset_dispatcher()


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    app = FastAPI(
        title="Birkin Agent",
        version=__version__,
        description="API backend for the Birkin AI agent.",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        from fastapi.exceptions import HTTPException as FastAPIHTTPException

        try:
            require_auth(request)
        except FastAPIHTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
            )
        return await call_next(request)

    # API routes first — must take priority over static files
    for _router in all_routers:
        app.include_router(_router)

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
