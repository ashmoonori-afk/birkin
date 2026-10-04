"""Real CLI pipes must preserve UTF-8 independently of the parent's locale."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping
from typing import Final

import pytest

from birkin_mnemosyne.providers import _run as run_provider


SAMPLE: Final = "\uba54\ubaa8 \u6f22\u5b57 \u2728 \U0001f680"


def _legacy_call(
    monkeypatch: pytest.MonkeyPatch, child: str, stdin: str | None,
) -> tuple[str, str, int]:
    """Force only the implicit codec while keeping the real child and pipes."""
    real_run = subprocess.run

    def legacy_run(
        argv: list[str], *,
        input: str | None = None,
        capture_output: bool = False,
        text: bool = False,
        encoding: str | None = None,
        errors: str | None = None,
        timeout: int | None = None,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return real_run(
            argv, input=input, capture_output=capture_output, text=text,
            encoding="cp949" if encoding is None else encoding,
            errors=errors, timeout=timeout, cwd=cwd, env=env,
        )

    with monkeypatch.context() as scoped:
        scoped.setattr(subprocess, "run", legacy_run)
        return run_provider([sys.executable, "-c", child], stdin=stdin, timeout=30)


@pytest.mark.parametrize("prompt", [SAMPLE, "ordinary ASCII note"])
def test_stdin_bytes_are_utf8_under_legacy_default(
    monkeypatch: pytest.MonkeyPatch, prompt: str,
) -> None:
    # Given: a UTF-8 child and a forced legacy default codec.
    child = (
        "import sys; data = sys.stdin.buffer.read(); "
        "sys.stdout.buffer.write(data.hex().encode('ascii'))"
    )
    # When: the provider transports a prompt to the real child.
    result = _legacy_call(monkeypatch, child, prompt)
    # Then: exact bytes, not a matching wrong codec at both ends.
    assert result == (prompt.encode("utf-8").hex(), "", 0)


@pytest.mark.parametrize("response", [SAMPLE, "ordinary ASCII response"])
def test_independent_utf8_stdout_stderr_and_exit_status(
    monkeypatch: pytest.MonkeyPatch, response: str,
) -> None:
    # Given: independently generated output, with no stdin decoding dependency.
    child = (
        f"import sys; data = {ascii(response)}.encode('utf-8'); "
        "sys.stdout.buffer.write(data); sys.stderr.buffer.write(data); sys.exit(7)"
    )
    # When: both real output streams are decoded by the provider.
    result = _legacy_call(monkeypatch, child, None)
    # Then: exact Unicode and the nonzero status are preserved.
    assert result == (response, response, 7)


def test_empty_input_and_invalid_output_keep_replacement_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: empty stdin and deliberately malformed output bytes.
    child = (
        "import sys; assert sys.stdin.buffer.read() == b''; "
        "sys.stdout.buffer.write(b'ok\\xff'); sys.stderr.buffer.write(b'err\\xff')"
    )
    # When: the existing tolerant text policy handles both real streams.
    result = _legacy_call(monkeypatch, child, "")
    # Then: the codec fix does not change empty input or replacement behavior.
    assert result == ("ok\ufffd", "err\ufffd", 0)
