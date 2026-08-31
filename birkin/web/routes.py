"""Typed route matching for the standard-library web server.

Matching is deliberately separate from handling so the security gates remain in
``Handler`` while route precedence and path quirks are explicit and testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Generic, TypeVar
from urllib.parse import urlsplit


class GetRoute(Enum):
    BROWSER = auto()
    FAVICON = auto()
    LEGACY_UI = auto()
    WORKSPACE = auto()
    BOOTSTRAP = auto()
    ROOT = auto()
    STATUS = auto()
    APPROVAL_DIFF = auto()
    CONFIG = auto()
    AGENT_RUNS = auto()
    AGENT_RUN = auto()
    ACTION_RECEIPT = auto()
    CHECKPOINTS = auto()
    EVENTS = auto()
    CONTRACT = auto()
    JOBS = auto()
    RUNS = auto()
    APPROVALS = auto()
    SKILLS = auto()
    AGENT_CARD = auto()
    NOT_FOUND = auto()


class PostRoute(Enum):
    BROWSER = auto()
    WORKSPACE = auto()
    A2A = auto()
    CONTEXT = auto()
    RUN_CONTROL = auto()
    CHECKPOINT = auto()
    INVALID_CHECKPOINT = auto()
    APPROVALS = auto()
    NOT_FOUND = auto()


_RouteT = TypeVar("_RouteT", GetRoute, PostRoute)


@dataclass(frozen=True)
class RouteMatch(Generic[_RouteT]):
    route: _RouteT
    identifier: str = ""
    action: str = ""


_LEGACY_UI_PATHS = {"/legacy-dashboard", "/dashboard", "/workbench"}


def match_get(raw_path: str) -> RouteMatch[GetRoute]:
    path = urlsplit(raw_path).path
    if path.startswith("/api/browser-aside/"):
        return RouteMatch(GetRoute.BROWSER)
    if path == "/favicon.ico":
        return RouteMatch(GetRoute.FAVICON)
    if path in _LEGACY_UI_PATHS:
        return RouteMatch(GetRoute.LEGACY_UI)
    if path.startswith("/api/workspace/"):
        return RouteMatch(GetRoute.WORKSPACE)
    if raw_path.startswith("/_bootstrap/"):
        return RouteMatch(GetRoute.BOOTSTRAP)
    if raw_path in ("/", "/index.html"):
        return RouteMatch(GetRoute.ROOT)
    if raw_path == "/api/status":
        return RouteMatch(GetRoute.STATUS)
    if raw_path.startswith("/api/approvals/") and raw_path.endswith("/diff"):
        return RouteMatch(GetRoute.APPROVAL_DIFF, raw_path.split("/")[3])
    if raw_path == "/api/config":
        return RouteMatch(GetRoute.CONFIG)
    if raw_path == "/api/agent-runs":
        return RouteMatch(GetRoute.AGENT_RUNS)
    run_match = re.fullmatch(r"/api/agent-runs/([0-9a-f]{12})", raw_path)
    if run_match:
        return RouteMatch(GetRoute.AGENT_RUN, run_match.group(1))
    receipt_match = re.fullmatch(r"/api/actions/([0-9a-f]{12})/receipt", raw_path)
    if receipt_match:
        return RouteMatch(GetRoute.ACTION_RECEIPT, receipt_match.group(1))
    if raw_path.startswith("/api/checkpoints"):
        return RouteMatch(GetRoute.CHECKPOINTS)
    exact_routes = {
        "/api/events": GetRoute.EVENTS,
        "/api/contract": GetRoute.CONTRACT,
        "/api/jobs": GetRoute.JOBS,
        "/api/runs": GetRoute.RUNS,
        "/api/approvals": GetRoute.APPROVALS,
        "/api/skills": GetRoute.SKILLS,
        "/.well-known/agent-card.json": GetRoute.AGENT_CARD,
    }
    return RouteMatch(exact_routes.get(raw_path, GetRoute.NOT_FOUND))


def match_post(raw_path: str) -> RouteMatch[PostRoute]:
    path = urlsplit(raw_path).path
    if path.startswith("/api/browser-aside/"):
        return RouteMatch(PostRoute.BROWSER)
    if path.startswith("/api/workspace/"):
        return RouteMatch(PostRoute.WORKSPACE)
    if raw_path == "/a2a":
        return RouteMatch(PostRoute.A2A)
    if raw_path == "/api/context":
        return RouteMatch(PostRoute.CONTEXT)
    control_match = re.fullmatch(r"/api/agent-runs/([0-9a-f]{12})/control", raw_path)
    if control_match:
        return RouteMatch(PostRoute.RUN_CONTROL, control_match.group(1))
    checkpoint_match = re.fullmatch(
        r"/api/checkpoints/([0-9a-fA-F]{4,40})/(restore|fork)", raw_path
    )
    if checkpoint_match:
        return RouteMatch(
            PostRoute.CHECKPOINT,
            checkpoint_match.group(1),
            checkpoint_match.group(2),
        )
    if raw_path.startswith("/api/checkpoints/") and raw_path.rsplit("/", 1)[-1] in {
        "restore",
        "fork",
    }:
        return RouteMatch(PostRoute.INVALID_CHECKPOINT)
    if raw_path == "/api/approvals":
        return RouteMatch(PostRoute.APPROVALS)
    return RouteMatch(PostRoute.NOT_FOUND)
