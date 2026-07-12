"""P1-2: the user sees what was remembered/recalled (memory_activity_line)."""

from birkin.memory import memory_activity_line


def test_write_shows_the_note_title():
    assert memory_activity_line(
        "memory_write_note", "Wrote note [[deploy failure]] -> /x") \
        == "🧠 remembered [[deploy failure]]"
    assert memory_activity_line("remember", "Wrote note [[user likes tea]] -> p") \
        == "🧠 remembered [[user likes tea]]"


def test_search_counts_recalled_notes():
    body = "- [[a]]: snip\n- [[b]]: snip\n- [[c]]: snip"
    assert memory_activity_line("memory_search", body) == "🧠 recalled 3 note(s)"
    assert memory_activity_line("memory_search", "No matching notes.") \
        == "🧠 searched memory (0)"


def test_other_memory_tools():
    assert memory_activity_line("memory_get_note", "full text") == "🧠 opened a note"
    assert memory_activity_line("memory_link", "Linked.") == "🧠 linked notes"


def test_non_memory_tool_is_silent():
    assert memory_activity_line("run_shell", "output") is None
    assert memory_activity_line("web_fetch", "html") is None


def test_repl_event_printer_shows_memory_line(capsys):
    from birkin import ui
    emit = ui.make_event_printer()
    emit("tool_end", {"name": "memory_search", "is_error": False,
                      "content": "- [[x]]: s\n- [[y]]: s"})
    out = capsys.readouterr().out
    assert "recalled 2 note(s)" in out
    # an errored memory tool shows no transparency line (only the ✗ mark)
    emit("tool_end", {"name": "memory_write_note", "is_error": True,
                      "content": ""})
    assert "remembered" not in capsys.readouterr().out
