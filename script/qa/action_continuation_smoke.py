"""No-model smoke driver for durable Moirai action continuations."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def _create(home: Path, actor: str, json_out: Path | None) -> int:
    os.environ["BIRKIN_HOME"] = str(home)
    import birkin.moirai as moirai
    import birkin.store as store
    import birkin.moirai.journal as journal

    home.mkdir(parents=True, exist_ok=True)
    script_path = home / "action-continuation-smoke.py"
    script_path.write_text(
        f'''
meta = {{"name": "action-continuation-smoke", "roles": {{}}}}

def main(m):
    supplied = m.request_answers(
        step_id="deploy-target",
        title="Deploy release",
        description="Choose whether to continue.",
        questions=[{{
            "id": "choice",
            "text": "Continue?",
            "options": [{{"value": "yes", "label": "Yes"}}],
        }}],
        expected_actor={actor!r},
        expected_capability="dashboard.approvals.answer.v1",
    )
    return {{"input": supplied}}
''',
        encoding="utf-8",
    )
    outcome = moirai.run_script(moirai.load_script(script_path), cfg={})
    pending = store.list_pending()
    if outcome["status"] != "waiting_input" or len(pending) != 1:
        raise RuntimeError("workflow did not create exactly one input wait")
    action_id = str(pending[0]["id"])
    wait = journal.get_input_wait(action_id)
    if wait is None:
        raise RuntimeError("input wait was not durable")
    result = {
        "action_id": action_id,
        "run_id": wait["run_id"],
        "worker_id": wait["worker_id"],
        "step_id": wait["step_id"],
        "question_digest": wait["question_digest"],
        "expected_actor": wait["expected_actor"],
        "expected_capability": wait["expected_capability"],
        "expires_at": wait["expires_at"],
        "resume_token": wait["resume_token"],
        "input_schema_version": wait["input_schema_version"],
        "previous_state_digest": wait["previous_state_digest"],
        "source_status": outcome["status"],
    }
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True)
    print(encoded)
    if json_out is not None:
        json_out.write_text(encoded + "\n", encoding="utf-8")
    return 0


def _state(home: Path, action_id: str) -> int:
    os.environ["BIRKIN_HOME"] = str(home)
    from birkin.moirai import journal

    wait = journal.get_input_wait(action_id)
    if wait is None:
        raise RuntimeError("input wait not found")
    event = journal.get_accepted_answer(action_id)
    source = journal.get_run(str(wait["run_id"]))
    child = (
        journal.get_run(str(wait["resume_run_id"]))
        if wait.get("resume_run_id")
        else None
    )
    result: dict[str, Any] = {
        "wait": wait,
        "accepted_event": event,
        "source_run": source,
        "resume_run": child,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _accept_without_resume(
    home: Path,
    action_id: str,
    binding_file: Path,
) -> int:
    os.environ["BIRKIN_HOME"] = str(home)
    import birkin.moirai.journal as journal

    binding = json.loads(binding_file.read_text(encoding="utf-8"))
    wait = journal.get_input_wait(action_id)
    if wait is None:
        raise RuntimeError("input wait not found")
    event = journal.accept_input(
        action_id,
        actual_actor=str(binding["expected_actor"]),
        actual_capability=str(binding["expected_capability"]),
        resume_token=str(binding["resume_token"]),
        input_value={
            "version": 1,
            "answers": {"choice": "yes"},
            "clarification": "",
            "navigation": [],
        },
    )
    print(json.dumps(event, ensure_ascii=False, sort_keys=True))
    return 0


def _recover(home: Path) -> int:
    os.environ["BIRKIN_HOME"] = str(home)
    from birkin.moirai import continuation

    resumed = continuation.recover()
    print(json.dumps({"resumed": resumed}, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Exercise durable Moirai structured-action continuations.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="create one waiting input action")
    create.add_argument("--home", type=Path, required=True)
    create.add_argument("--actor", required=True)
    create.add_argument("--json-out", type=Path)
    state = sub.add_parser("state", help="dump durable continuation state")
    state.add_argument("--home", type=Path, required=True)
    state.add_argument("--action-id", required=True)
    accept = sub.add_parser(
        "accept-without-resume",
        help="commit one answer event without dispatching a child",
    )
    accept.add_argument("--home", type=Path, required=True)
    accept.add_argument("--action-id", required=True)
    accept.add_argument("--binding-file", type=Path, required=True)
    recover = sub.add_parser(
        "recover",
        help="recover accepted continuations in a new process",
    )
    recover.add_argument("--home", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "create":
        return _create(args.home, args.actor, args.json_out)
    if args.command == "accept-without-resume":
        return _accept_without_resume(
            args.home,
            args.action_id,
            args.binding_file,
        )
    if args.command == "recover":
        return _recover(args.home)
    return _state(args.home, args.action_id)


if __name__ == "__main__":
    raise SystemExit(main())
