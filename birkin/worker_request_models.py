"""Typed worker request models and approval binding."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, Literal

from typing_extensions import assert_never

JsonValue = str | int | bool | None | Sequence["JsonValue"] | Mapping[str, "JsonValue"]
JsonObject = dict[str, JsonValue]
HarnessAction = Literal["show", "history", "rollback", "export", "refine"]
HarnessScope = Literal["local", "global"]
Resolution = Literal["quick", "standard", "deep"]


class WorkerRequestError(ValueError):
    """A structured worker request or approval binding is invalid."""


@dataclass(frozen=True, slots=True)
class MoiraiRun:
    script: str
    task: str
    worker: ClassVar[Literal["moirai"]] = "moirai"
    action: ClassVar[Literal["run"]] = "run"


@dataclass(frozen=True, slots=True)
class MoiraiList:
    limit: int
    worker: ClassVar[Literal["moirai"]] = "moirai"
    action: ClassVar[Literal["list"]] = "list"


@dataclass(frozen=True, slots=True)
class MoiraiStatus:
    run_id: str
    worker: ClassVar[Literal["moirai"]] = "moirai"
    action: ClassVar[Literal["status"]] = "status"


@dataclass(frozen=True, slots=True)
class MoiraiResume:
    run_id: str
    worker: ClassVar[Literal["moirai"]] = "moirai"
    action: ClassVar[Literal["resume"]] = "resume"


@dataclass(frozen=True, slots=True)
class MorpheusRun:
    dry_run: bool
    worker: ClassVar[Literal["morpheus"]] = "morpheus"
    action: ClassVar[Literal["run"]] = "run"


@dataclass(frozen=True, slots=True)
class HarnessRequest:
    action: HarnessAction
    target: str
    scope: HarnessScope
    worker: ClassVar[Literal["harness"]] = "harness"


@dataclass(frozen=True, slots=True)
class OdysseyRequest:
    goal: str
    worker: ClassVar[Literal["odyssey"]] = "odyssey"


@dataclass(frozen=True, slots=True)
class NeurosisRequest:
    idea: str
    resolution: Resolution
    worker: ClassVar[Literal["neurosis"]] = "neurosis"


@dataclass(frozen=True, slots=True)
class DaedalusCreate:
    slug: str
    root: str
    worker: ClassVar[Literal["daedalus"]] = "daedalus"
    action: ClassVar[Literal["create"]] = "create"


@dataclass(frozen=True, slots=True)
class DaedalusRefresh:
    slug: str
    root: str
    token: str
    worker: ClassVar[Literal["daedalus"]] = "daedalus"
    action: ClassVar[Literal["refresh"]] = "refresh"


@dataclass(frozen=True, slots=True)
class DaedalusShow:
    slug: str
    worker: ClassVar[Literal["daedalus"]] = "daedalus"
    action: ClassVar[Literal["show"]] = "show"


@dataclass(frozen=True, slots=True)
class DaedalusNote:
    slug: str
    text: str
    refs: tuple[str, ...]
    worker: ClassVar[Literal["daedalus"]] = "daedalus"
    action: ClassVar[Literal["note"]] = "note"


@dataclass(frozen=True, slots=True)
class DaedalusProfile:
    worker: ClassVar[Literal["daedalus"]] = "daedalus"
    action: ClassVar[Literal["profile"]] = "profile"


WorkerRequest = (
    MoiraiRun
    | MoiraiList
    | MoiraiStatus
    | MoiraiResume
    | MorpheusRun
    | HarnessRequest
    | OdysseyRequest
    | NeurosisRequest
    | DaedalusCreate
    | DaedalusRefresh
    | DaedalusShow
    | DaedalusNote
    | DaedalusProfile
)


def worker_name(request: WorkerRequest) -> str:
    match request:
        case MoiraiRun() | MoiraiList() | MoiraiStatus() | MoiraiResume():
            return "moirai"
        case MorpheusRun():
            return "morpheus"
        case HarnessRequest():
            return "harness"
        case OdysseyRequest():
            return "odyssey"
        case NeurosisRequest():
            return "neurosis"
        case (
            DaedalusCreate()
            | DaedalusRefresh()
            | DaedalusShow()
            | DaedalusNote()
            | DaedalusProfile()
        ):
            return "daedalus"
    assert_never(request)


def action_name(request: WorkerRequest) -> str | None:
    match request:
        case OdysseyRequest() | NeurosisRequest():
            return None
        case MoiraiRun():
            return "run"
        case MoiraiList():
            return "list"
        case MoiraiStatus():
            return "status"
        case MoiraiResume():
            return "resume"
        case MorpheusRun():
            return "run"
        case HarnessRequest(action=action):
            return action
        case DaedalusCreate():
            return "create"
        case DaedalusRefresh():
            return "refresh"
        case DaedalusShow():
            return "show"
        case DaedalusNote():
            return "note"
        case DaedalusProfile():
            return "profile"
    assert_never(request)


def request_data(request: WorkerRequest) -> JsonObject:
    """Serialize one request with exhaustive variant handling."""
    match request:
        case MoiraiRun(script=script, task=task):
            return {"worker": "moirai", "action": "run", "script": script, "task": task}
        case MoiraiList(limit=limit):
            return {"worker": "moirai", "action": "list", "limit": limit}
        case MoiraiStatus(run_id=run_id):
            return {"worker": "moirai", "action": "status", "run_id": run_id}
        case MoiraiResume(run_id=run_id):
            return {"worker": "moirai", "action": "resume", "run_id": run_id}
        case MorpheusRun(dry_run=dry_run):
            return {"worker": "morpheus", "action": "run", "dry_run": dry_run}
        case HarnessRequest(action=action, target=target, scope=scope):
            return {
                "worker": "harness",
                "action": action,
                "target": target,
                "scope": scope,
            }
        case OdysseyRequest(goal=goal):
            return {"worker": "odyssey", "goal": goal}
        case NeurosisRequest(idea=idea, resolution=resolution):
            return {"worker": "neurosis", "idea": idea, "resolution": resolution}
        case DaedalusCreate(slug=slug, root=root):
            return {
                "worker": "daedalus",
                "action": "create",
                "slug": slug,
                "root": root,
            }
        case DaedalusRefresh(slug=slug, root=root, token=token):
            return {
                "worker": "daedalus",
                "action": "refresh",
                "slug": slug,
                "root": root,
                "token": token,
            }
        case DaedalusShow(slug=slug):
            return {"worker": "daedalus", "action": "show", "slug": slug}
        case DaedalusNote(slug=slug, text=text, refs=refs):
            return {
                "worker": "daedalus",
                "action": "note",
                "slug": slug,
                "text": text,
                "refs": list(refs),
            }
        case DaedalusProfile():
            return {"worker": "daedalus", "action": "profile"}
    assert_never(request)


def canonical(request: WorkerRequest) -> bytes:
    return json.dumps(
        request_data(request), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def approval_payload(request: WorkerRequest) -> JsonObject:
    return {
        "version": 1,
        "request": request_data(request),
        "digest": hashlib.sha256(canonical(request)).hexdigest(),
    }
