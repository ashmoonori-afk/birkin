"""Fail-closed parser for untrusted worker request objects."""

from __future__ import annotations

from .worker_request_boundary import object_fields, object_list
from .worker_request_models import (
    DaedalusCreate,
    DaedalusNote,
    DaedalusProfile,
    DaedalusRefresh,
    DaedalusShow,
    HarnessAction,
    HarnessRequest,
    HarnessScope,
    MoiraiList,
    MoiraiResume,
    MoiraiRun,
    MoiraiStatus,
    MorpheusRun,
    NeurosisRequest,
    OdysseyRequest,
    Resolution,
    WorkerRequest,
    WorkerRequestError,
)

_MAX_TEXT = 4000


def _exact(
    raw: dict[str, object], required: set[str], optional: set[str] | None = None
) -> None:
    missing = required - set(raw)
    extra = set(raw) - required - (optional or set())
    if missing:
        raise WorkerRequestError(f"missing field: {min(missing)}")
    if extra:
        raise WorkerRequestError(f"unexpected field: {min(extra)}")


def _text(value: object, field: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise WorkerRequestError(f"{field} must be text")
    cleaned = " ".join(value.split()).strip()
    if required and not cleaned:
        raise WorkerRequestError(f"{field} is empty")
    if len(cleaned) > _MAX_TEXT:
        raise WorkerRequestError(f"{field} exceeds {_MAX_TEXT} characters")
    return cleaned


def _harness_action(value: object) -> HarnessAction:
    match value:
        case "show":
            return "show"
        case "history":
            return "history"
        case "rollback":
            return "rollback"
        case "export":
            return "export"
        case "refine":
            return "refine"
        case _:
            raise WorkerRequestError("invalid harness action")


def _scope(value: object) -> HarnessScope:
    match value:
        case "local":
            return "local"
        case "global":
            return "global"
        case _:
            raise WorkerRequestError("scope must be local or global")


def _resolution(value: object) -> Resolution:
    match value:
        case "quick":
            return "quick"
        case "standard":
            return "standard"
        case "deep":
            return "deep"
        case _:
            raise WorkerRequestError("resolution must be quick, standard, or deep")


def _refs(value: object) -> tuple[str, ...]:
    return tuple(_text(item, "ref") for item in object_list(value, label="refs"))


def parse_request(value: object) -> WorkerRequest:
    """Parse one model-produced request into a frozen typed variant."""
    raw = object_fields(value)
    worker = raw.get("worker")
    action = raw.get("action")
    match worker:
        case "moirai":
            match action:
                case "run":
                    _exact(raw, {"worker", "action", "script", "task"})
                    return MoiraiRun(
                        _text(raw["script"], "script"),
                        _text(raw["task"], "task"),
                    )
                case "list":
                    _exact(raw, {"worker", "action"}, {"limit"})
                    limit = raw.get("limit", 10)
                    if (
                        isinstance(limit, bool)
                        or not isinstance(limit, int)
                        or not 1 <= limit <= 100
                    ):
                        raise WorkerRequestError(
                            "limit must be an integer from 1 to 100"
                        )
                    return MoiraiList(limit)
                case "status":
                    _exact(raw, {"worker", "action", "run_id"})
                    return MoiraiStatus(_text(raw["run_id"], "run_id"))
                case "resume":
                    _exact(raw, {"worker", "action", "run_id"})
                    return MoiraiResume(_text(raw["run_id"], "run_id"))
                case _:
                    raise WorkerRequestError(
                        "moirai action must be run, list, status, or resume"
                    )
        case "morpheus":
            _exact(raw, {"worker", "action"}, {"dry_run"})
            if action != "run":
                raise WorkerRequestError("morpheus action must be run")
            dry_run = raw.get("dry_run", False)
            if not isinstance(dry_run, bool):
                raise WorkerRequestError("dry_run must be boolean")
            return MorpheusRun(dry_run)
        case "harness":
            _exact(raw, {"worker", "action"}, {"target", "scope"})
            parsed_action = _harness_action(action)
            target = _text(raw.get("target", ""), "target", required=False)
            if parsed_action in {"rollback", "export"} and not target:
                raise WorkerRequestError(f"harness {parsed_action} requires target")
            if parsed_action in {"show", "history"} and target:
                raise WorkerRequestError(
                    f"harness {parsed_action} does not accept target"
                )
            return HarnessRequest(
                parsed_action, target, _scope(raw.get("scope", "global"))
            )
        case "odyssey":
            _exact(raw, {"worker", "goal"})
            return OdysseyRequest(_text(raw["goal"], "goal"))
        case "neurosis":
            _exact(raw, {"worker", "idea"}, {"resolution"})
            return NeurosisRequest(
                _text(raw["idea"], "idea"),
                _resolution(raw.get("resolution", "standard")),
            )
        case "daedalus":
            return _parse_daedalus(raw, action)
        case _:
            raise WorkerRequestError(f"unknown worker {worker!r}")


def _parse_daedalus(raw: dict[str, object], action: object) -> WorkerRequest:
    common = {"worker", "action"}
    match action:
        case "profile":
            _exact(raw, common)
            return DaedalusProfile()
        case "create":
            _exact(raw, common | {"slug"}, {"root"})
            return DaedalusCreate(
                _text(raw["slug"], "slug"),
                _text(raw.get("root", ""), "root", required=False),
            )
        case "refresh":
            _exact(raw, common | {"slug", "token"}, {"root"})
            return DaedalusRefresh(
                _text(raw["slug"], "slug"),
                _text(raw.get("root", ""), "root", required=False),
                _text(raw["token"], "token"),
            )
        case "show":
            _exact(raw, common | {"slug"})
            return DaedalusShow(_text(raw["slug"], "slug"))
        case "note":
            _exact(raw, common | {"slug", "text"}, {"refs"})
            return DaedalusNote(
                _text(raw["slug"], "slug"),
                _text(raw["text"], "text"),
                _refs(raw.get("refs", [])),
            )
        case _:
            raise WorkerRequestError("invalid daedalus action")
