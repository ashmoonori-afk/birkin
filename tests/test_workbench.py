"""Workbench surface: attention-first overview, pure rendering, authority.

The renderer is a pure function over a snapshot dict (same discipline as
dash.py) so every layout claim here runs without a terminal. Contracts:
attention ordering, responsive layouts at the four contract sizes, guardrail
fields on the approval screen, NO_COLOR cleanliness, and the rule that the
UI only requests approval resolution from the Python authority — it never
flips state on its own.
"""
from __future__ import annotations

import re

from birkin import uistate, workbench
from birkin.ui import cell_width

ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

SNAP = {
    "header": {"model": "claude-sonnet-4-5", "provider": "claude",
               "daemon_up": True, "daemon_known": True, "daemon_stale": False},
    "approvals": [
        {"id": "aaaa11112222", "category": "shell", "origin": "morpheus",
         "title": "빌드 정리 명령 실행", "status": "pending",
         "description": "rm -rf build/", "payload": {"command": "rm -rf build/"},
         "created": "2026-08-13T00:00:00+00:00",
         "expires_at": "2126-01-01T00:00:00+00:00"},
        {"id": "bbbb11112222", "category": "cron", "origin": "user",
         "title": "아침 브리핑 크론 등록", "status": "error",
         "description": "cron register", "payload": {},
         "created": "2026-08-13T00:00:00+00:00"},
    ],
    "sessions": [
        {"title": "국내주식 리서치", "age": "3분전", "path": "x.json"},
    ],
    "agents": [
        {"id": "cccc", "task": "관제 리포트", "status": "running", "depth": 0},
        {"id": "dddd", "task": "정리 워커", "status": "done", "depth": 1},
    ],
    "cron": [
        {"name": "nightly", "schedule": "매일 03:00", "next": "2026-08-14 03:00",
         "enabled": True, "id": "j1"},
    ],
    "goal": {"status": "active", "objective": "리서치 완료"},
    "errors": {},
}

SIZES = ((60, 20), (80, 24), (120, 30), (160, 40))


def _fresh_state() -> dict:
    return workbench.initial_state()


# -- ledger: the attention queue --------------------------------------------

def test_ledger_orders_by_attention_not_by_domain():
    items = workbench.build_ledger(SNAP)
    states = [it["view"].state for it in items]
    assert states[0] == "waiting_human"          # pending approval on top
    assert states[1] == "failed"                 # failed approval next
    assert "running" in states
    # resolved/idle work sits below anything alive or blocked
    assert states.index("running") < len(states) - 1 or len(states) == 3


def test_ledger_rows_carry_kind_and_id():
    items = workbench.build_ledger(SNAP)
    kinds = {it["kind"] for it in items}
    assert "approval" in kinds and "agent" in kinds
    assert all(it.get("title") for it in items)


# -- responsive layout at the four contract sizes ---------------------------

def test_render_fits_every_contract_size():
    for cols, rows in SIZES:
        lines = workbench.render(SNAP, _fresh_state(), (cols, rows),
                                 color=False)
        assert len(lines) <= rows, (cols, rows, len(lines))
        for ln in lines:
            assert cell_width(ANSI.sub("", ln)) <= cols, (cols, repr(ln))


def test_narrow_drops_the_rail_for_a_switcher():
    lines = workbench.render(SNAP, _fresh_state(), (60, 20), color=False)
    text = "\n".join(lines)
    assert "│" not in text                       # no side-by-side panes
    assert "대기 1" in text                      # switcher summarizes attention


def test_wide_shows_rail_and_bench_side_by_side():
    lines = workbench.render(SNAP, _fresh_state(), (120, 30), color=False)
    text = "\n".join(lines)
    assert "│" in text
    assert "빌드 정리 명령 실행" in text


def test_no_color_render_has_zero_escapes():
    for size in SIZES:
        for ln in workbench.render(SNAP, _fresh_state(), size, color=False):
            assert ANSI.search(ln) is None


# -- approval screen: guardrail fields --------------------------------------

def test_approval_screen_shows_guardrail_context():
    state = _fresh_state()
    state.update(screen="approval", cursor=0)
    lines = workbench.render(SNAP, state, (100, 30), color=False)
    text = "\n".join(lines)
    assert "morpheus" in text                    # 요청 주체
    assert "rm -rf build/" in text               # 실행하려는 동작
    assert "만료" in text                        # 승인 만료 시간
    assert "Python daemon" in text               # 승인 이후 실행 주체
    assert "거부 시" in text                     # 거부 결과
    assert uistate.label("waiting_human") in text


def test_approval_screen_separates_approve_from_execute():
    state = _fresh_state()
    state.update(screen="approval", cursor=0, note="요청 전송 중")
    lines = workbench.render(SNAP, state, (100, 30), color=False)
    text = "\n".join(lines)
    # requesting is never rendered as done
    assert "요청 전송 중" in text
    assert uistate.label("completed") not in text


# -- authority boundary -----------------------------------------------------

def test_resolve_approval_routes_through_python_authority(monkeypatch):
    calls = {}

    def fake_approve(aid, **identity):
        calls["id"] = aid
        calls["identity"] = identity
        return {"ok": True, "result": "done"}

    from birkin import approvals
    monkeypatch.setattr(approvals, "approve", fake_approve)
    out = workbench.resolve_approval("aaaa11112222", approve=True)
    assert calls["id"] == "aaaa11112222"
    assert calls["identity"] == {
        "approved_by": "human:terminal",
        "approved_via": "terminal:workbench",
    }
    assert out["ok"] is True


def test_resolve_approval_failure_is_reported_not_swallowed(monkeypatch):
    from birkin import approvals

    def boom(aid, **_identity):
        raise RuntimeError("daemon unreachable")

    monkeypatch.setattr(approvals, "reject", boom)
    out = workbench.resolve_approval("aaaa11112222", approve=False)
    assert out["ok"] is False
    assert "daemon unreachable" in out["error"]


def test_render_documents_terminal_approval_and_refresh_keys():
    frame = "\n".join(
        workbench.render(SNAP, _fresh_state(), (120, 30), color=False),
    )

    assert "a 승인" in frame
    assert "r 거부" in frame
    assert "f 새로고침" in frame


def test_bracketed_paste_is_consumed_as_one_inert_key():
    from birkin import dash

    stream = bytearray(
        b"\x1b[200~a r "
        + "한글 입력".encode()
        + b"\x1b[201~"
    )

    def ready(*_args):
        return ([1], [], []) if stream else ([], [], [])

    def read_byte(_fd, _size):
        return bytes([stream.pop(0)])

    assert dash._read_posix_key(
        1, 0.1, select_fn=ready, read_fn=read_byte,
    ) == "paste"
    assert not stream


def test_workbench_never_imports_execution_machinery():
    import birkin.workbench as module
    src = open(module.__file__, encoding="utf-8").read()
    for forbidden in ("subprocess", "os.system", "tools.shell",
                      "from .tools", "import tools"):
        assert forbidden not in src, forbidden




# -- disconnected daemon is explicit ----------------------------------------

def test_daemon_down_renders_disconnected_guidance():
    snap = dict(SNAP, header=dict(SNAP["header"], daemon_up=False,
                                  daemon_known=True))
    lines = workbench.render(snap, _fresh_state(), (100, 30), color=False)
    text = "\n".join(lines)
    assert "데몬" in text
