"""Tool-trace tree: nesting, per-tool timing, /details verbosity."""

from __future__ import annotations

import contextlib
import io
import re

from birkin import ui


def _drive(events):
    buf = io.StringIO()
    emit = ui.make_event_printer()
    with contextlib.redirect_stdout(buf):
        for ev, pl in events:
            emit(ev, pl)
    # strip ANSI so assertions read the text
    return re.sub(r"\033\[[0-9;]*m", "", buf.getvalue())


def test_tool_end_shows_elapsed():
    out = _drive([
        ("tool_start", {"name": "read_file", "input": {}, "id": "a"}),
        ("tool_end", {"name": "read_file", "is_error": False, "content": "", "id": "a"}),
    ])
    assert re.search(r"✓ read_file · \d+\.\ds", out)


def test_subagent_nests_indentation():
    out = _drive([
        ("subagent.start", {"task": "audit"}),
        ("tool_start", {"name": "grep", "input": {}, "id": "g"}),
        ("tool_end", {"name": "grep", "is_error": False, "content": "", "id": "g"}),
        ("subagent.done", {}),
    ])
    lines = [ln for ln in out.splitlines() if "grep" in ln]
    # grep runs inside the subagent -> indented deeper than a top-level "  →".
    assert all(ln.startswith("    ") for ln in lines), lines


def test_workspace_shaped_tool_events_show_the_tool_name():
    # birkin chat receives the workspace adapter's sanitized payload.
    shaped = {"runtime_event": "tool_start", "runtime_name": "list_files",
              "progress_id": "runtime:tool:list_files"}
    out = _drive([
        ("tool_start", shaped),
        ("tool_end", {**shaped, "runtime_event": "tool_end",
                      "state": "failed"}),
    ])
    assert "→ list_files" in out and "✗ list_files" in out
    assert "None" not in out and "{}" not in out


def test_child_tool_events_nest_under_the_subagent():
    out = _drive([
        ("subagent.start", {"task": "audit", "id": "r1"}),
        ("subagent.tool_start", {"name": "grep", "input": {}, "id": "g"}),
        ("subagent.tool_end", {"name": "grep", "is_error": False,
                               "content": "", "id": "g"}),
        ("subagent.done", {"id": "r1"}),
        ("tool_start", {"name": "read_file", "input": {}, "id": "z"}),
    ])
    grep = [ln for ln in out.splitlines() if "grep" in ln]
    assert len(grep) == 2 and all(ln.startswith("    ") for ln in grep), grep
    assert "하위 에이전트: audit" in out and "하위 에이전트 완료" in out
    (after,) = [ln for ln in out.splitlines() if "read_file" in ln]
    assert after.startswith("  →")


def test_failed_subagent_reads_as_a_failure_not_done():
    # run_subagent marks a failed run with is_error, moirai with its error
    # text, and the workspace adapter with state="failed" plus its summary.
    out = _drive([
        ("subagent.start", {"task": "[worker-1] 표 합계 검증"}),
        ("subagent.done", {"error": "RateLimitError: 429"}),
        ("subagent.start", {"task": "보고서 초안", "id": "r1"}),
        ("subagent.done", {"chars": 0, "id": "r1", "is_error": True}),
        ("subagent.done", {"runtime_event": "subagent.done", "state": "failed",
                           "summary": "리서처 에이전트가 작업을 마치지 못했습니다."}),
    ])
    done = [ln for ln in out.splitlines() if "⇲" not in ln and ln.strip()]
    assert len(done) == 3 and all("✗" in ln for ln in done), done
    assert "하위 에이전트 완료" not in out
    assert out.count("하위 에이전트가 작업을 마치지 못했습니다") == 2
    assert "리서처 에이전트가 작업을 마치지 못했습니다." in out
    assert "RateLimitError" not in out


def test_depth_returns_to_zero_after_subagent():
    out = _drive([
        ("subagent.start", {"task": "x"}),
        ("subagent.done", {}),
        ("tool_start", {"name": "read_file", "input": {}, "id": "z"}),
        ("tool_end", {"name": "read_file", "is_error": False, "content": "", "id": "z"}),
    ])
    after = [ln for ln in out.splitlines() if "read_file" in ln]
    assert all(ln.startswith("  →") or ln.startswith("  ✓") for ln in after)


def test_error_mark_on_failure():
    out = _drive([
        ("tool_start", {"name": "run_shell", "input": {}, "id": "e"}),
        ("tool_end", {"name": "run_shell", "is_error": True, "content": "boom", "id": "e"}),
    ])
    assert "✗ run_shell" in out


def test_details_off_hides_result_snippet():
    ui.set_details(False)
    out = _drive([
        ("tool_start", {"name": "run_shell", "input": {"command": "ls"}, "id": "d"}),
        ("tool_end", {"name": "run_shell", "is_error": False,
                      "content": "a really long output here", "id": "d"}),
    ])
    assert "↳" not in out


def test_details_on_shows_result_snippet():
    ui.set_details(True)
    try:
        out = _drive([
            ("tool_start", {"name": "run_shell", "input": {"command": "ls"}, "id": "d"}),
            ("tool_end", {"name": "run_shell", "is_error": False,
                          "content": "line1\nline2", "id": "d"}),
        ])
        assert "↳" in out and "line1" in out
    finally:
        ui.set_details(False)


def test_details_toggle_default_flips():
    ui.set_details(False)
    assert ui.set_details(not ui.details_on()) is True
    assert ui.set_details(not ui.details_on()) is False


def test_timing_is_correct_under_parallel_ids():
    # Two same-named calls interleaved: keyed by id, each gets its own timing.
    out = _drive([
        ("tool_start", {"name": "web_fetch", "input": {}, "id": "1"}),
        ("tool_start", {"name": "web_fetch", "input": {}, "id": "2"}),
        ("tool_end", {"name": "web_fetch", "is_error": False, "content": "", "id": "1"}),
        ("tool_end", {"name": "web_fetch", "is_error": False, "content": "", "id": "2"}),
    ])
    assert out.count("✓ web_fetch") == 2
    assert len(re.findall(r"✓ web_fetch · \d+\.\ds", out)) == 2


def test_memory_activity_line_still_shown():
    out = _drive([
        ("tool_end", {"name": "memory_search", "is_error": False,
                      "content": "- [[x]]: s\n- [[y]]: s", "id": "m"}),
    ])
    assert "recalled 2 note(s)" in out
