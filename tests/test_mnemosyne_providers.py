"""``birkin_mnemosyne.providers._run`` must speak UTF-8 with every child.

Without an explicit ``encoding`` the text pipes inherit Python's default codec,
so on a cp949 (or any non-UTF-8) locale prompts are mangled and UTF-8 answers
come back as mojibake. The child here reads ``sys.stdin.buffer`` directly, so
the subprocess codec -- not the test process's own locale -- is what is under
test.
"""

from __future__ import annotations

import subprocess
import sys

from birkin_mnemosyne import providers

# Korean, CJK, and an emoji: the sparkle in the finding alone would be replaced.
SAMPLE = "\uba54\ubaa8 \u6f22\u5b57 \U0001f680"

CHILD = (
    "import sys\n"
    "text = sys.stdin.buffer.read().decode('utf-8')\n"
    "sys.stdout.buffer.write(text.encode('utf-8'))\n"
    "sys.stderr.buffer.write(text.encode('utf-8'))\n"
)


def test_run_uses_utf8_under_non_utf8_default(monkeypatch):
    monkeypatch.setattr(subprocess, "_text_encoding", lambda *a, **k: "cp949")

    assert providers._run([sys.executable, "-c", CHILD], stdin=SAMPLE,
                          timeout=10) == (SAMPLE, SAMPLE, 0)
