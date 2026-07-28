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


# ---------------- long inputs / paste batching ------------------------------

def test_multichar_char_event_inserts_atomically():
    """A single ``("char", text)`` event inserts the whole string at the
    cursor — this is the path a paste batch arrives on."""
    s = ic.EditorState()
    ic.apply_event(s, ("char", "hello world"), [], [])
    assert s.buffer == "hello world"
    assert s.cursor == 11


def test_5000_char_paste_event_is_accepted_without_truncation():
    """Smoke test for the user requirement: 5000+ characters must be storable
    in the buffer in a single event."""
    big = "x" * 5000
    s = ic.EditorState()
    ic.apply_event(s, ("char", big), [], [])
    assert len(s.buffer) == 5000
    assert s.cursor == 5000


def test_paste_in_the_middle_of_existing_text():
    s = ic.EditorState()
    ic.apply_event(s, ("char", "ab"), [], [])
    ic.apply_event(s, ("left", ""), [], [])    # cursor between a and b
    ic.apply_event(s, ("char", "XYZ"), [], [])
    assert s.buffer == "aXYZb"
    assert s.cursor == 4   # right after the pasted XYZ


# ---------------- horizontal scroll (compute_view) --------------------------

def test_compute_view_no_scroll_when_buffer_fits():
    assert ic.compute_view(buffer_len=10, cursor=5, content_width=80) == (0, 10)


def test_compute_view_zero_width_returns_empty_window():
    """Defensive: width 0 or negative shouldn't blow up — return (0, len)."""
    assert ic.compute_view(buffer_len=100, cursor=50, content_width=0) == (0, 100)


def test_compute_view_keeps_cursor_visible_at_end():
    s, e = ic.compute_view(buffer_len=200, cursor=200, content_width=80)
    assert e == 200
    assert s <= 200 <= e
    assert e - s == 80


def test_compute_view_keeps_cursor_visible_at_start():
    assert ic.compute_view(buffer_len=200, cursor=0, content_width=80) == (0, 80)


def test_compute_view_scrolls_with_cursor_in_the_middle():
    s, e = ic.compute_view(buffer_len=500, cursor=100, content_width=80)
    # cursor must lie inside the window
    assert s <= 100 <= e
    # window is exactly content_width wide (still within buffer bounds)
    assert e - s == 80


def test_compute_view_does_not_exceed_buffer():
    """View end is clamped to buffer length even near the right edge."""
    _, e = ic.compute_view(buffer_len=200, cursor=199, content_width=80)
    assert e == 200


# ---------------- multiline editing -----------------------------------------

def test_newline_event_inserts_linebreak_at_cursor():
    s = _run([("char", "a"), ("newline", ""), ("char", "b")])
    assert s.buffer == "a\nb"
    assert s.cursor == 3


def test_newline_then_enter_submits_full_multiline_buffer():
    s = _run([("char", "first"), ("newline", ""),
              ("char", "second"), ("enter", "")])
    assert s.submitted == "first\nsecond"
    assert s.exited is False


def test_paste_preserves_newlines_verbatim():
    """A multi-line paste arrives as one ``("char", text)`` event from the
    raw reader; apply_event must keep ``\\n`` in the buffer (not strip or
    submit on the first newline)."""
    s = _run([("char", "line one\nline two\nline three")])
    assert s.buffer == "line one\nline two\nline three"
    assert s.cursor == len(s.buffer)
    assert s.submitted is None


def test_cursor_row_col_basic():
    assert ic.cursor_row_col("hello", 3) == (0, 3)
    assert ic.cursor_row_col("hello\nworld", 8) == (1, 2)
    assert ic.cursor_row_col("a\nb\nc", 5) == (2, 1)


def test_up_arrow_moves_between_lines_in_multiline_buffer():
    # Buffer: "hello\nworld"; cursor parked at "wor|ld" -> (1, 3)
    s = ic.EditorState(buffer="hello\nworld", cursor=9)
    ic.apply_event(s, ("up", ""), [], [])
    # Same column on the previous line → "hel|lo" → cursor at index 3
    assert s.cursor == 3
    assert ic.cursor_row_col(s.buffer, s.cursor) == (0, 3)


def test_up_arrow_clamps_to_shorter_previous_line():
    # First line shorter than second; cursor at end of second line should
    # clamp to end of first.
    s = ic.EditorState(buffer="hi\nworld", cursor=8)   # at end of "world"
    ic.apply_event(s, ("up", ""), [], [])
    # Previous line "hi" has length 2; cursor clamps to col 2 → index 2
    assert s.cursor == 2


def test_down_arrow_clamps_to_shorter_next_line():
    s = ic.EditorState(buffer="world\nhi", cursor=5)   # at end of "world"
    ic.apply_event(s, ("down", ""), [], [])
    # Next line "hi" length 2; cursor clamps to col 2 → index 8
    assert s.cursor == len("world\nhi")


def test_up_arrow_on_first_line_does_not_clobber_buffer():
    """At the top line, ↑ in multi-line mode is a no-op (NOT a history
    recall — multi-line drafts must be preserved)."""
    s = ic.EditorState(buffer="first\nsecond", cursor=3)
    ic.apply_event(s, ("up", ""), [], ["older"])
    # Buffer untouched; cursor unchanged; not browsing history.
    assert s.buffer == "first\nsecond"
    assert s.cursor == 3
    assert s.history_idx == -1


def test_single_line_buffer_still_uses_history_on_up():
    """Sanity: the multi-line ↑ path must not break single-line history."""
    s = ic.EditorState(buffer="draft", cursor=5)
    ic.apply_event(s, ("up", ""), [], ["old"])
    assert s.buffer == "old"
    assert s.history_idx == 0


def test_kitty_modified_enter_regex_matches_all_modifier_combinations():
    """The Kitty Keyboard Protocol encodes Shift+Enter / Ctrl+Enter / etc.
    as ``\\x1b[13;<mod>u`` where ``<mod>`` is 2..16 depending on which
    modifiers are held. Every such variant must be recognized as the
    multiline-newline trigger."""
    for mod in (2, 3, 4, 5, 6, 7, 8, 16):
        assert ic._KITTY_MOD_ENTER_RE.match(f"13;{mod}u".encode())


def test_kitty_modified_enter_regex_rejects_plain_enter_encoding():
    """``13;1u`` (no modifier) should NOT be treated as newline — that's
    just plain Enter rendered through the protocol, which should still
    submit. In practice un-modified Enter doesn't come through this path
    at all, but the regex must still refuse it defensively."""
    assert not ic._KITTY_MOD_ENTER_RE.match(b"13;1u")
    assert not ic._KITTY_MOD_ENTER_RE.match(b"27;2;13u")   # other CSI u keys
    assert not ic._KITTY_MOD_ENTER_RE.match(b"A")          # plain arrow Up


def test_kitty_protocol_constants_are_well_formed():
    """Sanity: enable / disable sequences must be valid CSI strings so a
    non-supporting terminal silently drops them rather than echoing the
    bytes."""
    assert ic.KITTY_ENABLE.startswith("\x1b[")
    assert ic.KITTY_ENABLE.endswith("u")
    assert ic.KITTY_DISABLE.startswith("\x1b[")
    assert ic.KITTY_DISABLE.endswith("u")


def test_dropdown_active_still_intercepts_up_in_multiline():
    """Even with a multi-line buffer, ↑ first goes to the dropdown if one
    is visible (the dropdown depends on the FIRST line not having a space,
    so this case requires the dropdown to be active *because* of the first
    token)."""
    cmd_list = [ic.CommandHint("help", "h"),
                ic.CommandHint("hello", "g")]
    # Dropdown only shows when buffer is a single token with no whitespace.
    # Here, buffer is one line `/h` plus the menu shows.
    s = ic.EditorState(buffer="/h", cursor=2)
    ic.apply_event(s, ("up", ""), cmd_list, [])
    # selection should have moved, NOT line/history
    assert s.selected == len(ic.filter_commands("/h", cmd_list)) - 1


# -- word-wise navigation + deletion (Ctrl/Alt + arrows, Ctrl-W/U/K) --------

def test_word_boundary_helpers():
    assert ic._prev_word("foo bar", 7) == 4
    assert ic._prev_word("foo bar ", 8) == 4   # skip trailing space, then word
    assert ic._prev_word("foo", 0) == 0
    assert ic._next_word("foo bar", 0) == 3
    assert ic._next_word("  foo", 0) == 5
    assert ic._next_word("foo", 3) == 3


def test_word_left_right_moves_by_word():
    s = _run([("char", "alpha beta gamma")])     # cursor at end (16)
    ic.apply_event(s, ("word_left", ""), [], [])
    assert s.cursor == 11                         # start of "gamma"
    ic.apply_event(s, ("word_left", ""), [], [])
    assert s.cursor == 6                          # start of "beta"
    ic.apply_event(s, ("word_right", ""), [], [])
    assert s.cursor == 10                         # end of "beta"


def test_delete_word_removes_word_before_cursor():
    s = _run([("char", "foo bar baz")])           # cursor 11
    ic.apply_event(s, ("delete_word", ""), [], [])
    assert s.buffer == "foo bar " and s.cursor == 8
    ic.apply_event(s, ("delete_word", ""), [], [])
    assert s.buffer == "foo " and s.cursor == 4


def test_kill_to_start_and_end():
    s = _run([("char", "hello world")])           # cursor 11 (end)
    ic.apply_event(s, ("kill_to_start", ""), [], [])
    assert s.buffer == "" and s.cursor == 0

    s2 = _run([("char", "hello world"), ("home", "")])  # cursor 0
    ic.apply_event(s2, ("kill_to_end", ""), [], [])
    assert s2.buffer == ""

    s3 = _run([("char", "hello world")])          # cursor 11
    ic.apply_event(s3, ("word_left", ""), [], [])  # cursor 6 (start of "world")
    ic.apply_event(s3, ("kill_to_end", ""), [], [])
    assert s3.buffer == "hello "
    ic.apply_event(s3, ("kill_to_start", ""), [], [])
    assert s3.buffer == ""


def test_kill_to_start_and_end_bound_to_current_line():
    # Multiline buffer "line1\nline2" with the cursor mid-second-line: Ctrl-U/K
    # must only affect the SECOND line, never reach across the newline into line1.
    # "line1\nline2": indices l0 i1 n2 e3 1·4 \n5 l6 i7 n8 e9 2·10
    s = ic.EditorState()
    s.buffer = "line1\nline2"
    s.cursor = 8                                   # after "li" on line 2
    ic.apply_event(s, ("kill_to_start", ""), [], [])
    assert s.buffer == "line1\nne2" and s.cursor == 6   # line1 untouched
    s2 = ic.EditorState()
    s2.buffer = "line1\nline2"
    s2.cursor = 10                                  # before the trailing "2"
    ic.apply_event(s2, ("kill_to_end", ""), [], [])
    assert s2.buffer == "line1\nline"               # only the line-2 tail removed


def test_word_ops_reset_history_browse():
    hist = ["old one", "old two"]
    s = _run([("char", "draft text")])
    ic.apply_event(s, ("up", ""), [], hist)        # browse history
    assert s.history_idx != -1
    ic.apply_event(s, ("delete_word", ""), [], hist)
    assert s.history_idx == -1                     # editing exits history browse


def test_fuzzy_subsequence_reaches_non_prefix_commands():
    from birkin.inline_complete import CommandHint, filter_commands
    cmds = [CommandHint(name, "") for name in
            ("permission", "sessions", "rollback", "provider", "compact")]
    names = lambda q: [c.name for c in filter_commands(q, cmds)]
    assert "permission" in names("/prm")
    assert "sessions" in names("/sns")
    assert "rollback" in names("/rbk")


def test_exact_prefix_always_outranks_fuzzy():
    from birkin.inline_complete import CommandHint, filter_commands
    cmds = [CommandHint(n, "") for n in ("run", "reunion")]
    # "/run": prefix-matches "run"; "reunion" matches only as a subsequence
    # (r-e-u-n). The prefix must come first.
    ranked = [c.name for c in filter_commands("/run", cmds)]
    assert ranked == ["run", "reunion"]


def test_subseq_helper():
    from birkin.inline_complete import _subseq
    assert _subseq("prm", "permission")
    assert _subseq("", "anything")
    assert not _subseq("xyz", "permission")
    assert not _subseq("mrp", "permission")   # order matters
