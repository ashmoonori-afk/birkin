"""Security-hardening tests (ADR-029): cron→shell gate, gateway access, token env."""

from __future__ import annotations

from birkin import approvals


def test_shell_cron_not_auto_applied_when_only_cron_approved(tmp_path, monkeypatch):
    """An auto-approved `cron` must NOT launder a shell payload past the shell gate."""
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    cfg = {"auto_approve": ["cron"]}  # cron trusted, shell NOT
    st = approvals.propose(category="cron", title="nightly cleanup", description="",
                           payload={"type": "shell", "value": "rm -rf x",
                                    "name": "j", "hour": 4, "minute": 5}, cfg=cfg)
    assert st["auto"] is False          # queued for review, not executed
    assert "id" in st


def test_prompt_cron_auto_applies_when_cron_approved(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    cfg = {"auto_approve": ["cron"]}
    st = approvals.propose(category="cron", title="digest", description="",
                           payload={"type": "prompt", "value": "summarize",
                                    "name": "d", "hour": 9, "minute": 0}, cfg=cfg)
    assert st["auto"] is True           # non-shell cron is fine


def test_shell_cron_auto_applies_only_when_shell_also_approved(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    cfg = {"auto_approve": ["cron", "shell"]}  # operator explicitly trusts shell
    st = approvals.propose(category="cron", title="job", description="",
                           payload={"type": "shell", "value": "echo hi",
                                    "name": "j", "hour": 4, "minute": 5}, cfg=cfg)
    assert st["auto"] is True


def test_default_policy_queues_cron(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    cfg = {"auto_approve": ["memory", "skill"]}  # default
    st = approvals.propose(category="cron", title="j", description="",
                           payload={"type": "shell", "value": "x", "name": "j"}, cfg=cfg)
    assert st["auto"] is False


def test_telegram_token_prefers_env(monkeypatch):
    from birkin.gateway import channels
    monkeypatch.delenv("BIRKIN_TELEGRAM_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "ENVTOK")
    assert channels.telegram_token({"token": "CFGTOK"}) == "ENVTOK"
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert channels.telegram_token({"token": "CFGTOK"}) == "CFGTOK"
    assert channels.telegram_token({}) == ""


def test_telegram_allowlist_stored():
    from birkin.gateway.channels.telegram import TelegramChannel
    ch = TelegramChannel("tok", allowed_chat_ids=["111", "222"])
    assert ch.allowed_chat_ids == {"111", "222"}


def test_gateway_forces_workspace_over_full(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin.gateway.core import Gateway
    gw = Gateway({"provider": "claude-cli", "cli_access": "full",
                  "gateway_persistent": True})
    assert gw.cfg["cli_access"] == "workspace"  # never 'full' for a reachable service
