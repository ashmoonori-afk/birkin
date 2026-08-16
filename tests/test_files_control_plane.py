"""The file tools must not be able to rewrite birkin's own control plane.

`birkin morpheus` runs unattended overnight and deliberately drops shell:

    # Birkin's registry excludes shell/subagent tools.
    build_registry(ctx, include={"files", "web", "skills", "memory"})

but `files` carries write_file, and three files under ~/.birkin turn a write
back into arbitrary code execution:

  cron.json            scheduler._run_job runs type="shell" jobs through
                       subprocess with NO consent check of any kind, and the
                       daemon re-reads the file every 30s. approvals.propose()
                       has an explicit, ADR-029-tested gate stopping a
                       shell-typed cron from auto-applying (approvals.py:27-34,
                       :48-49) — writing the file directly walks past it.
  config.json          adds a "hooks" entry; hooks are arbitrary commands.
  hooks_allowlist.json is the exact list hooks.is_allowed() consults, so
                       pre-planting an entry makes _consent return True before
                       it ever reaches the "not approved, skipping" branch —
                       headless included.
  hooks/               the documented location for hook scripts; overwriting
                       one that is already consented-to is execution too.

fs_jail does not help: _jail_roots() lists birkin_home() as an ALLOWED root,
so these paths are writable with the jail on or off. Hence the refusal here is
unconditional rather than jail-gated.

Nothing legitimate writes these through the tool loop — config goes through
/permission and `birkin config`, cron through approvals.propose() ->
cron.add_job(), hooks are edited by the user.
"""

from __future__ import annotations

import types

import pytest

from birkin import config
from birkin.tools import files


@pytest.fixture
def ctx(tmp_path):
    return types.SimpleNamespace(cwd=tmp_path, cfg={})


def _protected():
    home = config.birkin_home()
    return [home / "config.json", home / "cron.json",
            home / "hooks_allowlist.json", home / "hooks" / "guard.py"]


@pytest.mark.parametrize("jail", [False, True])
def test_write_file_refuses_the_control_plane(ctx, jail):
    ctx.cfg = {"fs_jail": jail}
    for path in _protected():
        before = path.read_text(encoding="utf-8") if path.is_file() else None
        res = files._write_file({"path": str(path), "content": "pwned"}, ctx)
        assert res.is_error, f"fs_jail={jail}: write to {path.name} allowed"
        after = path.read_text(encoding="utf-8") if path.is_file() else None
        assert after == before, f"{path.name} was modified anyway"


@pytest.mark.parametrize("jail", [False, True])
def test_edit_file_refuses_the_control_plane(ctx, jail):
    """The hash-anchored editor is a second write path to the same files."""
    ctx.cfg = {"fs_jail": jail}
    home = config.birkin_home()
    target = home / "cron.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file():
        target.write_text("[]\n", encoding="utf-8")
    before = target.read_text(encoding="utf-8")
    res = files._edit_file(
        {"path": str(target),
         "edits": [{"line": 1, "hash": "abcd", "new": "x"}]}, ctx)
    # Must be refused as protected, NOT merely as a stale hash — otherwise the
    # test passes without the fix and proves nothing.
    assert res.is_error and "protected:" in res.content
    assert target.read_text(encoding="utf-8") == before


def test_refusal_survives_a_symlink_and_relative_traversal(ctx, tmp_path):
    """realpath, not string matching — the jail already learned this lesson."""
    home = config.birkin_home()
    res = files._write_file(
        {"path": str(home / "sub" / ".." / "cron.json"), "content": "x"}, ctx)
    assert res.is_error, "traversal back onto cron.json was allowed"

    link = tmp_path / "innocent.json"
    try:
        link.symlink_to(home / "cron.json")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this host")
    res = files._write_file({"path": str(link), "content": "x"}, ctx)
    assert res.is_error, "a symlink routed around the refusal"


def test_the_error_says_which_file_and_why(ctx):
    res = files._write_file(
        {"path": str(config.birkin_home() / "cron.json"), "content": "x"}, ctx)
    assert "cron.json" in res.content


def test_ordinary_writes_still_work(ctx, tmp_path):
    res = files._write_file({"path": str(tmp_path / "note.md"),
                             "content": "hello"}, ctx)
    assert not res.is_error
    assert (tmp_path / "note.md").read_text(encoding="utf-8") == "hello"


def test_user_skills_remain_writable(ctx):
    """create_skill/improve_skill legitimately write under ~/.birkin/skills/;
    blocking all of birkin_home would break them."""
    target = config.birkin_home() / "skills" / "demo" / "SKILL.md"
    res = files._write_file({"path": str(target), "content": "# demo\n"}, ctx)
    assert not res.is_error, "the refusal is too broad — it caught user skills"


def test_a_file_merely_named_like_one_elsewhere_is_fine(ctx, tmp_path):
    """Only ~/.birkin's own control plane is protected — a project's own
    config.json is ordinary content."""
    res = files._write_file({"path": str(tmp_path / "config.json"),
                             "content": "{}"}, ctx)
    assert not res.is_error


# -- the reason these three files, and no others ---------------------------

def test_shell_cron_still_cannot_auto_apply_through_the_approved_path():
    """The gate write_file was bypassing. Pinned here so the two stay linked:
    if this ever loosens, the file refusal above is the only thing left."""
    from birkin import approvals
    assert approvals._is_shell_cron("cron", {"type": "shell"}) is True
    assert approvals._is_shell_cron("cron", {"type": " Shell "}) is True
    assert approvals._is_shell_cron("cron", {"type": "prompt"}) is False


def test_scheduler_runs_shell_jobs_without_asking():
    """Documents WHY cron.json is protected: nothing downstream re-checks."""
    import inspect
    from birkin import scheduler
    src = inspect.getsource(scheduler.run_job)
    assert 'jtype == "shell"' in src and "run_shell_command" in src
    assert "approv" not in src.lower(), (
        "if _run_job grew its own consent check, revisit this test")


def test_morpheus_still_ships_files_without_shell():
    """If morpheus ever regains shell, this whole fix stops being the boundary
    it is protecting — and if it loses `files`, the test above over-claims."""
    import inspect
    from birkin import morpheus
    src = inspect.getsource(morpheus)
    assert 'include={"files", "web", "skills", "memory"}' in src
