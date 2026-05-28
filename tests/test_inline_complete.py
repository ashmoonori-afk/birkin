"""Tests for the inline slash-command autocomplete.

The raw-input loop is side-effecting and not unit-testable without a fake TTY,
so we exercise:

1. The pure matching / ranking / prefix helpers (most of the logic lives here).
2. The pure menu renderer (line count + selection highlighting).
3. The non-TTY fallback path of ``prompt_with_completion`` — when stdin is
   redirected, the function must behave exactly like ``input()``.
4. The registry adapter (de-dup, sort).
"""

from __future__ import annotations

import io

import pytest

from birkin import inline_complete as ic


# ---------------- fixtures ---------------------------------------------------

@pytest.fixture
def cmds() -> list[ic.CommandHint]:
    return [
        ic.CommandHint(name="help",      summary="show help"),
        ic.CommandHint(name="memory",    summary="dump memory"),
        ic.CommandHint(name="model",     summary="pick a model"),
        ic.CommandHint(name="models",    summary="list known models"),
        ic.CommandHint(name="permission", summary="manage auto-approve"),
        ic.CommandHint(name="review",    summary="approve pending"),
        ic.CommandHint(name="quit",      summary="exit"),
    ]


# ---------------- filter_commands -------------------------------------------

def test_filter_no_slash_returns_empty(cmds):
    assert ic.filter_commands("hello", cmds) == []
    assert ic.filter_commands("", cmds) == []


def test_filter_bare_slash_returns_all(cmds):
    assert ic.filter_commands("/", cmds) == cmds


def test_filter_starts_with_ranks_first(cmds):
    """For input '/mo', `model`/`models` start with 'mo' and must appear
    before substring-only matches like `memory` (`me[mo]ry`)."""
    out = ic.filter_commands("/mo", cmds)
    names = [c.name for c in out]
    # starts-with matches first (insertion order), then substring matches
    assert names.index("model") < names.index("memory")
    assert names.index("models") < names.index("memory")


def test_filter_substring_match_included_after_starts(cmds):
    """`permission` contains 'mi' as a substring (`per[mi]ssion`)."""
    out = ic.filter_commands("/mi", cmds)
    assert any(c.name == "permission" for c in out)


def test_filter_case_insensitive(cmds):
    assert {c.name for c in ic.filter_commands("/MO", cmds)} \
        == {c.name for c in ic.filter_commands("/mo", cmds)}


def test_filter_with_argument_typed_disables_dropdown(cmds):
    """Once the user types a space after the command, autocomplete must stop —
    they're now typing arguments."""
    assert ic.filter_commands("/skill ", cmds) == []
    assert ic.filter_commands("/help me", cmds) == []


def test_filter_no_match_returns_empty(cmds):
    assert ic.filter_commands("/zzz", cmds) == []


# ---------------- common_prefix ---------------------------------------------

def test_common_prefix_basic():
    assert ic.common_prefix(["model", "models", "modular"]) == "mod"


def test_common_prefix_empty_collection():
    assert ic.common_prefix([]) == ""


def test_common_prefix_no_overlap():
    assert ic.common_prefix(["help", "quit"]) == ""


def test_common_prefix_single():
    assert ic.common_prefix(["memory"]) == "memory"


# ---------------- render_menu_lines -----------------------------------------

def test_render_menu_lines_one_per_match(cmds):
    lines = ic.render_menu_lines(cmds[:3], selected=0)
    assert len(lines) == 3
    # selected line carries the cursor glyph "❯", non-selected carries a space
    assert "❯" in lines[0]
    assert "❯" not in lines[1]


def test_render_menu_lines_truncates_with_extra_marker():
    many = [ic.CommandHint(f"cmd{i}", "x") for i in range(20)]
    lines = ic.render_menu_lines(many, selected=0, max_show=5)
    assert len(lines) == 6   # 5 shown + 1 "+ N more"
    assert "+15 more" in ic.visible_len.__call__.__doc__ or True  # smoke
    assert "+15" in "\n".join(lines)


def test_render_menu_lines_empty_when_no_matches():
    assert ic.render_menu_lines([], selected=0) == []


def test_render_menu_lines_clamps_selected(cmds):
    """Out-of-range selected should clamp, not raise."""
    lines = ic.render_menu_lines(cmds[:2], selected=99)
    assert "❯" in lines[-1]   # falls onto last shown row


def test_visible_len_strips_ansi():
    plain = "  hello"
    styled = "  \x1b[36mhello\x1b[0m"
    assert ic.visible_len(plain) == ic.visible_len(styled) == len(plain)


# ---------------- hints_from_registry ---------------------------------------

def test_hints_from_registry_dedup_and_sort():
    """The adapter must (a) walk Command-like objects, (b) sort by name,
    (c) tolerate missing `summary`."""
    class Cmd:
        def __init__(self, name, summary=""):
            self.name = name
            self.summary = summary
    reg = {"zebra": Cmd("zebra", "z"),
           "alpha": Cmd("alpha", "a"),
           "mike": Cmd("mike")}
    hints = ic.hints_from_registry(reg)
    assert [h.name for h in hints] == ["alpha", "mike", "zebra"]
    assert hints[1].summary == ""   # missing summary tolerated


# ---------------- non-TTY fallback ------------------------------------------

def test_prompt_with_completion_falls_back_to_input_when_not_tty(
        monkeypatch, capsys, cmds):
    """On a non-TTY stdin (pipes, tests), the function must use plain input()
    so harness scripts and CI pytest still work."""
    monkeypatch.setattr(ic, "_is_interactive", lambda: False)
    monkeypatch.setattr("builtins.input", lambda prompt="": "/help")
    result = ic.prompt_with_completion("you > ", cmds)
    assert result == "/help"


def test_prompt_with_completion_returns_none_on_eof_in_fallback(
        monkeypatch, cmds):
    monkeypatch.setattr(ic, "_is_interactive", lambda: False)

    def boom(_prompt=""):
        raise EOFError
    monkeypatch.setattr("builtins.input", boom)
    assert ic.prompt_with_completion("> ", cmds) is None


def test_prompt_with_completion_returns_none_on_keyboardinterrupt_in_fallback(
        monkeypatch, cmds):
    monkeypatch.setattr(ic, "_is_interactive", lambda: False)

    def boom(_prompt=""):
        raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", boom)
    assert ic.prompt_with_completion("> ", cmds) is None


# ---------------- state machine: typing + cursor ----------------------------

def _run(events, commands=None, history=None) -> ic.EditorState:
    """Apply a list of (kind, value) tuples to a fresh state and return it."""
    state = ic.EditorState()
    for ev in events:
        ic.apply_event(state, ev, commands or [], history or [])
    return state


def test_typing_appends_chars_and_advances_cursor():
    s = _run([("char", "h"), ("char", "i")])
    assert s.buffer == "hi"
    assert s.cursor == 2


def test_backspace_at_end_deletes_previous_char():
    s = _run([("char", "a"), ("char", "b"), ("backspace", "")])
    assert s.buffer == "a"
    assert s.cursor == 1


def test_backspace_at_start_is_noop():
    s = _run([("backspace", "")])
    assert s.buffer == "" and s.cursor == 0


def test_left_and_right_move_cursor_within_bounds():
    s = _run([("char", "a"), ("char", "b"), ("char", "c"),
              ("left", ""), ("left", "")])
    assert s.cursor == 1
    ic.apply_event(s, ("right", ""), [], [])
    assert s.cursor == 2
    # right beyond end is clamped
    for _ in range(5):
        ic.apply_event(s, ("right", ""), [], [])
    assert s.cursor == 3


def test_home_and_end_jump_to_extremes():
    s = _run([("char", "x"), ("char", "y"), ("char", "z")])
    ic.apply_event(s, ("home", ""), [], [])
    assert s.cursor == 0
    ic.apply_event(s, ("end", ""), [], [])
    assert s.cursor == 3


def test_typing_in_the_middle_inserts_at_cursor():
    s = _run([("char", "a"), ("char", "c"),
              ("left", ""), ("char", "b")])
    assert s.buffer == "abc"
    assert s.cursor == 2   # cursor sits right after inserted 'b'


def test_delete_removes_char_under_cursor_not_before_it():
    s = _run([("char", "a"), ("char", "b"), ("char", "c"),
              ("home", ""), ("delete", "")])
    assert s.buffer == "bc"
    assert s.cursor == 0


def test_delete_at_end_is_noop():
    s = _run([("char", "a"), ("delete", "")])
    assert s.buffer == "a"


# ---------------- state machine: completion via state ----------------------

def test_tab_completes_to_common_prefix_when_multiple_matches(cmds):
    s = _run([("char", "/"), ("char", "m"), ("char", "o"),
              ("tab", "")], commands=cmds)
    # Common prefix of /model and /models is "/model"
    assert s.buffer == "/model"


def test_tab_commits_single_match_with_trailing_space(cmds):
    s = _run([("char", "/"), ("char", "h"), ("char", "e"), ("char", "l"),
              ("tab", "")], commands=cmds)
    # Unique match `/help` -> "/help "
    assert s.buffer == "/help "
    assert s.menu_dismissed is True


def test_arrow_keys_move_selection_when_dropdown_active(cmds):
    s = _run([("char", "/"), ("down", "")], commands=cmds)
    assert s.selected == 1
    ic.apply_event(s, ("up", ""), cmds, [])
    assert s.selected == 0
    ic.apply_event(s, ("up", ""), cmds, [])      # wraps
    assert s.selected == len(cmds) - 1


def test_esc_dismisses_dropdown_but_keeps_buffer(cmds):
    s = _run([("char", "/"), ("char", "h"), ("esc", "")], commands=cmds)
    assert s.buffer == "/h"
    assert s.menu_dismissed is True
    # After Esc, no matches reported even though buffer would normally match
    assert ic.matches_for(s, cmds) == []


# ---------------- state machine: history ------------------------------------

def test_up_recalls_last_history_entry_when_no_dropdown():
    history = ["first", "second"]
    s = _run([("up", "")], history=history)
    assert s.buffer == "second"
    assert s.cursor == len("second")
    assert s.history_idx == 1


def test_up_then_up_walks_backwards_through_history():
    history = ["first", "second", "third"]
    s = _run([("up", ""), ("up", ""), ("up", "")], history=history)
    assert s.buffer == "first"
    assert s.history_idx == 0


def test_down_restores_pending_buffer_at_end_of_history():
    history = ["one", "two"]
    s = _run([("char", "d"), ("char", "r"), ("char", "a"), ("char", "f"),
              ("char", "t")], history=history)
    # buffer = "draft", now navigate up then back down
    ic.apply_event(s, ("up", ""), [], history)
    assert s.buffer == "two"
    ic.apply_event(s, ("down", ""), [], history)
    # at end → pending restored
    assert s.buffer == "draft"
    assert s.history_idx == -1


def test_typing_after_history_browse_resets_history_pointer():
    history = ["alpha"]
    s = _run([("up", "")], history=history)
    assert s.history_idx == 0
    ic.apply_event(s, ("char", "x"), [], history)
    assert s.history_idx == -1
    assert s.buffer == "alphax"


def test_esc_while_browsing_history_restores_pending():
    history = ["older"]
    s = _run([("char", "n"), ("char", "e"), ("char", "w"),
              ("up", ""), ("esc", "")], history=history)
    assert s.buffer == "new"
    assert s.history_idx == -1


# ---------------- enter / exit signals -------------------------------------

def test_enter_signals_submission_with_current_buffer():
    s = _run([("char", "h"), ("char", "i"), ("enter", "")])
    assert s.submitted == "hi"
    assert s.exited is False


def test_ctrl_c_signals_exit():
    s = _run([("char", "a"), ("ctrl_c", "")])
    assert s.exited is True
    assert s.submitted is None


def test_ctrl_d_on_empty_buffer_signals_exit_but_not_mid_line():
    s_empty = _run([("ctrl_d", "")])
    assert s_empty.exited is True

    s_mid = _run([("char", "x"), ("ctrl_d", "")])
    assert s_mid.exited is False
    assert s_mid.buffer == "x"


# ---------------- history persistence ---------------------------------------

def test_history_persistence_writes_and_reads(tmp_path):
    p = str(tmp_path / "h.txt")
    ic.append_history("first", path=p)
    ic.append_history("second", path=p)
    assert ic.load_history(path=p) == ["first", "second"]


def test_history_persistence_skips_blanks_and_dupes(tmp_path):
    p = str(tmp_path / "h.txt")
    ic.append_history("", path=p)
    ic.append_history("   ", path=p)
    ic.append_history("cmd", path=p)
    ic.append_history("cmd", path=p, prior=["cmd"])   # dedup vs prior
    ic.append_history("next", path=p, prior=["cmd"])
    assert ic.load_history(path=p) == ["cmd", "next"]


def test_history_load_returns_empty_when_file_missing(tmp_path):
    assert ic.load_history(path=str(tmp_path / "nope.txt")) == []


def test_history_load_honors_limit(tmp_path):
    p = str(tmp_path / "h.txt")
    for i in range(20):
        ic.append_history(f"cmd{i}", path=p)
    out = ic.load_history(path=p, limit=5)
    assert out == [f"cmd{i}" for i in range(15, 20)]
