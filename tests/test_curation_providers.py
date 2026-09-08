from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from birkin import curation_schema, providers


def test_codex_completer_is_readonly_and_never_copies_the_login(
        monkeypatch, tmp_path):
    """The CLI path must not clone ~/.codex/auth.json.

    It used to copy the credential into a throwaway CODEX_HOME. OpenAI rotates
    the refresh token, so the first refresh inside the copy killed the user's
    real codex login — the copy is the bug, not the isolation.
    """
    source_home = tmp_path / "source-codex"
    source_home.mkdir()
    (source_home / "auth.json").write_text("{}", encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(source_home))
    monkeypatch.setattr(providers.shutil, "which",
                        lambda name: "codex.exe" if name == "codex" else None)
    captured = {}

    def fake_run(argv, stdin=None, timeout=0, cwd=None, env=None):
        outpath = Path(argv[argv.index("-o") + 1])
        schema_path = Path(argv[argv.index("--output-schema") + 1])
        outpath.write_text("```json\n{\"plan_version\":1,\"ops\":[]}\n```",
                           encoding="utf-8")
        captured.update({"argv": argv, "timeout": timeout, "cwd": cwd,
                         "env": env, "outpath": outpath, "stdin": stdin,
                         "schema": json.loads(schema_path.read_text(
                             encoding="utf-8"))})
        return "", "", 0

    monkeypatch.setattr(providers, "_run", fake_run)
    complete = providers.codex_completer("gpt-test", timeout=12,
                                       schema=curation_schema.curation_plan_provider_schema(),
                                         cwd=str(vault))

    assert complete("prompt") == "```json\n{\"plan_version\":1,\"ops\":[]}\n```"
    argv = captured["argv"]
    assert argv[:2] == ["codex.exe", "exec"]
    assert "--sandbox" in argv and argv[argv.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in argv
    assert "--ignore-rules" in argv
    assert "--ephemeral" in argv
    assert "--output-schema" in argv
    schema_path = Path(argv[argv.index("--output-schema") + 1])
    assert "--cd" in argv and argv[argv.index("--cd") + 1] == str(vault)
    assert "-m" in argv and argv[argv.index("-m") + 1] == "gpt-test"
    assert argv[-1] == "-"
    assert "prompt" not in argv
    assert captured["stdin"] == "prompt"
    items = captured["schema"]["properties"]["ops"]["items"]
    assert items["additionalProperties"] is False
    assert "anyOf" not in items
    assert set(items["required"]) == set(items["properties"])
    assert captured["timeout"] == 12
    assert captured["cwd"] == str(vault)
    # No env override at all: codex uses the real CODEX_HOME and refreshes its
    # own credential in place, so nothing is burned.
    assert captured["env"] is None
    assert (source_home / "auth.json").read_text(encoding="utf-8") == "{}"
    assert list(tmp_path.glob("**/*-codex-home*")) == []
    assert not captured["outpath"].exists()
    assert not schema_path.exists()


def test_codex_failed_exit_rejects_partial_output_without_leaking_stderr(
        monkeypatch, tmp_path):
    prompt_marker = "PRIVATE USER PROMPT"
    monkeypatch.setattr(providers.shutil, "which", lambda name: "codex.exe")

    def fake_run(argv, **kwargs):
        Path(argv[argv.index("-o") + 1]).write_text(
            '{"looks":"valid"}', encoding="utf-8")
        return '{"also":"partial"}', f"startup warning\n{prompt_marker}", 17

    monkeypatch.setattr(providers, "_run", fake_run)

    out = providers.codex_completer(cwd=str(tmp_path))(prompt_marker)

    assert out == "[provider-error] codex: 종료 코드 17"
    assert prompt_marker not in out


def test_codex_success_still_returns_output_file(monkeypatch, tmp_path):
    monkeypatch.setattr(providers.shutil, "which", lambda name: "codex.exe")

    def fake_run(argv, **kwargs):
        Path(argv[argv.index("-o") + 1]).write_text("model answer", encoding="utf-8")
        return "progress", "startup warning", 0

    monkeypatch.setattr(providers, "_run", fake_run)

    assert providers.codex_completer(cwd=str(tmp_path))("prompt") == "model answer"


def test_codex_empty_success_does_not_leak_stderr(monkeypatch, tmp_path):
    prompt_marker = "PRIVATE USER PROMPT"
    monkeypatch.setattr(providers.shutil, "which", lambda name: "codex.exe")
    monkeypatch.setattr(
        providers, "_run",
        lambda *args, **kwargs: ("", f"startup warning\n{prompt_marker}", 0),
    )

    out = providers.codex_completer(cwd=str(tmp_path))(prompt_marker)

    assert out == "[provider-error] codex: 모델 응답이 비어 있습니다"
    assert prompt_marker not in out


def test_get_completer_passes_cwd_to_codex_alias(monkeypatch):
    called = {}

    def fake_codex(model=None, timeout=0, cwd=None, schema=None):
        called.update({"model": model, "timeout": timeout, "cwd": cwd,
                       "schema": schema})
        return lambda prompt: "ok"

    monkeypatch.setattr(providers, "codex_completer", fake_codex)
    monkeypatch.setattr(providers, "codex_oauth_available", lambda: False)
    complete = providers.get_completer("codex-cli", model="gpt-test",
                                       timeout=7, cwd="vault-path")

    assert complete("prompt") == "ok"
    assert called == {"model": "gpt-test", "timeout": 7,
                      "cwd": "vault-path", "schema": None}


def test_get_completer_prefers_oauth_when_birkin_has_its_own_login(monkeypatch):
    """OAuth beats the CLI: no subprocess, and the CLI need not be installed."""
    called = {}

    def fake_oauth(model=None, timeout=0, cfg=None, schema=None):
        called.update({"model": model, "timeout": timeout, "cfg": cfg,
                       "schema": schema})
        return lambda prompt: "oauth-ok"

    def boom(*a, **k):  # the CLI path must not be taken
        raise AssertionError("codex CLI used despite an OAuth login")

    monkeypatch.setattr(providers, "codex_oauth_available", lambda: True)
    monkeypatch.setattr(providers, "codex_oauth_completer", fake_oauth)
    monkeypatch.setattr(providers, "codex_completer", boom)
    complete = providers.get_completer("codex", model="gpt-test", timeout=7,
                                       cfg={"k": 1}, cwd="vault-path")

    assert complete("prompt") == "oauth-ok"
    assert called == {"model": "gpt-test", "timeout": 7, "cfg": {"k": 1},
                      "schema": None}


def test_claude_auth_failure_is_an_error_not_an_answer(monkeypatch):
    """`claude -p` reports auth trouble in band — exit 0, normal envelope.

    birkin used to return payload["result"] unconditionally, so
    "Failed to authenticate: OAuth session expired and could not be refreshed"
    came back as the model's answer and workflows built on that sentence.
    """
    monkeypatch.setattr(providers.shutil, "which",
                        lambda name: "claude.exe" if name == "claude" else None)
    envelope = json.dumps({
        "type": "result", "subtype": "success", "is_error": True,
        "result": "Failed to authenticate: OAuth session expired and "
                  "could not be refreshed"})
    monkeypatch.setattr(providers, "_run",
                        lambda *a, **k: (envelope, "", 0))

    out = providers.claude_completer()("hi")
    assert out.startswith("[provider-error] claude:")
    assert "Failed to authenticate" in out


def test_claude_success_still_returns_plain_text(monkeypatch):
    monkeypatch.setattr(providers.shutil, "which",
                        lambda name: "claude.exe" if name == "claude" else None)
    envelope = json.dumps({"type": "result", "subtype": "success",
                           "is_error": False, "result": "PONG"})
    monkeypatch.setattr(providers, "_run", lambda *a, **k: (envelope, "", 0))

    assert providers.claude_completer()("hi") == "PONG"


def test_the_provider_layer_does_not_impose_a_schema_by_default():
    """A generic completer must not force one application's output shape.

    codex_completer used to write the CurationPlan schema on every call, so
    asking codex for a word came back as {"plan_version":1,"summary":"..."} —
    found by dogfooding the workflow engine, which shares this layer.
    """
    import inspect
    src = inspect.getsource(providers.codex_completer)
    assert "if schema:" in src, "schema must be opt-in"
    assert "plan_version" not in src, "no application schema inside the completer"
    assert not hasattr(providers, "CURATION_PLAN_SCHEMA")


def test_run_abort_stops_the_whole_cli_process_tree(tmp_path):
    marker = tmp_path / "orphan.txt"
    child = (
        "import time, pathlib; time.sleep(0.8); "
        f"pathlib.Path({str(marker)!r}).write_text('orphan')"
    )
    parent = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(10)"
    )
    abort = threading.Event()
    timer = threading.Timer(0.1, abort.set)
    timer.start()
    started = time.monotonic()
    try:
        _out, _err, code = providers._run(
            [sys.executable, "-c", parent], timeout=10, abort=abort,
        )
    finally:
        timer.cancel()
    assert code == -2 and time.monotonic() - started < 3
    time.sleep(1)
    assert not marker.exists()


def test_cancelled_cli_output_is_never_returned_as_model_text(monkeypatch, tmp_path):
    monkeypatch.setattr(providers.shutil, "which", lambda name: f"{name}.exe")
    monkeypatch.setattr(providers, "_run", lambda *args, **kwargs: ("partial", "", -2))
    assert providers.claude_completer(abort=threading.Event())("q").endswith("cancelled")
    assert providers.codex_completer(cwd=str(tmp_path), abort=threading.Event())("q").endswith("cancelled")


def test_run_with_pre_cancelled_event_does_not_start_process(monkeypatch):
    abort = threading.Event()
    abort.set()
    monkeypatch.setattr(
        providers.subprocess, "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("spawned")),
    )
    assert providers._run(["unused"], abort=abort)[2] == -2


def test_run_cleans_up_child_tree_on_keyboard_interrupt(monkeypatch):
    class Process:
        returncode = None
        calls = 0

        def communicate(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise KeyboardInterrupt
            return "", ""

    process = Process()
    killed = []
    monkeypatch.setattr(providers.os, "name", "posix")
    monkeypatch.setattr(providers.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr("birkin.proc.kill_tree", lambda child: killed.append(child))

    with pytest.raises(KeyboardInterrupt):
        providers._run(["command"])

    assert killed == [process]
    assert process.calls == 2


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object cleanup")
def test_run_kills_suspended_process_when_job_assignment_fails(monkeypatch):
    class Process:
        pid = 123
        killed = False
        waited = False

        def poll(self):
            return None

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            self.waited = True

    class Job:
        terminated = False
        closed = False

        def assign(self, pid):
            raise OSError("assign failed")

        def terminate(self):
            self.terminated = True

        def close(self):
            self.closed = True

    process = Process()
    job = Job()
    monkeypatch.setattr(providers.subprocess, "Popen",
                        lambda *args, **kwargs: process)
    monkeypatch.setattr("birkin._winjob.WindowsJob.create", lambda: job)

    with pytest.raises(OSError, match="assign failed"):
        providers._run(["command"])

    assert job.terminated and job.closed
    assert process.killed and process.waited


def test_curation_still_asks_for_its_schema_explicitly():
    import inspect

    from birkin import curation_cli
    src = inspect.getsource(curation_cli.cmd_curate_memory)
    assert "curation_plan_provider_schema" in src
