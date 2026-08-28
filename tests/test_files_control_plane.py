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

import os
from pathlib import Path
import sys
import types

import pytest

from birkin import config
from birkin.office import windows_native
from birkin.tools import file_listing, file_target_windows, files


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


@pytest.mark.parametrize(
    "relative",
    [
        "office/receipt_hmac_key",
        "office/jobs/job.jsonl",
        "office/artifacts/drafts/validated.docx",
        "office/artifacts/export-backups/token.bak",
        "office/artifacts/export-journal/transaction.json",
        "office/artifacts/export-locks/destination.lock",
    ],
)
def test_office_authority_refuses_model_file_access(
    ctx,
    relative,
) -> None:
    target = config.birkin_home() / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("authority", encoding="utf-8")

    read = files._read_file({"path": str(target)}, ctx)
    write = files._write_file(
        {"path": str(target), "content": "changed"},
        ctx,
    )
    listing = files._list_files({"path": str(target)}, ctx)

    assert read.is_error and "integrity-protected" in read.content
    assert write.is_error and "integrity-protected" in write.content
    assert listing.is_error and "integrity-protected" in listing.content
    assert target.read_text(encoding="utf-8") == "authority"


def test_read_file_reauthorizes_opened_symlink_target(
    ctx,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benign = tmp_path / "benign.txt"
    benign.write_text("benign", encoding="utf-8")
    secret = config.birkin_home() / "office" / "receipt_hmac_key"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("office secret", encoding="utf-8")
    requested = tmp_path / "requested.txt"
    requested.symlink_to(benign)
    replacement = tmp_path / "replacement.txt"
    replacement.symlink_to(secret)
    real_policy = files._integrity_plane_error
    swapped = False

    def swap_after_authorization(path):
        nonlocal swapped
        result = real_policy(path)
        if path == requested and not swapped:
            requested.unlink()
            replacement.rename(requested)
            swapped = True
        return result

    monkeypatch.setattr(
        files,
        "_integrity_plane_error",
        swap_after_authorization,
    )

    result = files._read_file({"path": str(requested)}, ctx)

    assert swapped is True
    assert result.is_error
    assert "integrity-protected" in result.content
    assert "office secret" not in result.content


def test_write_file_reauthorizes_opened_symlink_target(
    ctx,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benign = tmp_path / "benign.txt"
    benign.write_text("benign", encoding="utf-8")
    secret = config.birkin_home() / "office" / "receipt_hmac_key"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("office secret", encoding="utf-8")
    requested = tmp_path / "requested.txt"
    requested.symlink_to(benign)
    replacement = tmp_path / "replacement.txt"
    replacement.symlink_to(secret)
    real_policy = files._control_plane_error
    swapped = False

    def swap_after_authorization(path, context):
        nonlocal swapped
        result = real_policy(path, context)
        if path == requested and not swapped:
            requested.unlink()
            replacement.rename(requested)
            swapped = True
        return result

    monkeypatch.setattr(
        files,
        "_control_plane_error",
        swap_after_authorization,
    )

    result = files._write_file(
        {"path": str(requested), "content": "tampered"},
        ctx,
    )

    assert swapped is True
    assert result.is_error
    assert "integrity-protected" in result.content
    assert secret.read_text(encoding="utf-8") == "office secret"


def test_list_files_reauthorizes_opened_directory(
    ctx,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benign = tmp_path / "benign"
    benign.mkdir()
    jobs = config.birkin_home() / "office" / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    _ = (jobs / "secret-job.jsonl").write_text("secret", encoding="utf-8")
    requested = tmp_path / "requested"
    requested.symlink_to(benign, target_is_directory=True)
    replacement = tmp_path / "replacement"
    replacement.symlink_to(jobs, target_is_directory=True)
    real_policy = files._integrity_plane_error
    swapped = False

    def swap_after_authorization(path):
        nonlocal swapped
        result = real_policy(path)
        if path == requested and not swapped:
            requested.unlink()
            replacement.rename(requested)
            swapped = True
        return result

    monkeypatch.setattr(
        files,
        "_integrity_plane_error",
        swap_after_authorization,
    )

    result = files._list_files({"path": str(requested)}, ctx)

    assert swapped is True
    assert result.is_error
    assert "secret-job.jsonl" not in result.content


def test_file_tools_reject_hardlink_alias_to_office_secret(
    ctx,
    tmp_path,
) -> None:
    secret = config.birkin_home() / "office" / "receipt_hmac_key"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("office secret", encoding="utf-8")
    alias = tmp_path / "alias.txt"
    os.link(secret, alias)

    read = files._read_file({"path": str(alias)}, ctx)
    write = files._write_file(
        {"path": str(alias), "content": "tampered"},
        ctx,
    )

    assert read.is_error
    assert write.is_error
    assert secret.read_text(encoding="utf-8") == "office secret"


def test_file_tools_allow_ordinary_workspace_hardlinks(
    ctx,
    tmp_path,
) -> None:
    original = tmp_path / "original.txt"
    alias = tmp_path / "alias.txt"
    original.write_text("ordinary", encoding="utf-8")
    os.link(original, alias)

    read = files._read_file({"path": str(alias)}, ctx)
    write = files._write_file(
        {"path": str(alias), "content": "updated"},
        ctx,
    )

    assert not read.is_error
    assert read.content == "ordinary"
    assert not write.is_error
    assert original.read_text(encoding="utf-8") == "updated"


def test_windows_created_file_uses_create_new(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = types.SimpleNamespace(
        GENERIC_READ=0x80000000,
        FILE_SHARE_READ=1,
        FILE_SHARE_WRITE=2,
        FILE_SHARE_DELETE=4,
        CREATE_NEW=1,
    )
    captured: dict[str, int | None] = {}

    def open_handle(
        path: Path,
        *,
        directory: bool,
        access: int,
        share: int,
        disposition: int | None = None,
    ) -> int:
        del path, directory, access, share
        captured["disposition"] = disposition
        return 41

    fake_msvcrt = types.ModuleType("msvcrt")
    setattr(
        fake_msvcrt,
        "open_osfhandle",
        lambda handle, flags: handle + flags,
    )
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(windows_native, "api", lambda: native)
    monkeypatch.setattr(windows_native, "open_handle", open_handle)

    descriptor = file_target_windows.open_created(tmp_path / "new.txt")

    assert descriptor == 41 + os.O_RDWR + getattr(os, "O_BINARY", 0)
    assert captured == {"disposition": 1}


def test_windows_listing_uses_handle_pinned_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = tmp_path / "child"
    child.mkdir()
    (child / "z.txt").write_text("z", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    opened: dict[int, Path] = {}

    def open_directory(path: Path) -> int:
        handle = len(opened) + 1
        opened[handle] = path
        return handle

    monkeypatch.setattr(
        file_target_windows,
        "open_directory",
        open_directory,
    )
    monkeypatch.setattr(
        file_target_windows,
        "handle_final_path",
        lambda handle: opened[handle],
    )
    monkeypatch.setattr(
        file_target_windows,
        "close_handle",
        lambda handle: opened.pop(handle),
    )

    tree = file_listing._render_windows(  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        depth=2,
        policy=lambda path: "",
    )

    assert tree == f"{tmp_path}/\n  a.txt\n  child/\n    z.txt"
    assert opened == {}


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
