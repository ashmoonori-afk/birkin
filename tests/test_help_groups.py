"""/help is grouped by domain and never hides a command."""

from __future__ import annotations

import contextlib
import io
import types


def _help_output():
    import birkin.repl  # noqa: F401  (registers every command)
    from birkin import config, slashcommands as sc
    buf = io.StringIO()
    sess = types.SimpleNamespace(cfg=config.load_config())
    with contextlib.redirect_stdout(buf):
        sc.dispatch(sess, "/help")
    return buf.getvalue()


def test_help_prints_domain_headers():
    out = _help_output()
    for header in ("세션·대화", "모델", "기억", "스킬·도구", "운영·승인"):
        assert header in out, f"missing group header {header!r}"


def test_every_registered_command_appears():
    import birkin.repl  # noqa: F401
    from birkin import slashcommands as sc
    out = _help_output()
    for name in sc._REGISTRY:
        assert f"/{name}" in out, f"/{name} is hidden from /help"


def test_no_command_is_orphaned_from_a_group():
    import birkin.repl  # noqa: F401
    from birkin import slashcommands as sc
    grouped = set()
    for _title, names in sc._HELP_GROUPS:
        grouped |= set(names)
    # Everything either sits in a named group or falls to the "기타" catch-all;
    # this asserts the named groups actually cover the real command set.
    orphans = set(sc._REGISTRY) - grouped
    assert orphans == set(), f"uncategorized commands: {sorted(orphans)}"


def test_help_for_one_command_still_works():
    import birkin.repl  # noqa: F401
    from birkin import config, slashcommands as sc
    buf = io.StringIO()
    sess = types.SimpleNamespace(cfg=config.load_config())
    with contextlib.redirect_stdout(buf):
        sc.dispatch(sess, "/help rollback")
    out = buf.getvalue()
    assert "/rollback" in out and "usage:" in out
