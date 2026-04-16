"""Triggers router — CRUD and manual fire for workflow triggers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from birkin.triggers import (
    CronTrigger,
    FileWatchTrigger,
    MessageTrigger,
    TriggerConfig,
    TriggerScheduler,
    WebhookTrigger,
)

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
            pass  # Placeholder — will be wired to workflow execution

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
