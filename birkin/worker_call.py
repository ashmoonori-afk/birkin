"""Natural-language worker request contract."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import ClassVar

from . import worker_executor, worker_hooks, worker_request, worker_schema

WORKER_COMMANDS: dict[str, str] = {
    "moirai": "deterministic multi-agent workflows",
    "morpheus": "run the self-improvement routine",
    "harness": "inspect or manage the self-improvement ledger",
    "odyssey": "seed a goal-completion cycle",
    "neurosis": "seed a Socratic deep interview",
    "daedalus": "manage evidence-linked project document maps",
}

WorkerCallError = worker_request.WorkerRequestError


@dataclass(frozen=True, slots=True)
class WorkerCall:
    request: worker_request.WorkerRequest
    category: ClassVar[str] = "worker"

    @property
    def worker(self) -> str:
        return worker_request.worker_name(self.request)

    def title(self) -> str:
        action = worker_request.action_name(self.request)
        return f"run worker {self.worker}{f' {action}' if action else ''}"

    def description(self) -> str:
        return json.dumps(
            worker_request.request_data(self.request),
            ensure_ascii=False,
            sort_keys=True,
        )

    def argv(self) -> tuple[str, ...]:
        return worker_executor.argv(self.request)

    def payload(self) -> worker_request.JsonObject:
        return worker_request.approval_payload(self.request)


def invokable_workers() -> tuple[str, ...]:
    return tuple(name for name in worker_hooks.WORKERS if name in WORKER_COMMANDS)


def describe_workers() -> str:
    return "; ".join(
        f"{name} = {WORKER_COMMANDS[name]}" for name in invokable_workers()
    )


def resolve(request: object) -> WorkerCall:
    parsed = worker_request.parse(request)
    if worker_request.worker_name(parsed) not in invokable_workers():
        raise WorkerCallError(
            f"worker is not invokable: {worker_request.worker_name(parsed)}"
        )
    return WorkerCall(parsed)


def input_schema() -> worker_request.JsonObject:
    return worker_schema.input_schema()
