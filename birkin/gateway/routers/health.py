"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from birkin.gateway.schemas import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()
