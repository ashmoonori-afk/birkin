"""Workflow CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api", tags=["workflows"])


@router.get("/workflows")
def list_workflows() -> dict:
    """List all workflows (saved + samples)."""
    from birkin.gateway.workflows import load_workflows

    return load_workflows()


@router.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: str) -> dict:
    """Get a single workflow by ID."""
    from birkin.gateway.workflows import load_workflows

    data = load_workflows()
    for w in data["saved"] + data["samples"]:
        if w.get("id") == workflow_id:
            return w
    raise HTTPException(status_code=404, detail="Workflow not found")


@router.put("/workflows")
def put_workflow(body: dict) -> dict:
    """Save or update a workflow."""
    import uuid

    from birkin.gateway.workflows import save_workflow

    if "id" not in body:
        body["id"] = uuid.uuid4().hex[:12]
    save_workflow(body)
    return {"status": "ok", "id": body["id"]}


@router.delete("/workflows/{workflow_id}", status_code=204)
def remove_workflow(workflow_id: str) -> None:
    """Delete a saved workflow."""
    from birkin.gateway.workflows import delete_workflow

    delete_workflow(workflow_id)
