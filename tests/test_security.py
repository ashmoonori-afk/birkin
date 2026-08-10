"""Security-hardening tests (ADR-029): cron→shell gate, gateway access, token env.
Plus the advisory gateway warnings module (birkin.security)."""

from __future__ import annotations

import pytest

from birkin import approvals, security


# ---------------- advisory gateway warnings --------------------------------

def test_gateway_warnings_flag_native_loop_exposure():
    warns = security.gateway_warnings({"provider": "anthropic"})
    assert any("run_shell" in w for w in warns)
    assert any("fs_jail" in w for w in warns)


def test_gateway_warnings_quiet_for_gated_provider_with_lockdowns():
    warns = security.gateway_warnings({"provider": "claude-cli"})
    assert warns == []


@pytest.mark.parametrize("provider", ["codex-cli", "local-cli"])
def test_gateway_warnings_describe_external_cli_boundary(provider):
    warns = security.gateway_warnings({"provider": provider})
    text = "\n".join(warns)
    assert "external CLI tool loop" in text
    assert "NATIVE tool loop" not in text
    assert "fs_jail settings do not constrain" in text
    if provider == "local-cli":
        assert "may have unrestricted host access" in text
    else:
        assert "CLI's sandbox/permission policy" in text


def test_gateway_warnings_respect_optins():
    cfg = {"provider": "anthropic",
           "disabled_tools": ["run_shell"], "fs_jail": True}
    assert security.gateway_warnings(cfg) == []
    cfg2 = {"provider": "claude-cli", "allow_unattended_full": True,
            "cli_access": "full"}
    assert any("unattended" in w for w in security.gateway_warnings(cfg2))


def test_gateway_warns_when_raw_network_bypasses_inspected_egress():
    warns = security.gateway_warnings({
        "provider": "codex-cli",
        "cli_network_access": True,
    })
    text = "\n".join(warns)
    assert "raw network" in text
    assert "inspected egress" in text


def test_gateway_warns_when_native_egress_enforcement_is_disabled():
    warns = security.gateway_warnings({
        "provider": "anthropic",
        "disabled_tools": ["run_shell"],
        "fs_jail": True,
        "egress": {"enabled": True, "enforced": False},
    })
    text = "\n".join(warns)
    assert "egress.enforced is false" in text
    assert "raw native tools" in text


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
