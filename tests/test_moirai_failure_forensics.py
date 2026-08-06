"""Failure forensics: a dead run must explain itself from the DB alone.

A 59-minute gateway turn died with `codex turn timed out after 900s of
silence` and left NOTHING in moirai.db — the only trace was an untimestamped
console line. A moirai run that did fail recorded `'NoneType' object has no
attribute 'get'`: the downstream symptom, not the `IncompleteRead` that
actually killed step-8. Neither failure reached the self-improvement pass,
because the gateway's timeout handler returns before `_record_turn`.

Five contracts:

* `Run.call_agent` failures carry a traceback and their role/label/phase into
  `calls.traceback`, and the run's own `result_json` names them.
* A `CodexTurnTimeout` writes ONE incident row with the forensics the console
  line had: elapsed seconds, partial chars, last event kind, event count.
* Boot reclaims runs left `running` by a killed process, without touching a
  run that is still alive.
* A failed turn reaches `_record_turn`, and the self-improvement transcript
  carries the failure rows instead of only the happy path.
* Gateway stdout and stderr lines carry UTC timestamps, including heartbeat
  output assembled from partial writes.
"""

from __future__ import annotations

import io
import json
import types

import pytest

from birkin import moirai
from birkin.moirai import bindings as B
from birkin.moirai import engine, journal


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    yield tmp_path


def _write(tmp_path, body: str, name: str = "wf.py"):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


BOOM = '''
meta = {"name": "boom", "description": "d",
        "roles": {"worker": {"default": "codex:gpt-5.6-sol"}}}

def main(m):
    out = m.agent("do the thing", role="worker", label="step-8")
    return {"answer": out}
'''


def _run_with_spawn(tmp_path, spawn, body: str = BOOM) -> dict:
    script = moirai.load_script(_write(tmp_path, body))
    binding_map = {
        role: B.Binding(role=role, provider="codex", model="gpt-5.6-sol",
                        source="test", tools="none")
        for role in script.roles
    }
    return engine.run_script(script, cfg={}, bindings_map=binding_map,
                             spawn=spawn)


def _persistent_gateway(monkeypatch, session):
    from birkin.gateway import core as gw_core
    monkeypatch.setattr(gw_core, "build_session", lambda cfg: session)
    gw = gw_core.Gateway({"provider": "codex-cli", "gateway_persistent": True})
    monkeypatch.setattr(gw._claude_sessions, "borrow", lambda key: session)
    monkeypatch.setattr(gw._claude_sessions, "release",
                        lambda key, sess: None)
    return gw


# ---------------- C1: engine failure forensics ----------------------------

class TestEngineFailureForensics:
    def test_a_raised_spawn_records_traceback_on_the_call(self, tmp_path):
        def spawn(_prompt, _binding, _opts, _cfg, *, timeout):
            raise ConnectionError("IncompleteRead(4371 bytes read)")

        out = _run_with_spawn(tmp_path, spawn)
        calls = journal.run_calls(out["run_id"])
        failed = [c for c in calls if c["status"] == "error"]
        assert len(failed) == 1, calls
        tb = failed[0].get("traceback") or ""
        assert "Traceback (most recent call last)" in tb, (
            "the exception that killed the call is not reconstructible")
        assert "IncompleteRead" in tb

    def test_the_run_result_names_the_failed_role_and_label(self, tmp_path):
        def spawn(_prompt, _binding, _opts, _cfg, *, timeout):
            raise ConnectionError("IncompleteRead(4371 bytes read)")

        out = _run_with_spawn(tmp_path, spawn)
        run = journal.get_run(out["run_id"])
        result = json.loads(run["result_json"] or "{}")
        failures = result.get("failures")
        assert failures, f"result_json has no failures section: {result}"
        first = failures[0]
        assert first["role"] == "worker"
        assert first["label"] == "step-8"
        assert first["reason"] == "exception"
        assert "IncompleteRead" in first["error"]
        assert "Traceback (most recent call last)" in first["traceback"]

    def test_a_provider_error_string_is_a_recorded_failure_too(self, tmp_path):
        def spawn(_prompt, _binding, _opts, _cfg, *, timeout):
            return "[provider-error] codex: exited 1"

        out = _run_with_spawn(tmp_path, spawn)
        run = journal.get_run(out["run_id"])
        failures = json.loads(run["result_json"] or "{}").get("failures") or []
        assert [f["reason"] for f in failures] == ["provider-error"]
        assert failures[0]["label"] == "step-8"

    def test_a_clean_run_carries_no_failures_key(self, tmp_path):
        def spawn(_prompt, _binding, _opts, _cfg, *, timeout):
            return "fine"

        out = _run_with_spawn(tmp_path, spawn)
        run = journal.get_run(out["run_id"])
        result = json.loads(run["result_json"] or "{}")
        assert "failures" not in result
        assert result["answer"] == "fine"


# ---------------- C2: gateway timeout incident ----------------------------

class TestGatewayTimeoutIncident:
    def test_a_codex_timeout_writes_one_incident_row(self, tmp_path,
                                                     monkeypatch):
        from birkin.codex_session import CodexTurnTimeout
        from birkin.gateway import core as gw_core

        agent = types.SimpleNamespace(messages=[])
        ticks = iter((100.0, 101.25))
        monkeypatch.setattr(gw_core.time, "monotonic", lambda: next(ticks))

        def ask(_text, on_text=None, on_progress=None, **_kwargs):
            if on_progress is not None:
                on_progress({"activity": 295, "streamed": 0,
                             "last_kind": "agentMessage",
                             "active_kind": "agentMessage"})
            raise CodexTurnTimeout(
                "codex turn timed out after 900s of silence", partial="부분 결과")

        session = types.SimpleNamespace(
            cfg={}, agent=agent, ask=ask,
            _prepare_cli_turn=lambda text, **_k: text,
            _record_turn=lambda *a, **k: None)
        gw = _persistent_gateway(monkeypatch, session)

        from birkin.moirai import trigger as moirai_trigger
        monkeypatch.setattr(moirai_trigger, "run_approved",
                            lambda payload, on_event=None: "복구 결과")

        gw.handle("http", "c1", "장기 작업 실행")

        rows = journal.recent_incidents(limit=10)
        assert len(rows) == 1, rows
        row = rows[0]
        assert row["kind"] == "codex_timeout"
        assert row["channel"] == "http"
        assert row["chat_id"] == "c1"
        assert row["elapsed_seconds"] > 0
        assert row["partial_chars"] == len("부분 결과")
        assert row["last_event_kind"] == "agentMessage"
        assert row["event_count"] == 295


# ---------------- C3: stale reclamation -----------------------------------

class TestStaleReclamation:
    def test_boot_marks_orphaned_running_rows_stale(self, tmp_path):
        journal.start_run("dead-1", name="hard-task", script_path="x.py",
                          script_sha256="a" * 8, args={}, bindings={})
        journal.record_call("dead-1", 15, "k", role="worker", label="step-9")

        reclaimed = journal.reclaim_stale_runs()

        assert reclaimed == 1
        run = journal.get_run("dead-1")
        assert run["status"] == "stale"
        assert run["finished"]
        call = journal.run_calls("dead-1")[0]
        assert call["status"] == "stale"
        assert call["finished"]

    def test_the_live_run_is_excluded(self, tmp_path):
        journal.start_run("dead-1", name="hard-task", script_path="x.py",
                          script_sha256="a" * 8, args={}, bindings={})
        journal.start_run("alive-1", name="hard-task", script_path="x.py",
                          script_sha256="a" * 8, args={}, bindings={})

        reclaimed = journal.reclaim_stale_runs(exclude={"alive-1"})

        assert reclaimed == 1
        assert journal.get_run("dead-1")["status"] == "stale"
        assert journal.get_run("alive-1")["status"] == "running"


# ---------------- C4: failures feed self-improvement ----------------------

class TestFailureFeedsSelfImprove:
    def test_a_timed_out_turn_still_reaches_record_turn(self, tmp_path,
                                                        monkeypatch):
        from birkin.codex_session import CodexTurnTimeout

        recorded: list[tuple[str, str]] = []
        agent = types.SimpleNamespace(messages=[])

        def ask(_text, on_text=None, on_progress=None, **_kwargs):
            raise CodexTurnTimeout("codex turn timed out after 900s of silence",
                                   partial="")

        session = types.SimpleNamespace(
            cfg={}, agent=agent, ask=ask,
            _prepare_cli_turn=lambda text, **_k: text,
            _record_turn=lambda text, reply, **_k: recorded.append((text, reply)))
        gw = _persistent_gateway(monkeypatch, session)

        from birkin.moirai import trigger as moirai_trigger
        monkeypatch.setattr(moirai_trigger, "run_approved",
                            lambda payload, on_event=None: "복구 결과")

        gw.handle("http", "c1", "장기 작업 실행")

        assert recorded, "a failed turn never reaches the self-improvement hook"
        assert recorded[0][0] == "장기 작업 실행"
        assert "복구 결과" in recorded[0][1]

    def test_the_review_transcript_carries_failure_rows(self, tmp_path):
        from birkin import runtime

        journal.start_run("r-1", name="hard-task", script_path="x.py",
                          script_sha256="a" * 8, args={}, bindings={})
        journal.record_call("r-1", 14, "k", role="worker", label="step-8")
        journal.finish_call("r-1", 14, status="error",
                            error="IncompleteRead(4371 bytes read)",
                            traceback="Traceback (most recent call last)\nboom")
        journal.record_incident(
            kind="codex_timeout", channel="telegram", chat_id="1170346056",
            elapsed_seconds=3543.6, partial_chars=0,
            last_event_kind="agentMessage", event_count=295,
            detail="codex turn timed out after 900s of silence")

        block = runtime.failure_context()

        assert "step-8" in block
        assert "IncompleteRead" in block
        assert "codex_timeout" in block
        assert "3543" in block

    def test_no_failures_means_no_block(self, tmp_path):
        from birkin import runtime
        assert runtime.failure_context() == ""


# ---------------- C5: timestamped gateway log -----------------------------

class TestTimestampedGatewayLog:
    def test_every_line_carries_an_iso_timestamp(self):
        import re
        from birkin.gateway import core as gw_core

        sink = io.StringIO()
        stamped = gw_core.TimestampedStream(sink)
        stamped.write("[gateway] up\n")
        stamped.write("[birkin] codex still working — 조사 중 (1분)\n")
        stamped.write("partial")          # no newline yet — must not stamp early
        stamped.write(" tail\n")

        lines = sink.getvalue().splitlines()
        assert len(lines) == 3, lines
        pattern = re.compile(r"^\[20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ\] ")
        for line in lines:
            assert pattern.match(line), line
        assert lines[0].endswith("[gateway] up")
        assert lines[2].endswith("partial tail")
