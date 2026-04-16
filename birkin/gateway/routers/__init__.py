"""Gateway routers package — collects all sub-routers into a single list."""

from __future__ import annotations

from birkin.gateway.routers.auth import router as auth_router
from birkin.gateway.routers.chat import router as chat_router
from birkin.gateway.routers.health import router as health_router
from birkin.gateway.routers.sessions import router as sessions_router
from birkin.gateway.routers.settings import router as settings_router
from birkin.gateway.routers.skills import router as skills_router
from birkin.gateway.routers.telegram import router as telegram_router
from birkin.gateway.routers.traces import router as traces_router
from birkin.gateway.routers.triggers import router as triggers_router
from birkin.gateway.routers.webhooks import router as webhooks_router
from birkin.gateway.routers.wiki import router as wiki_router
from birkin.gateway.routers.workflows import router as workflows_router

all_routers = [
    auth_router,
    health_router,
    chat_router,
    settings_router,
    sessions_router,
    wiki_router,
    workflows_router,
    telegram_router,
    webhooks_router,
    skills_router,
    traces_router,
    triggers_router,
]
