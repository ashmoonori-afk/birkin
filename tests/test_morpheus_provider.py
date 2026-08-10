"""Run the nightly on a different backend than chat, and file one record.

`morpheus_provider` exists because of a measured dead end, not a preference:
on codex-cli the nightly can save NOTHING. `codex exec` pins approval to
"never", and that cancels MCP tool calls rather than allowing them —

    codex exec --sandbox read-only ... -c mcp_servers.birkin.enabled=true
    "call memory_search"  ->  "user cancelled MCP tool call"

with no narrower lever (`-a` is rejected by `exec`; `-c approval_policy=…` is
ignored). Only cli_access="full" gets through, and that also grants a shell to
an unattended process. The claude path is shaped differently: it allowlists
`mcp__birkin__*` through --allowedTools instead of asking per call, so the
writes land without Bash.

The dispatch was deliberately keyed on the CHAT provider so a Codex user would
never silently get `claude` spawned. That property is kept — the override is
explicit and empty by default.
"""

from __future__ import annotations

import pytest

from birkin import config, morpheus, scheduler, store


@pytest.fixture
def routed(monkeypatch):
    """Record which morpheus backend run_once dispatches to."""
    seen: dict = {}

    def claude(cfg, task, dry_run, n_files):
        seen.update(path="claude", cfg=cfg)
        return 0

    def generic(cfg, task, dry_run, n_files):
        seen.update(path="generic", cfg=cfg)
        return 0

    monkeypatch.setattr(morpheus, "_run_claude_morpheus", claude)
    monkeypatch.setattr(morpheus, "_run_birkin_morpheus", generic)
    monkeypatch.setattr(morpheus, "_gather_sessions", lambda: "")
    monkeypatch.setattr(morpheus, "_gather_changed_files", lambda _roots: "")
    monkeypatch.setattr(morpheus, "_gather_memory_state", lambda _cfg: "")
    monkeypatch.setattr(morpheus, "_run_curator", lambda _cfg, _dry: "")
    monkeypatch.setattr(store, "read_recent_activity", lambda: "")
    return seen


def _cfg(monkeypatch, **over):
    cfg = {**config.DEFAULT_CONFIG, **over}
    monkeypatch.setattr(config, "load_config", lambda: cfg)
    return cfg


def test_default_keeps_the_nightly_on_the_chat_provider(routed, monkeypatch):
    _cfg(monkeypatch, provider="codex-cli", morpheus_provider="")
    morpheus.run_once()
    assert routed["path"] == "generic"


def test_codex_user_is_never_silently_given_claude(routed, monkeypatch):
    """The property the original hard-coded dispatch was protecting."""
    _cfg(monkeypatch, provider="codex-cli")
    morpheus.run_once()
    assert routed["path"] == "generic"


def test_opting_in_routes_the_nightly_to_claude(routed, monkeypatch):
    _cfg(monkeypatch, provider="codex-cli", morpheus_provider="claude-cli")
    morpheus.run_once()
    assert routed["path"] == "claude", (
        "morpheus_provider did not move the nightly off the chat provider")
    assert routed["cfg"]["provider"] == "claude-cli", (
        "the claude path must see itself as claude-cli, not the chat provider")


def test_chat_provider_is_not_mutated(routed, monkeypatch):
    cfg = _cfg(monkeypatch, provider="codex-cli", morpheus_provider="claude-cli")
    morpheus.run_once()
    assert cfg["provider"] == "codex-cli", "the override leaked into chat config"


def test_claude_chat_still_uses_the_claude_path(routed, monkeypatch):
    _cfg(monkeypatch, provider="claude-cli", morpheus_provider="")
    morpheus.run_once()
    assert routed["path"] == "claude"


def test_an_unknown_override_falls_back_rather_than_crashing(routed, monkeypatch):
    _cfg(monkeypatch, provider="codex-cli", morpheus_provider="nonsense")
    morpheus.run_once()
    assert routed["path"] == "generic"


def test_the_key_ships_with_a_safe_default():
    assert config.DEFAULT_CONFIG["morpheus_provider"] == "", (
        "the nightly backend must not change for existing installs")


# -- one firing, one record ------------------------------------------------

def test_a_prompt_cron_job_files_exactly_one_run_record(monkeypatch):
    """A type="prompt" job recorded BOTH a "chat" and a "cron" run with the
    same timestamp — 3 firings produced 6 records on this install — and the
    tokens were counted twice in the ledger and the daily budget."""
    saved: list = []
    monkeypatch.setattr(store, "save_run",
                        lambda kind, summary, details=None, usage=None:
                        saved.append(kind))
    monkeypatch.setattr(scheduler.store, "save_run",
                        lambda kind, summary, details=None, usage=None:
                        saved.append(kind))
    asked: dict = {}

    class _Session:
        def ask(self, text, **kwargs):
            asked.update(kwargs)
            # A real Session files its own "chat" run unless told not to.
            if kwargs.get("record_turn", True):
                saved.append("chat")
            return "reply"

    monkeypatch.setattr("birkin.runtime.build_session", lambda *a, **k: _Session())
    monkeypatch.setattr(scheduler, "_deliver", lambda job, text: "none")

    scheduler._run_job({"id": "j1", "name": "nightly-thing", "type": "prompt",
                        "value": "what changed?"})

    assert asked.get("record_turn") is False, (
        "the cron job let ask() file a second record for the same firing")
    assert saved == ["cron"], f"expected one record, got {saved}"


# -- the model has to move with the provider -------------------------------

def test_the_chat_model_does_not_follow_the_nightly_to_claude(routed, monkeypatch):
    """Carrying provider over without the model sent codex's model name to
    claude, and the whole night died on:

        [birkin] Claude error: There's an issue with the selected model
        (gpt-5.6-terra). It may not exist or you may not have access to it.

    Empty means "the backend's own default" — claude gets no --model flag.
    """
    _cfg(monkeypatch, provider="codex-cli", model="gpt-5.6-terra",
         morpheus_provider="claude-cli")
    morpheus.run_once()
    assert routed["cfg"]["model"] == "", (
        "claude was handed the codex chat model: %r" % routed["cfg"]["model"])


def test_morpheus_model_overrides_when_set(routed, monkeypatch):
    _cfg(monkeypatch, provider="codex-cli", model="gpt-5.6-terra",
         morpheus_provider="claude-cli", morpheus_model="sonnet")
    morpheus.run_once()
    assert routed["cfg"]["model"] == "sonnet"


def test_same_provider_keeps_its_own_model(routed, monkeypatch):
    """No override in play — the chat model is the right model."""
    _cfg(monkeypatch, provider="claude-cli", model="sonnet", morpheus_provider="")
    morpheus.run_once()
    assert routed["cfg"]["model"] == "sonnet"


def test_both_keys_ship_empty():
    assert config.DEFAULT_CONFIG["morpheus_model"] == ""
