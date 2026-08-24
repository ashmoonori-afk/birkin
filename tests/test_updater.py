"""Tests for birkin self-update (``birkin.updater``).

Drives ``update()`` against real temp git repos (a local "upstream" + a clone),
so the fast-forward / dirty-refuse / already-latest paths are exercised end to
end without touching the network.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from birkin import updater


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t.dev", "-c", "user.name=tester", *args],
        cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def repos(tmp_path):
    """A local 'upstream' repo + a 'work' clone tracking it on main."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-b", "main")
    (upstream / "f.txt").write_text("v1\n", encoding="utf-8")
    _git(upstream, "add", "f.txt")
    _git(upstream, "commit", "-m", "v1")
    work = tmp_path / "work"
    _git(tmp_path, "clone", str(upstream), str(work))
    return {"upstream": upstream, "work": work}


def _bump_upstream(upstream: Path, text: str) -> None:
    (upstream / "f.txt").write_text(text, encoding="utf-8")
    _git(upstream, "add", "f.txt")
    _git(upstream, "commit", "-m", "bump")


def test_update_already_latest(repos):
    r = updater.update(repos["work"])
    assert r["ok"] is True and r["updated"] is False


def test_update_fast_forwards_when_behind(repos):
    _bump_upstream(repos["upstream"], "v2\n")
    r = updater.update(repos["work"])
    assert r["ok"] is True and r["updated"] is True
    assert (repos["work"] / "f.txt").read_text(encoding="utf-8") == "v2\n"


def test_update_refuses_when_dirty(repos):
    _bump_upstream(repos["upstream"], "v2\n")          # an update IS available…
    (repos["work"] / "f.txt").write_text("local\n", encoding="utf-8")  # …but tree is dirty
    r = updater.update(repos["work"])
    assert r["ok"] is False and r["updated"] is False
    assert "commit" in r["message"].lower() or "stash" in r["message"].lower()
    # the local edit must be preserved (no silent reset)
    assert (repos["work"] / "f.txt").read_text(encoding="utf-8") == "local\n"


def test_update_ignores_untracked_files(repos):
    """Untracked files don't block a fast-forward (git pull allows them)."""
    _bump_upstream(repos["upstream"], "v2\n")
    (repos["work"] / "scratch.txt").write_text("note\n", encoding="utf-8")  # untracked
    r = updater.update(repos["work"])
    assert r["ok"] is True and r["updated"] is True


def test_update_not_a_git_checkout(tmp_path):
    r = updater.update(tmp_path)   # no .git here
    assert r["ok"] is False and r["updated"] is False


def test_read_version_reads_init(tmp_path):
    pkg = tmp_path / "birkin"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""doc"""\n__version__ = "1.2.3"\n',
                                     encoding="utf-8")
    assert updater._read_version(tmp_path) == "1.2.3"


def test_read_version_missing_returns_placeholder(tmp_path):
    assert updater._read_version(tmp_path) == "?"   # no birkin/__init__.py


def test_update_message_shows_release_version_without_head_date(repos):
    """The message references a release version, not HEAD metadata.
    (The temp clone has no birkin/__init__.py, so the version reads as '?'.)"""
    import re
    r = updater.update(repos["work"])
    assert r["message"] == "Already up to date — v?."
    assert re.search(r"\d{4}-\d{2}-\d{2}", r["message"]) is None
