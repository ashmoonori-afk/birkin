"""Text codec contract for ``birkin_mnemosyne.providers._run``.

The CLI adapters hand prompts to real child processes through ``_run``. Without
an explicit ``encoding``, the parent's default subprocess text codec decides how
prompt text is encoded and how child output is decoded, so a cp949 (or any
non-UTF-8) default silently corrupts multilingual prompts and responses. These
tests pin the pipes to UTF-8 with real children only: no installed model CLI,
no locale mutation, and no CPython-private helpers.

Each test injects a deterministic non-UTF-8 fallback at the public
``subprocess.run`` boundary. The forwarded real call keeps child execution, pipe
transport, decoding, and return status untouched; only the implicit codec
selection changes, which is exactly the regression under test (and it still
fires when CI exports ``PYTHONUTF8=1``).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from birkin_mnemosyne import providers

SAMPLE = "\uba54\ubaa8 \u6f22\u5b57 \u2728 \U0001f680"

# ASCII-only child source: it moves raw bytes so the codec under test is the
# only variable, and it never depends on the child's own stdio codec.
_HEX_STDIN_CHILD = (
    "import sys\n"
    "sys.stdout.write(sys.stdin.buffer.read().hex())\n"
)

_UTF8_STREAMS_CHILD = (
    "import sys\n"
    "data = '\\uba54\\ubaa8 \\u6f22\\u5b57 \\u2728 \\U0001f680'.encode('utf-8')\n"
    "sys.stdout.buffer.write(data)\n"
    "sys.stderr.buffer.write(data)\n"
    "raise SystemExit(7)\n"
)

_EMPTY_STDIN_CHILD = (
    "import sys\n"
    "assert sys.stdin.buffer.read() == b''\n"
    "sys.stdout.buffer.write(b'ok\\xff')\n"
    "sys.stderr.buffer.write(b'err\\xff')\n"
)


@pytest.fixture
def legacy_default_codec(monkeypatch):
    """Force implicit subprocess text I/O onto cp949, mid-pytest.

    ``subprocess.run`` reads the default text codec from the *live* locale, so
    pytest's capture machinery has already pinned it to UTF-8 by the time a test
    runs. Patching ``locale.getpreferredencoding`` is the only portable, public
    way to make "no explicit encoding" select a legacy codec again; on Python
    3.10 there is no ``subprocess._text_encoding`` to patch at all.
    """
    import locale

    real_run = providers.subprocess.run
    real_getpreferredencoding = locale.getpreferredencoding

    def force_cp949(do_setlocale=True):
        return "cp949"

    def forwarding_run(*args, **kwargs):
        if kwargs.get("encoding") is None:
            kwargs["encoding"] = "cp949"
        return real_run(*args, **kwargs)

    monkeypatch.setattr(providers.subprocess, "run", forwarding_run)
    monkeypatch.setattr(locale, "getpreferredencoding", force_cp949)
    yield
    monkeypatch.undo()
    assert providers.subprocess.run is real_run
    assert locale.getpreferredencoding is real_getpreferredencoding


@pytest.mark.parametrize("prompt", [SAMPLE, "plain ascii prompt"])
def test_run_sends_prompt_as_utf8_bytes(legacy_default_codec, prompt):
    """The child must receive the prompt's UTF-8 bytes, whatever the locale is.

    The hex assertion is deliberate: a codec mismatch on both ends could still
    round-trip text, but it cannot fake these bytes.
    """
    out, err, code = providers._run(
        [sys.executable, "-c", _HEX_STDIN_CHILD], stdin=prompt, timeout=30)

    assert (out, err, code) == (prompt.encode("utf-8").hex(), "", 0)


def test_run_decodes_child_utf8_streams(legacy_default_codec):
    """Child UTF-8 on both streams must decode exactly, exit status preserved."""
    out, err, code = providers._run(
        [sys.executable, "-c", _UTF8_STREAMS_CHILD], stdin=None, timeout=30)

    assert (out, err, code) == (SAMPLE, SAMPLE, 7)


def test_run_keeps_empty_stdin_and_replacement_decoding(legacy_default_codec):
    """Empty stdin stays empty and undecodable output stays tolerant."""
    out, err, code = providers._run(
        [sys.executable, "-c", _EMPTY_STDIN_CHILD], stdin="", timeout=30)

    assert (out, err, code) == ("ok\ufffd", "err\ufffd", 0)


def test_default_codec_injection_would_actually_corrupt(monkeypatch):
    """Guard the harness: without the production encoding, cp949 corrupts.

    This is the negative control for the fixture above. It calls the real
    ``subprocess.run`` with cp949 forced and no explicit encoding, proving the
    injected codec really reaches pipe encoding/decoding on this interpreter.
    """
    import locale

    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=True: "cp949")

    proc = subprocess.run([sys.executable, "-c", _HEX_STDIN_CHILD],
                          input=SAMPLE, capture_output=True, text=True,
                          errors="replace", timeout=30)

    assert proc.stdout != SAMPLE.encode("utf-8").hex()
    assert SAMPLE.encode("cp949", "replace").hex() == proc.stdout
