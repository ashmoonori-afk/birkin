from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from birkin import approvals, config, moirai, store
from birkin.moirai import journal


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))


def _write_script(tmp_path: Path, *, with_agent: bool = False) -> Path:
    role = (
        '"roles": {"worker": {"default": "codex:test"}}'
        if with_agent
        else '"roles": {}'
    )
    prefix = (
        'prefix = m.agent("prefix", role="worker")'
        if with_agent
        else 'prefix = "no-agent"'
    )
    path = tmp_path / "wait_for_input.py"
    path.write_text(
        f'''
meta = {{"name": "wait-for-input", {role}}}

def main(m):
    {prefix}
    supplied = m.request_answers(
        step_id="deploy-target",
        title="Deploy release",
        description="Choose the deployment target.",
        questions=[{{
            "id": "choice",
            "text": "Continue?",
            "options": [{{"value": "yes", "label": "Yes"}}],
        }}],
        expected_actor="web:dashboard",
        expected_capability="dashboard.approvals.answer.v1",
    )
    return {{"prefix": prefix, "input": supplied}}
''',
        encoding="utf-8",
    )
    return path


def _write_custom_script(
    tmp_path: Path,
    *,
    name: str,
    imports: str = "",
    before: str = "",
    after: str = 'return {"input": supplied}',
    roles: str = "{}",
) -> Path:
    path = tmp_path / f"{name}.py"
    path.write_text(
        f'''
{imports}
meta = {{"name": {name!r}, "roles": {roles}}}

def main(m):
{before}
    supplied = m.request_answers(
        step_id="deploy-target",
        title="Deploy release",
        description="Choose the deployment target.",
        questions=[{{
            "id": "choice",
            "text": "Continue?",
            "options": [{{"value": "yes", "label": "Yes"}}],
        }}],
        expected_actor="web:dashboard",
        expected_capability="dashboard.approvals.answer.v1",
    )
    {after}
''',
        encoding="utf-8",
    )
    return path


def _run_waiting_script(
    path: Path,
    *,
    cfg: dict[str, Any] | None = None,
    spawn: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    outcome = moirai.run_script(
        moirai.load_script(path),
        cfg=cfg or {},
        spawn=spawn,
    )
    assert outcome["status"] == "waiting_input"
    pending = store.list_pending()
    assert len(pending) == 1
    return outcome, pending[0]


def _waiting_action(
    tmp_path: Path,
    *,
    with_agent: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    script = moirai.load_script(_write_script(tmp_path, with_agent=with_agent))

    def spawn(
        prompt: str,
        binding: Any,
        opts: dict[str, Any],
        cfg: dict[str, Any],
        *,
        timeout: float = 900.0,
    ) -> str:
        del binding, opts, cfg, timeout
        return f"result:{prompt}"

    outcome = moirai.run_script(script, cfg={}, spawn=spawn)
    assert outcome["status"] == "waiting_input"
    pending = store.list_pending()
    assert len(pending) == 1
    record = pending[0]
    wait = journal.get_input_wait(record["id"])
    assert wait is not None
    return outcome, record, wait


def _answer(
    record: dict[str, Any],
    *,
    source: str = "web:dashboard",
    question_digest: str | None = None,
    resume_token: str | None = None,
    input_schema_version: int | None = 1,
    previous_state_digest: str | None = None,
) -> dict[str, Any]:
    return approvals.answer(
        record["id"],
        answers={"choice": "yes"},
        source=source,
        capability="dashboard.approvals.answer.v1",
        question_digest=question_digest or record["question_digest"],
        resume_token=resume_token or record["resume_token"],
        input_schema_version=input_schema_version,
        previous_state_digest=(
            previous_state_digest or record["previous_state_digest"]
        ),
    )


def test_moirai_question_persists_bound_continuation(
    tmp_path: Path,
) -> None:
    outcome, record, wait = _waiting_action(tmp_path)

    assert record["id"] == wait["action_id"]
    assert wait["run_id"] == outcome["run_id"]
    assert wait["worker_id"] == "main"
    assert wait["step_id"] == "deploy-target"
    assert len(wait["question_digest"]) == 64
    assert wait["expected_actor"] == "web:dashboard"
    assert wait["expected_capability"] == "dashboard.approvals.answer.v1"
    assert wait["expires_at"].endswith("+00:00")
    assert len(wait["resume_token"]) >= 43
    assert wait["input_schema_version"] == 1
    assert len(wait["previous_state_digest"]) == 64
    assert record["continuation"] == {
        "schema": 1,
        "handler": "moirai.resume.v1",
        "worker": "moirai",
        "context": {
            key: wait[key]
            for key in (
                "action_id",
                "run_id",
                "worker_id",
                "step_id",
                "question_digest",
                "expected_actor",
                "expected_capability",
                "expires_at",
                "resume_token",
                "input_schema_version",
                "previous_state_digest",
            )
        },
    }


def test_answer_rejects_stale_question_wrong_actor_and_tampered_continuation(
    tmp_path: Path,
) -> None:
    _, record, _ = _waiting_action(tmp_path)
    attempts = [
        lambda: _answer(record, source="web:other"),
        lambda: _answer(record, question_digest="0" * 64),
        lambda: _answer(record, resume_token="tampered"),
        lambda: _answer(record, previous_state_digest="f" * 64),
        lambda: _answer(record, input_schema_version=2),
    ]
    for attempt in attempts:
        rejected = attempt()
        assert rejected["ok"] is False
        assert rejected["event"] == "reply_rejected"
        pending = store.get_pending(record["id"])
        assert pending is not None
        assert pending["status"] == "pending"
        assert journal.get_accepted_answer(record["id"]) is None


def test_answer_appends_event_before_single_resume_under_concurrency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from birkin.moirai import continuation

    _, record, _ = _waiting_action(tmp_path)
    observed: list[int] = []

    def resume(action_id: str, **unused: Any) -> dict[str, Any]:
        event = journal.get_accepted_answer(action_id)
        assert event is not None, "accepted event must commit before resume"
        observed.append(event["event_id"])
        return {"ok": True, "resume_run_id": "child-run"}

    monkeypatch.setattr(continuation, "resume", resume)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: approvals.answer(
                    record["id"],
                    answers={"choice": "yes"},
                    source="web:dashboard",
                    capability="dashboard.approvals.answer.v1",
                    question_digest=record["question_digest"],
                    resume_token=record["resume_token"],
                    input_schema_version=record["input_schema_version"],
                    previous_state_digest=record["previous_state_digest"],
                ),
                range(2),
            )
        )

    assert sorted(result["event"] for result in results) == [
        "action_resolved",
        "reply_rejected",
    ]
    assert len(observed) == 1
    event = journal.get_accepted_answer(record["id"])
    assert event is not None
    assert event["event_id"] == observed[0]


def test_moirai_resumes_exact_step_with_schema_bound_answer_after_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from birkin.moirai import continuation

    source, record, _ = _waiting_action(tmp_path, with_agent=True)
    real_resume = continuation.resume

    def crash_after_acceptance(action_id: str, **unused: Any) -> dict[str, Any]:
        assert journal.get_accepted_answer(action_id) is not None
        raise RuntimeError("simulated process exit")

    monkeypatch.setattr(continuation, "resume", crash_after_acceptance)
    accepted = _answer(record)
    assert accepted["ok"] is True
    accepted_wait = journal.get_input_wait(record["id"])
    assert accepted_wait is not None
    assert accepted_wait["state"] == "accepted"

    monkeypatch.setattr(continuation, "resume", real_resume)

    def no_live_spawn(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("durable prefix must replay without a live call")

    recovered = continuation.recover(spawn=no_live_spawn)
    assert recovered == [record["id"]]

    wait = journal.get_input_wait(record["id"])
    assert wait is not None
    assert wait["state"] == "resumed"
    child = journal.get_run(wait["resume_run_id"])
    assert child is not None
    assert child["parent_run_id"] == source["run_id"]
    assert child["resume_action_id"] == record["id"]
    assert child["status"] == "completed"
    result = json.loads(child["result_json"])
    assert result == {
        "prefix": "result:prefix",
        "input": {
            "version": 1,
            "answers": {"choice": "yes"},
            "clarification": "",
            "navigation": [],
        },
    }


def test_recovery_republishes_missing_pending_projection(
    tmp_path: Path,
) -> None:
    from birkin.moirai import continuation

    _, record, _ = _waiting_action(tmp_path)
    pending_path = config.pending_dir() / f"{record['id']}.json"
    pending_path.unlink()

    continuation.recover()

    repaired = store.get_pending(record["id"])
    assert repaired is not None
    assert repaired["status"] == "pending"
    assert repaired["question_digest"] == record["question_digest"]


def test_resume_preserves_source_runtime_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from birkin.moirai import continuation

    path = _write_custom_script(
        tmp_path,
        name="cfg-preserved",
        after='return {"input": supplied, "post": m.agent("post", role="worker")}',
        roles='{"worker": {"default": "codex:test"}}',
    )
    source, record = _run_waiting_script(
        path,
        cfg={"runtime_marker": "kept"},
    )
    real_resume = continuation.resume
    monkeypatch.setattr(
        continuation,
        "resume",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("simulated process exit")
        ),
    )
    assert _answer(record)["ok"] is True
    monkeypatch.setattr(continuation, "resume", real_resume)

    seen_cfg: list[dict[str, Any]] = []

    def spawn(
        prompt: str,
        binding: Any,
        opts: dict[str, Any],
        cfg: dict[str, Any],
        *,
        timeout: float = 900.0,
    ) -> str:
        del binding, opts, timeout
        seen_cfg.append(dict(cfg))
        return f"result:{prompt}"

    assert continuation.recover(spawn=spawn) == [record["id"]]
    assert seen_cfg == [{"runtime_marker": "kept"}]
    wait = journal.get_input_wait(record["id"])
    assert wait is not None
    child = journal.get_run(wait["resume_run_id"])
    assert child is not None
    assert child["parent_run_id"] == source["run_id"]


def test_recovery_finalizes_completed_child_without_reexecution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from birkin.moirai import continuation

    effect = tmp_path / "effect.txt"
    path = _write_custom_script(
        tmp_path,
        name="completed-child",
        imports="from pathlib import Path",
        after=(
            f'Path({str(effect)!r}).write_text('
            f'(Path({str(effect)!r}).read_text() if '
            f'Path({str(effect)!r}).exists() else "") + "effect\\n"); '
            'return {"input": supplied}'
        ),
    )
    _, record = _run_waiting_script(path)
    real_finish = journal.finish_resume

    def crash_before_wait_finalize(
        action_id: str,
        *,
        state: str,
        error: str = "",
    ) -> None:
        if state == "resumed":
            raise RuntimeError("simulated process exit")
        real_finish(action_id, state=state, error=error)

    monkeypatch.setattr(journal, "finish_resume", crash_before_wait_finalize)
    assert _answer(record)["ok"] is True
    assert effect.read_text(encoding="utf-8").splitlines() == ["effect"]
    wait = journal.get_input_wait(record["id"])
    assert wait is not None
    assert wait["state"] == "dispatching"
    child = journal.get_run(wait["resume_run_id"])
    assert child is not None
    assert child["status"] == "completed"

    monkeypatch.setattr(journal, "finish_resume", real_finish)
    assert continuation.recover() == [record["id"]]
    assert effect.read_text(encoding="utf-8").splitlines() == ["effect"]
    repaired = journal.get_input_wait(record["id"])
    assert repaired is not None
    assert repaired["state"] == "resumed"


def test_resume_executes_the_verified_script_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from birkin.moirai import continuation

    tampered_effect = tmp_path / "tampered.txt"
    path = _write_custom_script(
        tmp_path,
        name="verified-source",
        after='return {"source": "verified", "input": supplied}',
    )
    _, record = _run_waiting_script(path)
    real_resume = continuation.resume
    monkeypatch.setattr(
        continuation,
        "resume",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("simulated process exit")
        ),
    )
    assert _answer(record)["ok"] is True
    monkeypatch.setattr(continuation, "resume", real_resume)

    original_read_text = Path.read_text
    reads = 0
    tampered_source = path.read_text(encoding="utf-8").replace(
        'return {"source": "verified", "input": supplied}',
        (
            f'Path({str(tampered_effect)!r}).write_text("executed"); '
            'return {"source": "tampered", "input": supplied}'
        ),
    ).replace(
        'meta = {"name":',
        'from pathlib import Path\nmeta = {"name":',
    )

    def swapping_read_text(
        candidate: Path,
        *args: Any,
        **kwargs: Any,
    ) -> str:
        nonlocal reads
        if candidate == path:
            reads += 1
            if reads > 1:
                return tampered_source
        return original_read_text(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", swapping_read_text)
    assert continuation.resume(record["id"])["ok"] is True
    assert not tampered_effect.exists()
    wait = journal.get_input_wait(record["id"])
    assert wait is not None
    child = journal.get_run(wait["resume_run_id"])
    assert child is not None
    assert json.loads(child["result_json"])["source"] == "verified"


def test_parallel_prefix_replays_independent_of_thread_scheduling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from birkin.moirai import continuation

    marker = tmp_path / "parallel-seen"
    source_prefix = tmp_path / "source-prefix.json"
    before = f'''
    first = not Path({str(marker)!r}).exists()
    gate = threading.Event()
    def lane_a():
        if first:
            gate.wait()
            return m.agent("same", role="worker")
        result = m.agent("same", role="worker")
        gate.set()
        return result
    def lane_b():
        if first:
            result = m.agent("same", role="worker")
            gate.set()
            return result
        gate.wait()
        return m.agent("same", role="worker")
    prefix = m.parallel([lane_a, lane_b])
    if first:
        Path({str(source_prefix)!r}).write_text(json.dumps(prefix))
    Path({str(marker)!r}).write_text("seen")
'''
    path = _write_custom_script(
        tmp_path,
        name="parallel-prefix",
        imports="import json\nimport threading\nfrom pathlib import Path",
        before=before,
        after='return {"prefix": prefix, "input": supplied}',
        roles='{"worker": {"default": "codex:test"}}',
    )

    calls = 0

    def source_spawn(
        prompt: str,
        binding: Any,
        opts: dict[str, Any],
        cfg: dict[str, Any],
        *,
        timeout: float = 900.0,
    ) -> str:
        nonlocal calls
        del binding, opts, cfg, timeout
        calls += 1
        return f"result:{prompt}:{calls}"

    _, record = _run_waiting_script(path, spawn=source_spawn)
    real_resume = continuation.resume
    monkeypatch.setattr(
        continuation,
        "resume",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("simulated process exit")
        ),
    )
    assert _answer(record)["ok"] is True
    monkeypatch.setattr(continuation, "resume", real_resume)

    def no_live_spawn(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("parallel prefix must replay without live calls")

    assert continuation.recover(spawn=no_live_spawn) == [record["id"]]
    wait = journal.get_input_wait(record["id"])
    assert wait is not None
    child = journal.get_run(wait["resume_run_id"])
    assert child is not None
    assert json.loads(child["result_json"])["prefix"] == json.loads(
        source_prefix.read_text(encoding="utf-8")
    )


def test_resume_fails_before_execution_when_child_run_is_not_durable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from birkin.moirai import continuation

    effect = tmp_path / "unjournaled-effect.txt"
    path = _write_custom_script(
        tmp_path,
        name="journal-failure",
        imports="from pathlib import Path",
        after=(
            f'Path({str(effect)!r}).write_text("executed"); '
            'return {"input": supplied}'
        ),
    )
    _, record = _run_waiting_script(path)
    real_resume = continuation.resume
    monkeypatch.setattr(
        continuation,
        "resume",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("simulated process exit")
        ),
    )
    assert _answer(record)["ok"] is True
    monkeypatch.setattr(continuation, "resume", real_resume)
    monkeypatch.setattr(journal, "start_run", lambda *args, **kwargs: None)

    with pytest.raises(journal.ContinuationJournalError):
        continuation.resume(record["id"])
    assert not effect.exists()
