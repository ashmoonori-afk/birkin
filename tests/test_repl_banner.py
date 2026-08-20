"""The launch banner surfaces the live status + points at the new TUI."""

from __future__ import annotations

import contextlib
import io
import re
import types


def _banner_output(monkeypatch):
    from birkin import repl
    # statusline reads real backend; stub it to a known string so the test is
    # about the banner wiring, not the backend.
    monkeypatch.setattr("birkin.statusline.render",
                        lambda cfg: "  gpt-5.6-sol·codex-cli · ●up · ⚑2")
    sess = types.SimpleNamespace(
        cfg={"model": "gpt-5.6-sol", "provider": "codex-cli"},
        skills=types.SimpleNamespace(skills=[1, 2, 3]),
        memory=types.SimpleNamespace(vault="/x/vault"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        repl._banner(sess)
    return re.sub(r"\033\[[0-9;?]*m", "", buf.getvalue())


def test_banner_shows_the_live_status_line(monkeypatch):
    out = _banner_output(monkeypatch)
    assert "●up" in out and "⚑2" in out, "launch screen has no live status"


def test_banner_advertises_the_new_surfaces(monkeypatch):
    out = _banner_output(monkeypatch)
    assert "/work" in out and "/status" in out


def test_banner_does_not_advertise_the_deprecated_dash_alias(monkeypatch):
    # /work and /dash are one surface now; the launch screen must point at the
    # supported name so new users never learn the deprecated alias.
    out = _banner_output(monkeypatch)
    assert "/dash" not in out
