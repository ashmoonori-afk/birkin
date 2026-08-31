from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

from birkin import cli
from birkin.gateway import core
from birkin.gateway import turn_router
from birkin.omo import OmoController, parse_omo_command
from birkin.omo_rpc import command_for_session
from tests.omo_gateway_support import (
    BlockingRpc,
    FailingRpc,
    FakeRpc,
    write_session,
)


def test_controller_controls_selected_session_and_rejects_missing_selection(
    tmp_path: Path,
) -> None:
    first = write_session(tmp_path, "abc12345-0000", "C:/repo/one")
    rpc = FakeRpc()
    controller = OmoController(rpc=rpc, session_roots=(tmp_path,))

    assert "abc12345-0000" in controller.handle("/omo list")
    assert (
        controller.handle("/omo use abc123") == "Selected abc12345-0000 (C:/repo/one)."
    )
    assert rpc.selected == first
    assert controller.handle("/omo send fix the test").startswith(
        "OMO prompt started in the background."
    )
    assert rpc.prompt_called.wait(timeout=1)
    assert controller.handle("/omo steer check caller") == "Steering message queued."
    assert controller.handle("/omo abort") == "Abort requested."
    assert controller.handle("/omo last") == "last reply"
    assert "abc123" in controller.handle("/omo status")
    assert "No OMO session matches" in controller.handle("/omo use missing")
    empty = OmoController(rpc=rpc, session_roots=())
    assert "Select a session first" in empty.handle("/omo send hello")
    assert rpc.prompts == ["fix the test"]
    assert rpc.steers == ["check caller"]
    assert rpc.aborted


def test_gateway_registers_authorizes_and_closes_omo(monkeypatch) -> None:
    rpc = FakeRpc()
    controller = OmoController(rpc=rpc, session_roots=())
    monkeypatch.setattr(core, "OmoController", lambda: controller)
    monkeypatch.setattr(core, "build_session", lambda cfg: object())
    gateway = core.Gateway({"channels": {"telegram": {"allowed_chat_ids": ["42"]}}})

    assert "omo" in {item["command"] for item in core.command_menu()}
    assert "omo" in core._PRIVILEGED_COMMANDS
    assert gateway.handle("telegram", "42", "/omo help").startswith(
        "OMO session control"
    )
    assert (
        gateway.handle("telegram", "99", "/omo help")
        == "OMO control is restricted to configured Telegram chat IDs."
    )
    assert gateway.handle("http", "42", "/omo help") == (
        "OMO control is restricted to configured Telegram chat IDs."
    )
    gateway.shutdown()
    assert rpc.closed


def test_telegram_gateway_lease_rejects_competing_owner_and_releases_on_shutdown(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(core.config, "birkin_home", lambda: tmp_path)
    monkeypatch.setattr(core, "build_session", lambda cfg: object())
    monkeypatch.setattr(
        core,
        "OmoController",
        lambda: OmoController(rpc=FakeRpc(), session_roots=()),
    )
    cfg = {
        "channels": {
            "telegram": {
                "enabled": True,
                "token": "1234567890:abcdefghijklmnopqrstuvwxyz",
                "allowed_chat_ids": ["42"],
            }
        }
    }
    first = core.Gateway(cfg)
    competing = None
    replacement = None

    try:
        with pytest.raises(
            RuntimeError,
            match=r"Telegram owner PID \d+ already owns bot [0-9a-f]{12}",
        ):
            competing = core.Gateway(cfg)
        first.shutdown()
        replacement = core.Gateway(cfg)
    finally:
        if competing is not None:
            competing.shutdown()
        if replacement is not None:
            replacement.shutdown()


def test_omo_gateway_routes_only_authorized_explicit_commands(monkeypatch) -> None:
    rpc = FakeRpc()
    controller = OmoController(rpc=rpc, session_roots=())
    monkeypatch.setattr(core, "OmoController", lambda: controller)
    monkeypatch.setattr(core, "build_session", lambda cfg: object())
    monkeypatch.setattr(
        turn_router,
        "run_model_turn",
        lambda *_args, **_kwargs: "ordinary Birkin turn",
    )
    gateway = core.Gateway({"channels": {"telegram": {"allowed_chat_ids": ["42"]}}})

    try:
        assert gateway._omo_command_trusted("telegram", "42") is True
        assert gateway._omo_command_trusted("telegram", "99") is False
        assert gateway._omo_command_trusted("local_http", "42") is False
        assert gateway.handle("telegram", "42", "/omo help").startswith(
            "OMO session control"
        )
        assert gateway.handle("telegram", "99", "/omo help") == (
            "OMO control is restricted to configured Telegram chat IDs."
        )
        assert gateway.handle("local_http", "42", "/omo help") == (
            "OMO control is restricted to configured Telegram chat IDs."
        )
        assert (
            gateway.handle("telegram", "42", "ordinary message")
            == "ordinary Birkin turn"
        )
        assert rpc.prompts == []
    finally:
        gateway.shutdown()


def test_gateway_diagnostics_report_owner_channel_and_omo_state(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    overlay_path = Path(__file__).parents[1] / ".birkin" / "omo_gateway.py"
    namespace = runpy.run_path(str(overlay_path), run_name="omo_gateway_test")
    gateway_main = namespace["main"]
    original_menu = core.command_menu
    original_gateway = core.Gateway
    token = "1234567890:diagnostic-secret-token"
    cfg = {
        "channels": {
            "telegram": {
                "enabled": True,
                "token": token,
                "allowed_chat_ids": ["42"],
            }
        }
    }
    monkeypatch.setattr(core.config, "birkin_home", lambda: tmp_path)
    monkeypatch.setattr(core.config, "load_config", lambda: cfg)
    monkeypatch.setattr(core, "run", lambda: 7)
    monkeypatch.setattr(sys, "argv", ["omo_gateway.py", "--diagnose"])

    try:
        exit_code = gateway_main()
    finally:
        core.command_menu = original_menu
        core.Gateway = original_gateway

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Telegram owner: unclaimed" in output
    assert "Telegram channel: enabled" in output
    assert "OMO control: enabled for 1 configured Telegram chat ID" in output
    assert "Conflict guidance:" in output
    assert token not in output


def test_cli_omo_diagnose_alias_reports_gateway_state(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    token = "1234567890:diagnostic-secret-token"
    cfg = {
        "channels": {
            "telegram": {
                "enabled": True,
                "token": token,
                "allowed_chat_ids": ["42"],
            }
        }
    }
    monkeypatch.setattr(core.config, "birkin_home", lambda: tmp_path)
    monkeypatch.setattr(core.config, "load_config", lambda: cfg)

    assert cli.main(["omo", "diagnose"]) == 0

    output = capsys.readouterr().out
    assert "Telegram owner: unclaimed" in output
    assert "Telegram channel: enabled" in output
    assert "OMO control: enabled for 1 configured Telegram chat ID" in output
    assert "Conflict guidance:" in output
    assert token not in output


def test_gateway_keeps_omo_controls_available_while_send_runs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    write_session(tmp_path, "abc12345-0000", "C:/repo/one")
    rpc = BlockingRpc()
    controller = OmoController(rpc=rpc, session_roots=(tmp_path,))
    monkeypatch.setattr(core, "OmoController", lambda: controller)
    monkeypatch.setattr(core, "build_session", lambda cfg: object())
    gateway = core.Gateway({"channels": {"telegram": {"allowed_chat_ids": ["42"]}}})

    assert gateway.handle("telegram", "42", "/omo use abc123").startswith("Selected")

    try:
        assert gateway.handle("telegram", "42", "/omo send fix the test") == (
            "OMO prompt started in the background. "
            "Use /omo status, /omo steer, /omo abort, or /omo last."
        )
        assert rpc.prompt_started.wait(timeout=1)
        assert (
            gateway.handle("telegram", "42", "/omo steer check caller")
            == "Steering message queued."
        )
        assert gateway.handle("telegram", "42", "/omo abort") == "Abort requested."
    finally:
        rpc.release_prompt.set()
        assert rpc.prompt_finished.wait(timeout=1)
        gateway.shutdown()

    assert rpc.steers == ["check caller"]
    assert rpc.aborted


def test_controller_rejects_conflicting_operations_while_send_runs(
    tmp_path: Path,
) -> None:
    write_session(tmp_path, "abc12345-0000", "C:/repo/one")
    write_session(tmp_path, "def67890-0000", "C:/repo/two")
    rpc = BlockingRpc()
    controller = OmoController(rpc=rpc, session_roots=(tmp_path,))

    assert controller.handle("/omo use abc123").startswith("Selected")
    assert controller.handle("/omo send first").startswith(
        "OMO prompt started in the background."
    )
    try:
        assert rpc.prompt_started.wait(timeout=1)
        assert controller.handle("/omo send second") == (
            "An OMO prompt is already running."
        )
        assert controller.handle("/omo use def678") == (
            "Wait for the running OMO prompt to finish before switching sessions."
        )
    finally:
        rpc.release_prompt.set()
        assert rpc.prompt_finished.wait(timeout=1)
        controller.close()


def test_controller_reports_background_prompt_failure(tmp_path: Path) -> None:
    write_session(tmp_path, "abc12345-0000", "C:/repo/one")
    rpc = FailingRpc()
    controller = OmoController(rpc=rpc, session_roots=(tmp_path,))

    assert controller.handle("/omo use abc123").startswith("Selected")
    assert controller.handle("/omo send fail").startswith(
        "OMO prompt started in the background."
    )
    assert rpc.prompt_failed.wait(timeout=1)
    prompt_thread = controller._prompt_thread
    assert prompt_thread is not None
    prompt_thread.join(timeout=1)
    assert not prompt_thread.is_alive()
    assert "Last prompt error: background prompt failed" in controller.handle(
        "/omo status"
    )
    controller.close()


def test_parser_and_session_command_preserve_omo_contract() -> None:
    assert parse_omo_command("/omo@BirkinBot send hello") == ("send", "hello")
    assert parse_omo_command("/other") is None
    assert command_for_session(
        ("omo", "--no-session", "--approve"), Path("C:/sessions/example.jsonl")
    ) == ("omo", "--approve", "--session", "C:\\sessions\\example.jsonl")
