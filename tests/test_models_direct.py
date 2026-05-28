"""Direct tests for models.py — discovery, render, apply_selection."""

from __future__ import annotations

import shutil

import pytest

from birkin import models


def test_discover_curated_anthropic_present():
    cfg = {"provider": "anthropic", "model": "claude-sonnet-4-6"}
    found = models.discover(cfg, api=False, cli=False, ollama=False)
    ids = [m.id for m in found]
    assert "claude-sonnet-4-6" in ids
    assert all(m.source == "anthropic" for m in found)


def test_discover_includes_local_cli_when_configured():
    cfg = {"provider": "anthropic", "cli_command": ["my-llm", "--x"]}
    found = models.discover(cfg, api=False, cli=True, ollama=False)
    cli = [m for m in found if m.source == "local-cli"]
    assert cli and cli[0].is_cli
    assert "my-llm" in cli[0].note


def test_discover_detects_claude_codex_if_present(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: f"/fake/{name}")
    found = models.detect_cli_agents()
    sources = {m.source for m in found}
    assert {"claude-cli", "codex-cli"} <= sources


def test_render_groups_and_marks_current(capsys):
    cfg = {"provider": "anthropic"}
    found = models.discover(cfg, api=False, cli=False, ollama=False)
    models.render(found, current="claude-sonnet-4-6")
    out = capsys.readouterr().out
    assert "API models" in out
    assert "claude-sonnet-4-6" in out
    assert "*" in out  # current marker


def test_apply_selection_claude_cli_sets_provider_and_model():
    cfg = {"provider": "anthropic", "model": "x", "base_url": "https://x"}
    m = models.Model("claude-code (sonnet)", "claude-cli", "Claude Code · sonnet",
                     param="sonnet")
    models.apply_selection(cfg, m)
    assert cfg["provider"] == "claude-cli"
    assert cfg["model"] == "sonnet"
    assert cfg["base_url"] == ""


def test_apply_selection_codex_cli_clears_model():
    cfg = {"provider": "anthropic", "model": "claude-x", "base_url": "https://x"}
    m = models.Model("codex", "codex-cli", "Codex CLI", param="")
    models.apply_selection(cfg, m)
    assert cfg["provider"] == "codex-cli"
    assert cfg["model"] == ""
    assert cfg["base_url"] == ""


def test_apply_selection_local_cli():
    cfg = {"provider": "anthropic", "model": "x", "base_url": "y"}
    m = models.Model("local-cli", "local-cli", "configured: my-llm")
    models.apply_selection(cfg, m)
    assert cfg["provider"] == "local-cli"
    assert cfg["base_url"] == ""


def test_apply_selection_ollama_rewires_openai_with_local_endpoint():
    cfg = {"provider": "anthropic", "model": "x", "api_key": None}
    m = models.Model("llama3.1:8b", "ollama", "local · ollama")
    models.apply_selection(cfg, m)
    assert cfg["provider"] == "openai"
    assert cfg["base_url"].endswith("/v1")
    assert cfg["model"] == "llama3.1:8b"
    assert cfg.get("api_key") == "ollama"


def test_apply_selection_anthropic_keeps_provider():
    cfg = {"provider": "openai"}
    m = models.Model("claude-opus-4-7", "anthropic", "deepest reasoning")
    models.apply_selection(cfg, m)
    assert cfg["provider"] == "anthropic"
    assert cfg["model"] == "claude-opus-4-7"


def test_fetch_api_models_skips_without_key():
    # autouse fixture scrubbed env keys; no api_key in cfg
    cfg = {"provider": "anthropic"}
    assert models.fetch_api_models(cfg) == []


def test_fetch_ollama_models_returns_empty_when_unreachable(monkeypatch):
    monkeypatch.setattr(models, "_get_json", lambda url, headers, timeout: None)
    assert models.fetch_ollama_models() == []
