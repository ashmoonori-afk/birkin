from __future__ import annotations

import json
from pathlib import Path

from birkin import providers


def test_codex_completer_uses_readonly_isolated_home_and_cwd(
        monkeypatch, tmp_path):
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
                             encoding="utf-8")),
                         "auth_seeded": (Path(env["CODEX_HOME"]) /
                                         "auth.json").is_file()})
        return "", "", 0

    monkeypatch.setattr(providers, "_run", fake_run)
    complete = providers.codex_completer("gpt-test", timeout=12,
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
    isolated_home = Path(captured["env"]["CODEX_HOME"])
    assert isolated_home != source_home
    assert captured["auth_seeded"] is True
    assert not captured["outpath"].exists()
    assert not schema_path.exists()
    assert not isolated_home.exists()


def test_get_completer_passes_cwd_to_codex_alias(monkeypatch):
    called = {}

    def fake_codex(model=None, timeout=0, cwd=None):
        called.update({"model": model, "timeout": timeout, "cwd": cwd})
        return lambda prompt: "ok"

    monkeypatch.setattr(providers, "codex_completer", fake_codex)
    complete = providers.get_completer("codex-cli", model="gpt-test",
                                       timeout=7, cwd="vault-path")

    assert complete("prompt") == "ok"
    assert called == {"model": "gpt-test", "timeout": 7,
                      "cwd": "vault-path"}


def test_rmtree_retry_removes_transiently_locked_home(monkeypatch, tmp_path):
    target = tmp_path / "locked-codex-home"
    target.mkdir()
    (target / "auth.json").write_text("{}", encoding="utf-8")
    real_rmtree = providers.shutil.rmtree
    calls = []

    def flaky_rmtree(path, onerror=None):
        calls.append(Path(path))
        if len(calls) == 1:
            raise OSError("temporarily locked")
        return real_rmtree(path, onerror=onerror)

    monkeypatch.setattr(providers.shutil, "rmtree", flaky_rmtree)
    monkeypatch.setattr(providers.time, "sleep", lambda _seconds: None)

    providers._rmtree_retry(target, attempts=2, delay=0)

    assert len(calls) == 2
    assert all(str(path).endswith("locked-codex-home") for path in calls)
    assert not target.exists()
