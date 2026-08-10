"""An approved hard task must be visible in chat while it executes.

The hard-task pattern announces every step through m.phase(). But an approved
moirai proposal executes synchronously inside the telegram callback handler,
and nothing on that path carries the events: run_approved drops on_event,
execute_action has no way to pass one, and the callback spins no pinger. So a
user who approves a hard task gets minutes of silence -- the exact failure the
progress work exists to remove.

The chain under test: telegram callback -> gateway.execute_claimed_action ->
approvals.execute_claimed -> execute_action -> trigger.run_approved ->
engine.run_script(on_event=...) -> moirai.phase -> progress holder ->
heartbeat_text.
"""

from __future__ import annotations

import types

from birkin import approvals
from birkin.gateway import core as gateway_core
from birkin.gateway.channels import telegram as tg
from birkin.moirai import trigger


def _stub_engine(monkeypatch, phases=("할 일 1/3: 검색",)):
    from birkin.moirai import cli as moirai_cli
    from birkin.moirai import engine

    monkeypatch.setattr(moirai_cli, "resolve_script_path", lambda name: name)
    monkeypatch.setattr(engine, "load_script",
                        lambda path: types.SimpleNamespace(name="hard-task"))

    def fake_run(script, args=None, on_event=None, **kwargs):
        if on_event is not None:
            for title in phases:
                on_event("moirai.phase", {"title": title})
        return {"status": "ok", "agents": 0, "seconds": 0, "run_id": "r1"}

    monkeypatch.setattr(engine, "run_script", fake_run)


class TestTheExecutorForwardsEvents:
    def test_run_approved_hands_on_event_to_the_engine(self, monkeypatch) -> None:
        _stub_engine(monkeypatch)
        events: list[str] = []
        out = trigger.run_approved({"script": "hard-task", "task": "x"},
                                   on_event=lambda e, p: events.append(e))
        assert "moirai.phase" in events
        assert "ok" in out

    def test_run_approved_without_a_listener_still_works(self, monkeypatch) -> None:
        _stub_engine(monkeypatch)
        assert "ok" in trigger.run_approved({"script": "hard-task", "task": "x"})

    def test_execute_action_moirai_branch_forwards(self, monkeypatch) -> None:
        _stub_engine(monkeypatch)
        events: list[str] = []
        approvals.execute_action("moirai", {"script": "hard-task", "task": "x"},
                                 on_event=lambda e, p: events.append(e))
        assert events == ["moirai.phase"]

    def test_execute_claimed_forwards(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
        _stub_engine(monkeypatch)
        rec = approvals.propose(category="moirai", title="t", description="d",
                                payload={"script": "hard-task", "task": "x"},
                                cfg={})
        approvals.claim(rec["id"])
        events: list[str] = []
        out = approvals.execute_claimed(rec["id"],
                                        on_event=lambda e, p: events.append(e))
        assert isinstance(out, dict)
        assert "moirai.phase" in events


class TestGatewayMapsPhaseIntoProgress:
    def test_a_phase_event_lands_in_the_holder(self, monkeypatch,
                                               tmp_path) -> None:
        monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))

        def fake_claimed(aid, on_event=None):
            if on_event is not None:
                on_event("moirai.phase", {"title": "할 일 2/5: 정리"})
                on_event("moirai.phase", {"title": "할 일 3/5: 검증"})
            return {"ok": True, "result": "done"}

        import birkin.approvals as approvals_module
        monkeypatch.setattr(approvals_module, "execute_claimed", fake_claimed)
        holder: dict = {}
        g = gateway_core.Gateway.__new__(gateway_core.Gateway)
        g.execute_claimed_action("aid1", on_progress=holder.update)
        assert holder.get("phase") == "할 일 3/5: 검증"
        assert holder.get("activity") == 2

    def test_without_a_callback_nothing_changes(self, monkeypatch,
                                                tmp_path) -> None:
        monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))

        def fake_claimed(aid, on_event=None):
            assert on_event is None
            return {"ok": True, "result": "done"}

        import birkin.approvals as approvals_module
        monkeypatch.setattr(approvals_module, "execute_claimed", fake_claimed)
        g = gateway_core.Gateway.__new__(gateway_core.Gateway)
        g.execute_claimed_action("aid1")


class TestTelegramWrapsApprovalExecution:
    class _GatewayNew:
        def execute_claimed_action(self, aid, on_progress=None):
            if on_progress is not None:
                on_progress({"phase": "할 일 1/2: 자료", "activity": 1})
            return "ok-new"

    class _GatewayOld:
        """The shape every existing test fake has: no on_progress at all."""

        def execute_claimed_action(self, aid):
            return "ok-old"

    def _channel(self, monkeypatch):
        ch = tg.TelegramChannel.__new__(tg.TelegramChannel)
        monkeypatch.setattr(ch, "_keep_typing",
                            lambda chat_id, stop, *a, **k: stop.wait(),
                            raising=False)
        return ch

    def test_a_progress_capable_gateway_feeds_the_holder(self,
                                                         monkeypatch) -> None:
        ch = self._channel(monkeypatch)
        out = tg.execute_claimed_with_progress(self._GatewayNew(), ch,
                                               "42", "aid")
        assert out == "ok-new"
        assert ch._progress["42"].get("phase") == "할 일 1/2: 자료"

    def test_an_old_gateway_is_not_broken(self, monkeypatch) -> None:
        ch = self._channel(monkeypatch)
        assert tg.execute_claimed_with_progress(self._GatewayOld(), ch,
                                                "42", "aid") == "ok-old"


class TestHeartbeatRendersThePhase:
    def test_the_phase_appears_in_the_line(self) -> None:
        line = tg.heartbeat_text(3, {"phase": "할 일 2/5: 자료 정리",
                                     "activity": 2})
        assert "할 일 2/5" in line

    def test_no_phase_reads_like_before(self) -> None:
        line = tg.heartbeat_text(3, {"activity": 2, "streamed": 0,
                                     "last_kind": "command_execution"})
        assert "할 일" not in line
        assert "3" in line
