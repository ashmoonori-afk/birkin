"""File tools: read, write, list. Paths resolve against the context cwd."""

from __future__ import annotations

import os
import ctypes
import ntpath
import tempfile
from pathlib import Path
from typing import Any

from ..operation_policy import ApprovalRequiredError
from ._types import Tool, ToolContext, ToolResult
from .file_target import (
    OpenedTarget,
    UnsafeTargetError,
    close_target,
    open_existing,
    open_for_write,
    read_bytes,
    replace_bytes,
)
from .file_listing import render_tree
from .file_atomic_replace import replace_bytes_atomic
from .hashline import annotate, edit_text

MAX_READ_BYTES = 200_000


def _windows_drive_type(root: str) -> int | None:
    if os.name != "nt":
        return None
    get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
    get_drive_type.argtypes = [ctypes.c_wchar_p]
    get_drive_type.restype = ctypes.c_uint
    return int(get_drive_type(root))


def _network_path_blocked(ctx: ToolContext, raw: str) -> bool:
    egress = ctx.cfg.get("egress", {})
    enforced = (
        isinstance(egress, dict)
        and bool(egress)
        and bool(egress.get("enabled", True))
        and bool(egress.get("enforced", True))
    )
    if not enforced:
        return False
    normalized = raw.replace("/", "\\")
    if normalized.startswith("\\\\"):
        return True
    drive, _tail = ntpath.splitdrive(normalized)
    return (
        len(drive) == 2
        and drive.endswith(":")
        and _windows_drive_type(f"{drive}\\") == 4
    )


def _resolve(ctx: ToolContext, raw: str) -> Path:
    p = Path(raw).expanduser()
    p = p if p.is_absolute() else (ctx.cwd / p)
    if (
        not getattr(ctx, "approved_operation", False)
        and (
            _network_path_blocked(ctx, raw)
            or (
                not ntpath.splitdrive(raw.replace("/", "\\"))[0]
                and _network_path_blocked(ctx, str(ctx.cwd))
            )
        )
    ):
        raise ApprovalRequiredError(
            "network_file_policy",
            "Network file paths are disabled during enforced egress",
        )
    # Opt-in path jail (default off — see config "fs_jail"). When on, confine
    # file tools to the workspace and ~/.birkin so the native loop can't read or
    # overwrite arbitrary files via an absolute path or "..". Off by default to
    # preserve existing behavior (the project's choice is warn, not hard-deny).
    if (
        ctx.cfg.get("fs_jail")
        and not getattr(ctx, "approved_operation", False)
    ):
        _enforce_jail(ctx, p)
    return p


def _jail_roots(ctx: ToolContext) -> list[Path]:
    roots = [Path(ctx.cwd).resolve()]
    try:
        from .. import config
        roots.append(config.birkin_home().resolve())
    except Exception:
        pass
    return roots


def _enforce_jail(ctx: ToolContext, p: Path) -> None:
    """Raise ValueError if ``p`` resolves outside the allowed roots.

    Uses realpath so a symlink can't redirect the write outside the jail."""
    rp = Path(os.path.realpath(p))
    for root in _jail_roots(ctx):
        if rp == root or root in rp.parents:
            return
    raise ApprovalRequiredError(
        "fs_jail",
        f"fs_jail refused a path outside the workspace and ~/.birkin: {p}",
    )


# birkin's own control plane. A write here is not a file edit, it is a
# privilege escalation:
#   cron.json            scheduler._run_job runs type="shell" jobs through
#                        subprocess with no consent check at all, and the
#                        daemon re-reads the file every 30s. approvals.propose
#                        has an explicit gate (ADR-029) stopping a shell-typed
#                        cron from auto-applying; writing the file skips it.
#   config.json          declares "hooks" — arbitrary commands.
#   hooks_allowlist.json IS the consent record hooks.is_allowed() reads, so a
#                        planted entry makes _consent return True before it
#                        reaches the "not approved, skipping" branch.
#   hooks/               the documented home for hook scripts; overwriting one
#                        that is already consented-to is execution too.
# `birkin morpheus` runs unattended with write_file but deliberately WITHOUT
# shell ("Birkin's registry excludes shell/subagent tools"); these writes hand
# it back. Unconditional rather than fs_jail-gated, because _jail_roots()
# lists birkin_home() as an allowed root — the jail cannot express this.
#   companion/           the commitment/check-in store. "The LLM may propose a
#                        candidate; only companion.py's functions transition
#                        one" (its module contract) is hollow if write_file can
#                        edit state.json — a planted policy/commitment turns
#                        into unattended outbound Telegram messages.
_CONTROL_FILES = ("config.json", "cron.json", "hooks_allowlist.json")
_CONTROL_DIRS = {
    "hooks": "files under ~/.birkin/hooks/ are run as approved hooks, so "
             "the file tools cannot write them.",
    "companion": "~/.birkin/companion/ is the approval-gated check-in state — "
                 "propose changes with companion_propose instead of editing "
                 "its files.",
}
_INTEGRITY_DIRS = {
    "pending": "~/.birkin/pending contains digest-bound approval records and cannot "
               "be changed through native file tools.",
}
_OFFICE_AUTHORITY_PATHS = (
    ("office", "receipt_hmac_key"),
    ("office", "jobs"),
    ("office", "artifacts", "drafts"),
    ("office", "artifacts", "export-backups"),
    ("office", "artifacts", "export-journal"),
    ("office", "artifacts", "export-locks"),
)


def _integrity_plane_error(p: Path) -> str:
    try:
        from .. import config
        home = Path(os.path.realpath(config.birkin_home()))
    except Exception:
        return ""
    rp = Path(os.path.realpath(p))
    if (
        rp.parent == home / "office"
        and rp.name.startswith(".receipt_hmac_key.")
    ):
        return (
            "integrity-protected: Office authority is accessible only "
            "through registered document tools."
        )
    for parts in _OFFICE_AUTHORITY_PATHS:
        root = home.joinpath(*parts)
        if rp == root or root in rp.parents:
            return (
                "integrity-protected: Office authority is accessible only "
                "through registered document tools."
            )
    return ""


def _integrity_target_error(target: OpenedTarget) -> str:
    metadata = os.fstat(target.descriptor)
    if metadata.st_nlink == 1:
        return ""
    try:
        from .. import config

        home = Path(os.path.realpath(config.birkin_home()))
        expected = (metadata.st_dev, metadata.st_ino)
        roots = tuple(
            home.joinpath(*parts)
            for parts in _OFFICE_AUTHORITY_PATHS
        )
        for root in roots:
            if root.is_file() and _path_identity(root) == expected:
                return _integrity_plane_error(root)
            if not root.is_dir():
                continue
            for directory, _names, files_in_directory in os.walk(root):
                for name in files_in_directory:
                    candidate = Path(directory) / name
                    if _path_identity(candidate) == expected:
                        return _integrity_plane_error(candidate)
    except OSError:
        return (
            "integrity-protected: Office authority identity could not "
            "be verified."
        )
    return ""


def _path_identity(path: Path) -> tuple[int, int] | None:
    try:
        metadata = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return None
    return metadata.st_dev, metadata.st_ino


def _control_plane_error(p: Path, ctx: ToolContext) -> str:
    """Why this path must not be written, or "" if it is ordinary."""
    integrity = _integrity_plane_error(p)
    if integrity:
        return integrity
    try:
        from .. import config
        home = Path(os.path.realpath(config.birkin_home()))
    except Exception:
        return ""
    # realpath both sides so "sub/.." and a symlink land on the real target,
    # the same reasoning _enforce_jail already applies.
    rp = Path(os.path.realpath(p))
    for directory, why in _INTEGRITY_DIRS.items():
        root = home / directory
        if rp == root or root in rp.parents:
            return f"integrity-protected: {why}"
    if getattr(ctx, "approved_operation", False):
        return ""
    if rp.parent == home and rp.name in _CONTROL_FILES:
        return (f"protected: {rp.name} is birkin's own control plane — it "
                f"schedules or authorises command execution, so the file "
                f"tools cannot write it. Use the approval flow instead "
                f"(propose_action), or edit it yourself outside birkin.")
    for d, why in _CONTROL_DIRS.items():
        root = home / d
        if rp == root or root in rp.parents:
            return f"protected: {why}"
    return ""


def _normalize_newlines(s: str) -> str:
    """CRLF/CR -> LF so hashline operates on clean ``\\n`` lines cross-platform."""
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _atomic_write_text(path: Path, text: str) -> None:
    """Write text via a temp sibling + os.replace so a crash can't truncate it.
    ``newline=""`` disables platform translation so LF stays LF (no CRLF surprise
    that would invalidate the hashes the agent just saw)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # mkstemp creates the temp file with O_EXCL + 0600 in the destination dir, so
    # a pre-planted symlink under a *predictable* name can't redirect the write.
    # (The old ``<file>.<pid>.tmp`` name was a TOCTOU foothold in shared dirs.)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent),
                                    prefix=path.name + ".", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _read_file(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
    path = _resolve(ctx, inp.get("path", ""))
    blocked = _integrity_plane_error(path)
    if blocked:
        return ToolResult(blocked, is_error=True)
    try:
        target = open_existing(
            path,
            writable=False,
            policy=_integrity_plane_error,
        )
        identity_blocked = _integrity_target_error(target)
        if identity_blocked:
            close_target(target)
            return ToolResult(identity_blocked, is_error=True)
    except UnsafeTargetError as exc:
        return ToolResult(str(exc.strerror), is_error=True)
    except PermissionError:
        raise
    except OSError:
        return ToolResult(f"No such file: {path}", is_error=True)
    try:
        data = read_bytes(target)
    finally:
        close_target(target)
    try:
        offset = max(0, int(inp.get("offset", 0) or 0))
    except (TypeError, ValueError):
        offset = 0
    if offset >= len(data) and len(data):
        return ToolResult(
            f"offset {offset} is past the end of the file ({len(data)} bytes).",
            is_error=True)
    if offset and inp.get("annotate"):
        # Annotation numbers lines from 1, so an offset read would hand
        # edit_file line numbers that point somewhere else in the file. The
        # hash anchor would reject the edit anyway — fail clearly instead.
        return ToolResult(
            "annotate cannot be combined with offset: line numbers would not "
            "match the file. Re-read from offset=0 to edit.", is_error=True)
    window = data[offset:offset + MAX_READ_BYTES]
    truncated = offset + len(window) < len(data)
    text = window.decode("utf-8", "replace")
    # annotate=true tags each line "{n}#{hash}| " so a later edit_file can be
    # hash-anchored (reject stale writes). See tools/hashline.py.
    if inp.get("annotate"):
        text = annotate(_normalize_newlines(text))
    if truncated:
        text += (f"\n\n[truncated at {offset + len(window)} of {len(data)} "
                 f"bytes; continue with offset={offset + len(window)}]")
    return ToolResult(text)


def _edit_file(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Apply hash-anchored line edits — only if each line still matches the hash
    the agent saw (read the file with annotate=true first). All-or-nothing."""
    path = _resolve(ctx, inp.get("path", ""))
    blocked = _control_plane_error(path, ctx)
    if blocked:
        if not blocked.startswith("integrity-protected:"):
            blocked = f"approval-required[control_plane]: {blocked}"
        return ToolResult(blocked, is_error=True)
    edits = inp.get("edits") or []
    if not isinstance(edits, list) or not edits:
        return ToolResult("Provide a non-empty 'edits' list "
                          "({line, hash, new}).", is_error=True)
    try:
        target = open_existing(
            path,
            writable=True,
            policy=lambda opened: _control_plane_error(opened, ctx),
        )
        identity_blocked = _integrity_target_error(target)
        if identity_blocked:
            close_target(target)
            return ToolResult(identity_blocked, is_error=True)
    except UnsafeTargetError as exc:
        blocked = str(exc.strerror)
        if not blocked.startswith("integrity-protected:"):
            blocked = f"approval-required[control_plane]: {blocked}"
        return ToolResult(blocked, is_error=True)
    except PermissionError:
        raise
    except OSError:
        return ToolResult(f"No such file: {path}", is_error=True)
    try:
        original = _normalize_newlines(
            read_bytes(target).decode("utf-8", "replace")
        )
        new_text, errors = edit_text(original, edits)
        if errors:
            return ToolResult(
                "Edit rejected — file left UNCHANGED:\n- "
                + "\n- ".join(errors)
                + "\nRe-read the file with read_file annotate=true for fresh hashes.",
                is_error=True,
            )
        replace_bytes_atomic(
            target,
            new_text.encode("utf-8"),
            lambda opened: _control_plane_error(opened, ctx),
        )
    finally:
        close_target(target)
    applied = f"Applied {len(edits)} edit(s) to {path}."
    # Say whether the file still compiles, while the agent is still on
    # this turn. Off unless lsp_servers maps the suffix, and a server
    # that will not start costs the edit nothing -- the write already
    # succeeded. Only NEW problems: a file that arrived with ten
    # warnings must not blame all ten on this edit.
    from ..lsp import diagnostics as _diagnostics
    return ToolResult(applied + _diagnostics.report_for(
        path, new_text, ctx.cfg, baseline_text=original))


def _write_file(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
    path = _resolve(ctx, inp.get("path", ""))
    blocked = _control_plane_error(path, ctx)
    if blocked:
        if not blocked.startswith("integrity-protected:"):
            blocked = f"approval-required[control_plane]: {blocked}"
        return ToolResult(blocked, is_error=True)
    content = inp.get("content", "")
    try:
        target = open_for_write(
            path,
            lambda opened: _control_plane_error(opened, ctx),
        )
        identity_blocked = _integrity_target_error(target)
        if identity_blocked:
            close_target(target)
            return ToolResult(identity_blocked, is_error=True)
    except UnsafeTargetError as exc:
        blocked = str(exc.strerror)
        if not blocked.startswith("integrity-protected:"):
            blocked = f"approval-required[control_plane]: {blocked}"
        return ToolResult(blocked, is_error=True)
    except PermissionError:
        raise
    except OSError as exc:
        return ToolResult(f"Unsafe file path: {exc}", is_error=True)
    try:
        replace_bytes(target, content.encode("utf-8"))
    finally:
        close_target(target)
    return ToolResult(f"Wrote {len(content)} chars to {path}")


def _list_files(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
    base = _resolve(ctx, inp.get("path", "."))
    blocked = _integrity_plane_error(base)
    if blocked:
        return ToolResult(blocked, is_error=True)
    if not base.exists():
        return ToolResult(f"No such path: {base}", is_error=True)
    if base.is_file():
        try:
            target = open_existing(
                base,
                writable=False,
                policy=_integrity_plane_error,
            )
        except (UnsafeTargetError, OSError) as exc:
            if isinstance(exc, PermissionError):
                raise
            return ToolResult(str(exc), is_error=True)
        close_target(target)
        return ToolResult(str(base))
    depth = int(inp.get("depth", 1))
    try:
        return ToolResult(
            render_tree(
                base,
                depth=depth,
                policy=_integrity_plane_error,
            )
        )
    except (UnsafeTargetError, OSError) as exc:
        if isinstance(exc, PermissionError):
            raise
        return ToolResult(str(exc), is_error=True)


def tools() -> list[Tool]:
    return [
        Tool(
            name="read_file",
            description="Read a UTF-8 text file relative to the workspace. "
                        "Large files are read in windows — pass offset to "
                        "continue past a truncation point. Set annotate=true to "
                        "tag each line '{n}#{hash}| ' for a later hash-anchored "
                        "edit_file (annotate cannot be used with offset).",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "offset": {"type": "integer", "description":
                               "Byte offset to start reading from (default 0)"},
                    "annotate": {"type": "boolean", "description":
                                 "Prefix lines with {n}#{hash}| for edit_file"},
                },
                "required": ["path"],
            },
            fn=_read_file,
        ),
        Tool(
            name="edit_file",
            description="Apply line edits that REJECT stale writes: each edit must "
                        "carry the line's current #hash (from read_file annotate=true). "
                        "All-or-nothing — if any hash is stale the file is untouched.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "edits": {
                        "type": "array",
                        "description": "Edits to apply",
                        "items": {
                            "type": "object",
                            "properties": {
                                "line": {"type": "integer", "description": "1-indexed line no."},
                                "hash": {"type": "string", "description": "the #hash you saw"},
                                "new": {"type": "string", "description": "replacement line text"},
                            },
                            "required": ["line", "hash", "new"],
                        },
                    },
                },
                "required": ["path", "edits"],
            },
            fn=_edit_file,
        ),
        Tool(
            name="write_file",
            description="Create or overwrite a text file (parent dirs are "
                        "created automatically).",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            fn=_write_file,
        ),
        Tool(
            name="list_files",
            description="List files/directories under a path (default '.').",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "depth": {"type": "integer", "description": "Recursion depth (default 1)"},
                },
            },
            fn=_list_files,
        ),
    ]
