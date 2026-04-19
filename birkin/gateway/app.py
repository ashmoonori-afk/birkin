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
    reset_insights_engine,
    reset_mcp_registry,
    reset_session_store,
    reset_skill_registry,
    reset_telegram_adapter,
    reset_wiki_memory,
    reset_workflow_recommender,
)
from birkin.gateway.routers import all_routers

_background_tasks: set[asyncio.Task] = set()  # prevent GC of background tasks
_WEB_DIR = Path(__file__).resolve().parent.parent / "web" / "static"

logger = logging.getLogger(__name__)


def _seconds_until_3am() -> float:
    """Calculate seconds until next 3:00 AM."""
    import datetime as dt

    now = dt.datetime.now()
    target = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if now >= target:
        target += dt.timedelta(days=1)
    return (target - now).total_seconds()


async def _daily_memory_loop() -> None:
    """Run daily memory compilation + session cleanup at 3 AM."""
    from birkin.gateway.deps import get_wiki_memory
    from birkin.memory.compiler import MemoryCompiler
    from birkin.memory.event_store import EventStore

    while True:
        await asyncio.sleep(_seconds_until_3am())
        try:
            import datetime as dt

            wiki = get_wiki_memory()
            today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")

            # Compile daily digest
            store = EventStore()
            compiler = MemoryCompiler(store, wiki)
            result = compiler.compile_daily(today)
            logger.info("Daily compile: %d events processed", result.events_processed)

            # Cleanup old sessions (>30 days)
            deleted = wiki.summarize_old_sessions(max_age_hours=720)
            if deleted:
                logger.info("Session cleanup: %d old sessions archived", len(deleted))

            # Weekly insights digest on Sundays
            if dt.datetime.now().weekday() == 6:
                try:
                    from birkin.gateway.deps import get_insights_engine

                    end = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
                    start = (dt.datetime.now(dt.UTC) - dt.timedelta(days=6)).strftime("%Y-%m-%d")
                    insights = get_insights_engine()
                    digest = insights.weekly_digest(start, end)
                    wiki.ingest("insights", f"weekly-{end}", digest.summary)
                    logger.info("Weekly insights digest saved: insights/weekly-%s", end)
                except (OSError, RuntimeError, ValueError) as exc:
                    logger.error("Weekly insights digest failed: %s", exc)

            store.close()

            # Workflow suggestion check
            try:
                from birkin.gateway.deps import get_workflow_recommender

                recommender = get_workflow_recommender()
                suggestions = await recommender.check_and_notify()
                if suggestions:
                    logger.info("Daily cron: %d workflow suggestions generated", len(suggestions))
            except (OSError, RuntimeError, ValueError, ImportError) as exc:
                logger.debug("Workflow recommender check failed: %s", exc)

        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("Daily memory loop failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown for the FastAPI application."""
    # ── Startup ──
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        from birkin.gateway.routers.telegram import _health_check_loop

        task = asyncio.create_task(_health_check_loop())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    # Daily memory compilation + session cleanup (runs at 3 AM)
    task = asyncio.create_task(_daily_memory_loop())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    # Hydrate trigger scheduler with persisted triggers
    try:
        from birkin.gateway.routers.triggers import _get_scheduler
        from birkin.triggers.storage import TriggerStore

        trigger_store = TriggerStore()
        active_triggers = trigger_store.load_all_active()
        if active_triggers:
            scheduler = _get_scheduler()
            for cfg in active_triggers:
                await scheduler.add(cfg)
            logger.info("Loaded %d active triggers from storage", len(active_triggers))
        trigger_store.close()
    except (OSError, RuntimeError, ValueError, ImportError) as exc:
        logger.warning("Failed to load persisted triggers: %s", exc)

    yield

    # ── Shutdown ──
    from birkin.core.agent import shutdown_executor

    shutdown_executor(wait=True)

    logger.info("Shutting down: closing all SQLite connections")
    try:
        get_session_store().close_all()
    except (OSError, RuntimeError) as exc:
        logger.warning("Error closing session store connections: %s", exc, exc_info=True)

    reset_session_store()
    reset_wiki_memory()
    reset_telegram_adapter()
    reset_dispatcher()
    reset_skill_registry()
    reset_mcp_registry()
    reset_insights_engine()
    reset_workflow_recommender()


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
