"""Triggers router — CRUD and manual fire for workflow triggers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from birkin.core.errors import BirkinError
from birkin.triggers import (
    CronTrigger,
    FileWatchTrigger,
    MessageTrigger,
    TriggerConfig,
    TriggerScheduler,
    WebhookTrigger,
)
from birkin.triggers.storage import TriggerStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/triggers", tags=["triggers"])

_scheduler: TriggerScheduler | None = None


def _get_scheduler() -> TriggerScheduler:
    global _scheduler  # noqa: PLW0603
    if _scheduler is None:
        _scheduler = TriggerScheduler()
        _scheduler.register_type("cron", CronTrigger)
        _scheduler.register_type("file_watch", FileWatchTrigger)
        _scheduler.register_type("webhook", WebhookTrigger)
        _scheduler.register_type("message", MessageTrigger)

        async def _default_on_fire(config: TriggerConfig) -> None:
            """Execute the linked workflow when a trigger fires."""
            import logging

            _logger = logging.getLogger(__name__)
            workflow_id = config.workflow_id
            if not workflow_id:
                _logger.warning("Trigger %s fired but has no workflow_id", config.id)
                return

            try:
                from birkin.core.providers import create_provider
                from birkin.core.workflow_engine import WorkflowEngine
                from birkin.gateway.config import load_config
                from birkin.gateway.deps import get_wiki_memory

                cfg = load_config()
                provider_name = config.config.get("provider", cfg.get("provider", "anthropic"))
                provider = create_provider(f"{provider_name}/default")

                from birkin.gateway.workflows import load_workflows

                wf_data = load_workflows()
                workflow = next(
                    (w for w in wf_data["saved"] + wf_data["samples"] if w.get("id") == workflow_id),
                    None,
                )
                if workflow is None:
                    _logger.error("Trigger %s: workflow %s not found", config.id, workflow_id)
                    return

                engine = WorkflowEngine(provider=provider, wiki_memory=get_wiki_memory())
                engine.load(workflow)
                result = await engine.run(f"Triggered by {config.type}")
                _logger.info(
                    "Trigger %s → workflow %s completed: %s", config.id, workflow_id, result[:100] if result else "ok"
                )
            except (OSError, RuntimeError, ValueError, TypeError, BirkinError) as exc:
                _logger.error("Trigger %s → workflow %s failed: %s", config.id, workflow_id, exc)

        _scheduler.set_default_callback(_default_on_fire)
    return _scheduler


class CreateTriggerRequest(BaseModel):
    type: str
    workflow_id: str
    active: bool = True
    config: dict[str, Any] = {}


class UpdateTriggerRequest(BaseModel):
    active: bool | None = None
    config: dict[str, Any] | None = None


@router.get("")
async def list_triggers() -> list[dict[str, Any]]:
    """List all registered triggers."""
    scheduler = _get_scheduler()
    return [
        {
            "id": t.id,
            "type": t.trigger_type,
            "workflow_id": t.workflow_id,
            "active": t.active,
            "running": t.is_running(),
            "config": t.config.config,
        }
        for t in scheduler.list_all()
    ]


@router.post("")
async def create_trigger(body: CreateTriggerRequest) -> dict[str, Any]:
    """Create and start a new trigger."""
    scheduler = _get_scheduler()
    config = TriggerConfig(
        type=body.type,
        workflow_id=body.workflow_id,
        active=body.active,
        config=body.config,
    )
    try:
        trigger = await scheduler.add(config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Persist to SQLite so trigger survives restart
    try:
        with TriggerStore() as store:
            store.save(config)
    except (OSError, RuntimeError) as exc:
        logger.warning("Failed to persist trigger: %s", exc)

    return {
        "id": trigger.id,
        "type": trigger.trigger_type,
        "workflow_id": trigger.workflow_id,
        "active": trigger.active,
        "running": trigger.is_running(),
    }


@router.get("/{trigger_id}")
async def get_trigger(trigger_id: str) -> dict[str, Any]:
    """Get a specific trigger."""
    scheduler = _get_scheduler()
    trigger = scheduler.get(trigger_id)
    if trigger is None:
        raise HTTPException(status_code=404, detail=f"Trigger not found: {trigger_id}")
    return {
        "id": trigger.id,
        "type": trigger.trigger_type,
        "workflow_id": trigger.workflow_id,
        "active": trigger.active,
        "running": trigger.is_running(),
        "config": trigger.config.config,
    }


@router.delete("/{trigger_id}")
async def delete_trigger(trigger_id: str) -> dict[str, str]:
    """Stop and remove a trigger."""
    scheduler = _get_scheduler()
    removed = await scheduler.remove(trigger_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Trigger not found: {trigger_id}")

    # Remove from SQLite so it doesn't reappear on restart
    try:
        with TriggerStore() as store:
            store.remove(trigger_id)
    except (OSError, RuntimeError) as exc:
        logger.warning("Failed to remove trigger from DB: %s", exc)

    return {"status": "deleted", "id": trigger_id}


@router.post("/{trigger_id}/fire")
async def fire_trigger(trigger_id: str) -> dict[str, Any]:
    """Manually fire a trigger."""
    scheduler = _get_scheduler()
    trigger = scheduler.get(trigger_id)
    if trigger is None:
        raise HTTPException(status_code=404, detail=f"Trigger not found: {trigger_id}")

    fired = await trigger.fire()

    return {"id": trigger_id, "fired": fired}
