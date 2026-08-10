"""The color/animation capability gate: no escapes leak to pipes/CI/NO_COLOR."""

from __future__ import annotations

import subprocess
import sys

# The gate is evaluated at import time (module-level palette constants), so its
# behavior can only be checked in a fresh interpreter with the env pre-set.
_PROBE = (
    "import birkin.ui as ui;"
    "line=f'{ui.RED}x{ui.RESET}';"
    "print('C', ui.should_color());"
    "print('P', ui.plain_mode());"
    "print('ESC', '\\033[' in (ui.CYAN+ui.DIM+ui.RESET+line))"
)


def _run(env_over):
    import os
    env = {**os.environ, "TERM": "xterm-256color"}
    for k in ("NO_COLOR", "BIRKIN_NO_COLOR", "CLICOLOR_FORCE", "BIRKIN_PLAIN"):
        env.pop(k, None)
    env.update(env_over)
    out = subprocess.run([sys.executable, "-c", _PROBE], capture_output=True,
                         text=True, env=env).stdout
    return dict(line.split(" ", 1) for line in out.strip().splitlines())


def test_piped_output_has_no_escapes():
    # stdout captured by subprocess PIPE => not a tty => color off.
    r = _run({})
    assert r["C"] == "False"
    assert r["ESC"] == "False", "ANSI escapes leaked to a pipe"
    assert r["P"] == "True"


def test_clicolor_force_re_enables_when_piped():
    r = _run({"CLICOLOR_FORCE": "1"})
    assert r["C"] == "True" and r["ESC"] == "True"
    assert r["P"] == "False"


def test_no_color_beats_force():
    r = _run({"NO_COLOR": "1", "CLICOLOR_FORCE": "1"})
    assert r["C"] == "False" and r["ESC"] == "False"


def test_empty_no_color_is_unset():
    # NO_COLOR="" must be treated as unset per the spec.
    r = _run({"NO_COLOR": "", "CLICOLOR_FORCE": "1"})
    assert r["C"] == "True"


def test_birkin_no_color_override():
    r = _run({"BIRKIN_NO_COLOR": "1"})
    assert r["C"] == "False"


def test_birkin_plain_forces_plain_but_keeps_color():
    r = _run({"CLICOLOR_FORCE": "1", "BIRKIN_PLAIN": "1"})
    assert r["C"] == "True", "plain mode should not strip color"
    assert r["P"] == "True", "plain mode disables animation"


def test_spinner_is_inert_in_plain_mode():
    from birkin import ui
    sp = ui.Spinner("x")
    sp.start()                       # under pytest stdout is not a tty
    assert sp._thread is None, "spinner must not animate when piped"
    sp.stop()                        # safe no-op


def test_event_printer_text_survives_without_color():
    # The one existing consumer checks substrings, not escapes — the gate must
    # keep the text intact.
    from birkin import ui
    emit = ui.make_event_printer()
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        emit("tool_end", {"name": "read_file", "is_error": False, "content": ""})
    assert "read_file" in buf.getvalue()
