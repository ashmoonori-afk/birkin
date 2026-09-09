"""A CLI provider that exits nonzero has not answered, whatever it printed."""

from __future__ import annotations

from birkin import providers


def _fake_run(out: str, err: str, code: int):
    def run(argv, stdin=None, timeout=0, **_):
        return out, err, code
    return run


def test_generic_cli_nonzero_exit_is_a_provider_error(monkeypatch):
    monkeypatch.setattr(providers.shutil, "which", lambda _: "/usr/bin/gemini")
    monkeypatch.setattr(providers, "_run",
                        _fake_run("partial diagnostic on stdout", "", 1))
    reply = providers._generic_cli_completer("gemini", ["-p", "-"], None, None, 5)("hi")
    assert reply.startswith("[provider-error] gemini exited 1")
    assert "partial diagnostic" in reply


def test_ollama_nonzero_exit_is_a_provider_error(monkeypatch):
    monkeypatch.setattr(providers.shutil, "which", lambda _: "/usr/bin/ollama")
    monkeypatch.setattr(providers, "_run",
                        _fake_run("pulling manifest", "model not found", 1))
    reply = providers.local_completer("llama3", 5)("hi")
    assert reply == "[provider-error] ollama exited 1: model not found"


def test_zero_exit_returns_stdout(monkeypatch):
    monkeypatch.setattr(providers.shutil, "which", lambda _: "/usr/bin/ollama")
    monkeypatch.setattr(providers, "_run", _fake_run("  answer  ", "", 0))
    assert providers.local_completer("llama3", 5)("hi") == "answer"
