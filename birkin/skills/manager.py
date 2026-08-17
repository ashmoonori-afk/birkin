"""SkillManager: index skills for the prompt, load them on demand, and let the
agent author/refine its own skills (the self-improvement substrate).

The model sees only a compact *index* (name + one-line description) in its
system prompt. When a skill is relevant it calls ``load_skill`` to pull the
full instructions into context — the same progressive-disclosure pattern used
by hermes and the agentskills standard.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from .. import config, store
from .loader import Skill, discover


class SkillProposalError(RuntimeError):
    pass


class IndeterminatePublicationError(SkillProposalError):
    def __init__(self, operation: str, candidate_sha256: str):
        self.operation = operation
        self.operation_id = operation
        self.candidate_sha256 = candidate_sha256
        self.retry_safe = False
        super().__init__(
            "skill publication outcome is indeterminate "
            f"(operation={operation}, sha256={candidate_sha256}); "
            "do not retry until the target is reconciled"
        )


class SkillManager:
    def __init__(self, dirs: list[tuple[Path, str]]):
        self._dirs = dirs
        self.skills: dict[str, Skill] = discover(dirs)
        self._sig = self._signature()
        self._checked_at = time.monotonic()
        self._revision = 0

    @property
    def revision(self) -> int:
        return self._revision

    def reload(self) -> None:
        self.skills = discover(self._dirs)
        self._sig = self._signature()
        self._revision += 1

    def _signature(self) -> tuple[tuple[str, float], ...]:
        """Cheap fingerprint (paths + mtimes, no file reads) for hot-reload."""
        items: list[tuple[str, float]] = []
        for base, _src in self._dirs:
            if base and base.is_dir():
                for f in base.rglob("SKILL.md"):
                    try:
                        items.append((str(f), f.stat().st_mtime))
                    except OSError:
                        continue
        return tuple(sorted(items))

    def reload_if_changed(self, debounce: float = 1.0) -> bool:
        """Reload skills if any SKILL.md changed/added/removed since last check.
        Debounced so it's cheap to call before every turn. Returns True if reloaded."""
        now = time.monotonic()
        if now - self._checked_at < debounce:
            return False
        self._checked_at = now
        sig = self._signature()
        if sig != self._sig:
            self.skills = discover(self._dirs)
            self._sig = sig
            self._revision += 1
            return True
        return False

    def get(self, name: str) -> Skill | None:
        if name in self.skills:
            return self.skills[name]
        low = name.lower()
        for n, s in self.skills.items():
            if n.lower() == low:
                return s
        return None

    def eligible_skills(self) -> list[Skill]:
        """Skills whose frontmatter prerequisites are met on this machine."""
        return [s for s in self.skills.values() if s.eligible]

    def index(self) -> str:
        """Compact catalog for the system prompt (eligible skills only)."""
        skills = self.eligible_skills()
        if not skills:
            return "(no skills installed yet)"
        lines = []
        for s in sorted(skills, key=lambda x: x.name):
            desc = s.description or "(no description)"
            lines.append(f"- {s.name}: {desc}")
        return "\n".join(lines)

    def route(self, query: str, limit: int = 3) -> list[Skill]:
        """Pick the most relevant *eligible* skills for a query by keyword overlap
        against name + description + tags + body. Used to inject skills into
        CLI-agent prompts (which can't call load_skill)."""
        terms = [t for t in re.findall(r"[^\W_]+", (query or "").lower())
                 if len(t) > 2 or (len(t) > 1 and not t.isascii())]
        skills = self.eligible_skills()
        if not terms or not skills:
            return []

        def matched_terms(text: str) -> list[str]:
            tokens = re.findall(r"[^\W_]+", text.lower())
            token_set = set(tokens)
            return [term for term in terms if (
                term in token_set if term.isascii()
                else any(term in token or token in term
                         for token in tokens if len(token) > 1)
            )]

        metadata_scored: list[tuple[int, int, int, Skill]] = []
        for s in skills:
            hay = f"{s.name} {s.description} {' '.join(s.tags)}".lower()
            metadata_terms = matched_terms(hay)
            if metadata_terms:
                metadata_scored.append(
                    (max(len(t) for t in metadata_terms),
                     sum(len(t) for t in metadata_terms),
                     len(metadata_terms), s))
        if metadata_scored:
            metadata_scored.sort(
                key=lambda x: (x[0], x[1], x[2]), reverse=True)
            return [s for _, _, _, s in metadata_scored[:limit]]
        body_scored = []
        for s in skills:
            body_hits = len(matched_terms(s.body()))
            if body_hits:
                body_scored.append((body_hits, s))
        body_scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in body_scored[:limit]]

    def render_skill(self, skill: Skill) -> str:
        """Full skill text plus its bundled files + directory (for execution)."""
        directory = skill.directory.resolve()
        out = (f"# Skill: {skill.name}\n\n"
               f"Skill directory: `{directory}`\n\n{skill.body()}")
        extras = _bundled_files(directory)
        if extras:
            listing = "\n".join(f"- {p}" for p in extras)
            out += (f"\n\n## Bundled files (in this skill's directory)\n"
                    f"{listing}\n\n"
                    f"To run a bundled script, run it with the skill directory "
                    f"as the working directory (e.g. `python scripts/<name>.py ...`).")
        return out

    # -- tools -------------------------------------------------------------

    def tools(self, origin: str = "agent"):
        from ..tools import Tool, ToolContext, ToolResult

        def load_skill(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
            self.reload_if_changed(debounce=0.0)
            name = inp.get("name", "").strip()
            skill = self.get(name)
            if not skill:
                avail = ", ".join(sorted(self.skills)) or "(none)"
                return ToolResult(f"No skill named {name!r}. Available: {avail}",
                                  is_error=True)
            from ..curator import record_use
            record_use(skill.name)   # usage feeds the curator lifecycle
            return ToolResult(self.render_skill(skill))

        def create_skill(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
            if not ctx.cfg.get("self_improve", True):
                return ToolResult("Self-improvement is disabled in config.",
                                  is_error=True)
            name = inp.get("name", "").strip()
            desc = inp.get("description", "").strip()
            body = inp.get("body", "").strip()
            if not (name and desc and body):
                return ToolResult("create_skill needs name, description, body.",
                                  is_error=True)
            canonical = _slug(name)
            if _skill_exists(canonical):
                return ToolResult(
                    f"Skill {canonical!r} already exists; use improve_skill.",
                    is_error=True)
            # Skill-PR: route through the approval gate so every authoring is
            # recorded. With `skills` in auto_approve (default), it's applied
            # immediately; otherwise it queues for `birkin review`.
            from .. import approvals
            res = approvals.propose(
                category="skill",
                title=f"new skill: {name}",
                description=desc,
                payload={"action": "create", "name": name, "description": desc,
                         "body": body, "tags": inp.get("tags") or []},
                cfg=ctx.cfg, origin=origin)
            if res.get("auto"):
                if not res.get("ok"):
                    return ToolResult(
                        f"Could not create skill {canonical!r}: "
                        f"{res.get('result', 'unknown error')}", is_error=True)
                self.reload()
                return ToolResult(f"Created skill {name!r} (auto-approved).")
            return ToolResult(
                f"Skill proposal recorded for {name!r} — awaiting approval "
                f"(id {res.get('id')}). Run `birkin review` to apply.")

        def improve_skill(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
            if not ctx.cfg.get("self_improve", True):
                return ToolResult("Self-improvement is disabled in config.",
                                  is_error=True)
            name = inp.get("name", "").strip()
            addition = inp.get("addition", "").strip()
            skill = self.get(name)
            if not skill:
                return ToolResult(f"No skill named {name!r}.", is_error=True)
            if not addition:
                return ToolResult("improve_skill needs 'addition'.", is_error=True)
            # Skill-PR: route through the approval gate (no silent in-place edits).
            from .. import approvals
            res = approvals.propose(
                category="skill",
                title=f"improve skill: {name}",
                description=addition[:160],
                payload={"action": "improve", "target": skill.name,
                         "addition": addition},
                cfg=ctx.cfg, origin=origin)
            if res.get("auto"):
                if not res.get("ok"):
                    return ToolResult(
                        f"Could not improve skill {name!r}: "
                        f"{res.get('result', 'unknown error')}", is_error=True)
                self.reload()
                return ToolResult(f"Appended a learned note to {name!r} (auto-approved).")
            return ToolResult(
                f"Improvement proposal recorded for {name!r} — awaiting "
                f"approval (id {res.get('id')}). Run `birkin review` to apply.")

        return [
            Tool(
                name="load_skill",
                description="Load the full instructions for a named skill from "
                            "the catalog. Call this whenever a listed skill is "
                            "relevant to the task.",
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
                fn=load_skill,
            ),
            Tool(
                name="create_skill",
                description="Author a NEW reusable skill from what you just "
                            "learned, so it persists for future sessions. Use "
                            "after solving a non-trivial, repeatable task.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "kebab-case name"},
                        "description": {"type": "string",
                                        "description": "One line; when to use it"},
                        "body": {"type": "string",
                                 "description": "Markdown instructions"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["name", "description", "body"],
                },
                fn=create_skill,
            ),
            Tool(
                name="improve_skill",
                description="Append a 'Learned' note to an existing skill to "
                            "refine it based on new experience.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "addition": {"type": "string"},
                    },
                    "required": ["name", "addition"],
                },
                fn=improve_skill,
            ),
        ]


def _guard_agent_written(
    path: Path,
    what: str,
) -> None:
    """Scan a staged skill before publishing it.

    Opt-in (``skills_guard_agent_created``) for the same reason hermes leaves
    it off: on the native loop the agent already has shell, so this catches a
    model that copied something hostile into a skill, not a determined agent.
    """
    if not config.load_config().get("skills_guard_agent_created"):
        return
    from . import guard
    result = guard.scan_skill(path.parent, source="agent-created")
    if guard.should_allow_install(result) is True:
        return
    raise SkillProposalError(
        f"{what} was rejected before publication — the security scan returned "
        f"{result.verdict}:\n{guard.format_report(result, path.parent.name)}")


def _canonical_skill_target(
    target: Path,
    roots: list[Path],
) -> tuple[Path, Path]:
    absolute_target = target.absolute()
    for root in roots:
        absolute_root = root.absolute()
        try:
            relative = absolute_target.relative_to(absolute_root)
        except ValueError:
            continue
        canonical_root = absolute_root.resolve()
        return canonical_root, canonical_root / relative
    raise SkillProposalError("skill improve target is outside configured roots")


def _open_directory_tree(root: Path) -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(root.anchor, flags)
    try:
        for part in root.parts[1:]:
            if part in {"", ".", ".."}:
                raise SkillProposalError(
                    "skill improve target has an unsafe path"
                )
            child = os.open(
                part,
                flags,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_descendant_directory(
    root_fd: int,
    relative: Path,
    *,
    create: bool = False,
) -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.dup(root_fd)
    try:
        for part in relative.parts:
            if part in {"", ".", ".."}:
                raise SkillProposalError(
                    "skill improve target has an unsafe path"
                )
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o700, dir_fd=descriptor)
                child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _verified_candidate_bytes(candidate: Path, what: str) -> bytes:
    if candidate.is_symlink():
        raise SkillProposalError("staged SKILL.md must not be a symlink")
    before = candidate.read_bytes()
    _guard_agent_written(candidate, what)
    if candidate.is_symlink():
        raise SkillProposalError("staged SKILL.md must not be a symlink")
    after = candidate.read_bytes()
    if not secrets.compare_digest(
        hashlib.sha256(before).digest(),
        hashlib.sha256(after).digest(),
    ):
        raise SkillProposalError(
            "staged SKILL.md changed during security review"
        )
    return after


def _write_all(descriptor: int, payload: bytes) -> None:
    written = 0
    while written < len(payload):
        written += os.write(descriptor, payload[written:])


def _zero_open_descriptor(descriptor: int) -> None:
    try:
        os.ftruncate(descriptor, 0)
    except OSError:
        remaining = os.fstat(descriptor).st_size
        offset = 0
        zeroes = bytes(min(remaining, 64 * 1024))
        while offset < remaining:
            chunk = zeroes[:min(len(zeroes), remaining - offset)]
            offset += os.pwrite(descriptor, chunk, offset)
    os.fsync(descriptor)


def _descriptor_path_is_target(
    descriptor: int,
    target_fd: int,
    target_name: str,
) -> bool | None:
    try:
        import fcntl
        descriptor_path = fcntl.fcntl(
            descriptor,
            50,
            bytes(1024),
        )
        target_path = fcntl.fcntl(
            target_fd,
            50,
            bytes(1024),
        )
        descriptor_name = os.fsdecode(
            descriptor_path.split(b"\0", 1)[0]
        )
        target_directory = os.fsdecode(
            target_path.split(b"\0", 1)[0]
        )
    except (ImportError, OSError):
        try:
            descriptor_name = os.readlink(
                f"/proc/self/fd/{descriptor}"
            )
            target_directory = os.readlink(
                f"/proc/self/fd/{target_fd}"
            )
        except OSError:
            return None
    if Path(descriptor_name) == (
        Path(target_directory) / target_name
    ):
        return True
    return None


def _descriptor_is_target(
    descriptor: int,
    target_fd: int,
    target_name: str,
) -> bool | None:
    try:
        descriptor_stat = os.fstat(descriptor)
    except OSError:
        return _descriptor_path_is_target(
            descriptor,
            target_fd,
            target_name,
        )
    try:
        target_stat = os.stat(
            target_name,
            dir_fd=target_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return None
    except OSError:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            target_descriptor = os.open(
                target_name,
                flags,
                dir_fd=target_fd,
            )
        except FileNotFoundError:
            return None
        except OSError:
            return _descriptor_path_is_target(
                descriptor,
                target_fd,
                target_name,
            )
        try:
            try:
                target_stat = os.fstat(target_descriptor)
            except OSError:
                return _descriptor_path_is_target(
                    descriptor,
                    target_fd,
                    target_name,
                )
        finally:
            os.close(target_descriptor)
    if (
        descriptor_stat.st_dev,
        descriptor_stat.st_ino,
    ) == (
        target_stat.st_dev,
        target_stat.st_ino,
    ):
        return True
    return None


def _publish_skill_bytes_posix(
    payload: bytes,
    target: Path,
    target_root: Path,
    root_fd: int,
) -> None:
    relative_parent = target.parent.relative_to(target_root)
    target_fd = _open_descendant_directory(
        root_fd,
        relative_parent,
        create=True,
    )
    temporary = f".birkin-publish-{secrets.token_hex(12)}.tmp"
    temporary_fd = -1
    published = False
    indeterminate = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        temporary_fd = os.open(
            temporary,
            flags,
            0o600,
            dir_fd=target_fd,
        )
        try:
            rename_started = False
            try:
                _write_all(temporary_fd, payload)
                os.fsync(temporary_fd)
                rename_started = True
                os.replace(
                    temporary,
                    target.name,
                    src_dir_fd=target_fd,
                    dst_dir_fd=target_fd,
                )
                published = True
            except BaseException as error:
                if rename_started:
                    try:
                        target_state = _descriptor_is_target(
                            temporary_fd,
                            target_fd,
                            target.name,
                        )
                    except BaseException:
                        target_state = None
                    if target_state is True:
                        published = True
                    elif target_state is None:
                        indeterminate = True
                        digest = hashlib.sha256(payload).hexdigest()
                        raise IndeterminatePublicationError(
                            temporary,
                            digest,
                        ) from error
                raise
        finally:
            if not published and not indeterminate:
                _zero_open_descriptor(temporary_fd)
    finally:
        if temporary_fd >= 0:
            os.close(temporary_fd)
        if not indeterminate:
            try:
                os.unlink(temporary, dir_fd=target_fd)
            except FileNotFoundError:
                pass
        os.close(target_fd)


def _windows_kernel32() -> Any:
    import ctypes
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _zero_windows_handle(
    kernel32: Any,
    handle: Any,
    length: int,
) -> int:
    import ctypes
    from ctypes import wintypes

    new_position = ctypes.c_longlong()
    if not kernel32.SetFilePointerEx(
        handle,
        ctypes.c_longlong(0),
        ctypes.byref(new_position),
        0,
    ):
        return ctypes.get_last_error()
    remaining = length
    zeroes = bytes(min(remaining, 64 * 1024))
    while remaining:
        chunk = zeroes[:min(len(zeroes), remaining)]
        buffer = ctypes.create_string_buffer(chunk)
        written = wintypes.DWORD()
        if not kernel32.WriteFile(
            handle,
            buffer,
            len(chunk),
            ctypes.byref(written),
            None,
        ):
            return ctypes.get_last_error()
        if written.value != len(chunk):
            return 29
        remaining -= written.value
    if not kernel32.FlushFileBuffers(handle):
        return ctypes.get_last_error()
    return 0


def _windows_handle_is_target(
    kernel32: Any,
    handle: Any,
    target: Path,
) -> bool | None:
    import ctypes
    from ctypes import wintypes

    length = kernel32.GetFinalPathNameByHandleW(
        handle,
        None,
        0,
        0,
    )
    def normalize(path: str) -> str:
        if path.startswith("\\\\?\\UNC\\"):
            path = "\\\\" + path[8:]
        elif path.startswith("\\\\?\\"):
            path = path[4:]
        return os.path.normcase(os.path.normpath(path))

    if length:
        buffer = ctypes.create_unicode_buffer(length + 1)
        if kernel32.GetFinalPathNameByHandleW(
            handle,
            buffer,
            len(buffer),
            0,
        ):
            if normalize(buffer.value) == normalize(
                str(target.absolute())
            ):
                return True
            return None

    class FileNameInfo(ctypes.Structure):
        _fields_ = [
            ("FileNameLength", wintypes.DWORD),
            ("FileName", wintypes.WCHAR * 1),
        ]

    filename_offset = FileNameInfo.FileName.offset
    info_buffer = ctypes.create_string_buffer(
        filename_offset + 64 * 1024
    )
    if not kernel32.GetFileInformationByHandleEx(
        handle,
        2,
        info_buffer,
        len(info_buffer),
    ):
        return None
    info = FileNameInfo.from_buffer(info_buffer)
    filename = bytes(info_buffer)[
        filename_offset:filename_offset + info.FileNameLength
    ].decode("utf-16-le")
    _, target_tail = os.path.splitdrive(str(target.absolute()))
    if normalize(filename) == normalize(target_tail):
        return True
    return None


def _publish_skill_bytes_windows(
    payload: bytes,
    target: Path,
    target_root: Path,
) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = _windows_kernel32()
    create_file = kernel32.CreateFileW
    create_file.restype = wintypes.HANDLE
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    close_handle = kernel32.CloseHandle
    invalid_handle = wintypes.HANDLE(-1).value
    file_read_attributes = 0x0080
    delete_access = 0x00010000
    generic_write = 0x40000000
    share_read = 0x00000001
    share_write = 0x00000002
    open_existing = 3
    create_new = 1
    backup_semantics = 0x02000000
    open_reparse_point = 0x00200000
    temporary_attribute = 0x00000100
    reparse_attribute = 0x00000400

    handles: list[int] = []

    def open_handle(
        path: Path,
        access: int,
        share: int,
        creation: int,
        flags: int,
    ) -> int:
        handle = create_file(
            str(path),
            access,
            share,
            None,
            creation,
            flags,
            None,
        )
        if handle == invalid_handle:
            raise OSError(ctypes.get_last_error(), str(path))
        return int(handle)

    try:
        current = Path(target_root.anchor)
        for part in (*target_root.parts[1:], *target.parent.relative_to(
                target_root).parts):
            current /= part
            if not current.exists():
                if not kernel32.CreateDirectoryW(str(current), None):
                    raise OSError(ctypes.get_last_error(), str(current))
            handle = open_handle(
                current,
                file_read_attributes,
                share_read | share_write,
                open_existing,
                backup_semantics | open_reparse_point,
            )

            class FileAttributeTagInfo(ctypes.Structure):
                _fields_ = [
                    ("FileAttributes", wintypes.DWORD),
                    ("ReparseTag", wintypes.DWORD),
                ]

            tag_info = FileAttributeTagInfo()
            if not kernel32.GetFileInformationByHandleEx(
                wintypes.HANDLE(handle),
                9,
                ctypes.byref(tag_info),
                ctypes.sizeof(tag_info),
            ):
                close_handle(wintypes.HANDLE(handle))
                raise OSError(ctypes.get_last_error(), str(current))
            if tag_info.FileAttributes & reparse_attribute:
                close_handle(wintypes.HANDLE(handle))
                raise SkillProposalError(
                    "skill improve target contains a reparse point"
                )
            handles.append(handle)

        temporary = target.parent / (
            f".birkin-publish-{secrets.token_hex(12)}.tmp"
        )
        source_handle = open_handle(
            temporary,
            generic_write | delete_access,
            0,
            create_new,
            temporary_attribute,
        )
        published = False
        rename_started = False
        indeterminate = False
        try:
            payload_buffer = ctypes.create_string_buffer(payload)
            written = wintypes.DWORD()
            if not kernel32.WriteFile(
                wintypes.HANDLE(source_handle),
                payload_buffer,
                len(payload),
                ctypes.byref(written),
                None,
            ):
                raise OSError(ctypes.get_last_error(), str(temporary))
            if written.value != len(payload):
                raise OSError("short Windows skill publication write")
            if not kernel32.FlushFileBuffers(
                wintypes.HANDLE(source_handle)
            ):
                raise OSError(ctypes.get_last_error(), str(temporary))

            class FileRenameInfo(ctypes.Structure):
                _fields_ = [
                    ("ReplaceIfExists", wintypes.BOOLEAN),
                    ("RootDirectory", wintypes.HANDLE),
                    ("FileNameLength", wintypes.DWORD),
                    ("FileName", wintypes.WCHAR * 1),
                ]

            encoded_name = target.name.encode("utf-16-le")
            filename_offset = FileRenameInfo.FileName.offset
            buffer = ctypes.create_string_buffer(
                filename_offset + len(encoded_name)
            )
            rename_info = FileRenameInfo.from_buffer(buffer)
            rename_info.ReplaceIfExists = True
            rename_info.RootDirectory = wintypes.HANDLE(handles[-1])
            rename_info.FileNameLength = len(encoded_name)
            ctypes.memmove(
                ctypes.addressof(buffer) + filename_offset,
                encoded_name,
                len(encoded_name),
            )
            rename_started = True
            if not kernel32.SetFileInformationByHandle(
                wintypes.HANDLE(source_handle),
                3,
                buffer,
                len(buffer),
            ):
                rename_started = False
                raise OSError(ctypes.get_last_error(), str(target))
            published = True
        finally:
            cleanup_error = 0
            disposition_failed = False
            if not published and rename_started:
                try:
                    target_state = _windows_handle_is_target(
                        kernel32,
                        wintypes.HANDLE(source_handle),
                        target,
                    )
                except BaseException:
                    target_state = None
                if target_state is True:
                    published = True
                elif target_state is None:
                    indeterminate = True
            if not published and not indeterminate:
                class FileDispositionInfo(ctypes.Structure):
                    _fields_ = [("DeleteFile", wintypes.BOOLEAN)]

                disposition = FileDispositionInfo(True)
                if not kernel32.SetFileInformationByHandle(
                    wintypes.HANDLE(source_handle),
                    4,
                    ctypes.byref(disposition),
                    ctypes.sizeof(disposition),
                ):
                    cleanup_error = ctypes.get_last_error()
                    disposition_failed = True
                    class FileEndOfFileInfo(ctypes.Structure):
                        _fields_ = [
                            ("EndOfFile", ctypes.c_longlong),
                        ]

                    end_of_file = FileEndOfFileInfo(0)
                    if not kernel32.SetFileInformationByHandle(
                        wintypes.HANDLE(source_handle),
                        6,
                        ctypes.byref(end_of_file),
                        ctypes.sizeof(end_of_file),
                    ):
                        cleanup_error = _zero_windows_handle(
                            kernel32,
                            wintypes.HANDLE(source_handle),
                            len(payload),
                        )
                    elif not kernel32.FlushFileBuffers(
                        wintypes.HANDLE(source_handle)
                    ):
                        cleanup_error = ctypes.get_last_error()
            close_handle(wintypes.HANDLE(source_handle))
            if disposition_failed and not indeterminate:
                if kernel32.DeleteFileW(str(temporary)):
                    cleanup_error = 0
                elif ctypes.get_last_error() in {2, 3}:
                    cleanup_error = 0
            if indeterminate:
                digest = hashlib.sha256(payload).hexdigest()
                raise IndeterminatePublicationError(
                    temporary.name,
                    digest,
                )
            if cleanup_error:
                raise OSError(cleanup_error, str(temporary))
    finally:
        for handle in reversed(handles):
            close_handle(wintypes.HANDLE(handle))


def _publish_skill_bytes(
    payload: bytes,
    target: Path,
    target_root: Path,
    root_fd: int | None,
) -> None:
    if os.name == "nt":
        _publish_skill_bytes_windows(payload, target, target_root)
        return
    if root_fd is None:
        raise SkillProposalError(
            "anchored skill publication is unavailable"
        )
    _publish_skill_bytes_posix(
        payload,
        target,
        target_root,
        root_fd,
    )


def apply_skill_proposal(payload: dict[str, Any]) -> str:
    """Carry out an approved skill change (create / improve). Returns a human
    summary. Used by ``approvals.execute_action(category="skill")``."""
    action = (payload or {}).get("action")
    from ..persistence_safety import unsafe_persistence_reason
    unsafe = unsafe_persistence_reason(
        payload.get("name"), payload.get("description"),
        payload.get("body"), payload.get("addition"))
    if unsafe:
        raise SkillProposalError(unsafe)
    if action == "create":
        name = payload.get("name", "").strip()
        desc = payload.get("description", "").strip()
        body = payload.get("body", "").strip()
        if not (name and desc and body):
            raise SkillProposalError(
                "skill create proposal missing name/description/body")
        canonical = _slug(name)
        path = _user_skill_path(canonical, create=False)
        target_root, path = _canonical_skill_target(
            path,
            [config.user_skills_dir()],
        )
        try:
            with store.file_lock(_proposal_lock_path(canonical)):
                if _skill_exists(canonical):
                    raise SkillProposalError(f"skill already exists: {canonical}")
                root_fd = (
                    None
                    if os.name == "nt"
                    else _open_directory_tree(target_root)
                )
                try:
                    with tempfile.TemporaryDirectory(
                        prefix=".proposal-",
                    ) as staging_name:
                        staging = Path(staging_name)
                        candidate_dir = staging / canonical
                        candidate_dir.mkdir()
                        candidate = candidate_dir / "SKILL.md"
                        candidate.write_text(
                            _render_skill(
                                name,
                                desc,
                                body,
                                payload.get("tags") or [],
                            ),
                            encoding="utf-8",
                        )
                        verified = _verified_candidate_bytes(
                            candidate,
                            f"skill {name!r}",
                        )
                        _publish_skill_bytes(
                            verified,
                            path,
                            target_root,
                            root_fd,
                        )
                finally:
                    if root_fd is not None:
                        os.close(root_fd)
        except store.FileLockTimeout:
            raise SkillProposalError("skill store is busy") from None
        return f"Created skill {name!r} at {path}"
    if action == "improve":
        target_name = payload.get("target", "").strip()
        addition = payload.get("addition", "").strip()
        if not (target_name and addition):
            raise SkillProposalError(
                "skill improve proposal missing target/addition")
        lock_path = _proposal_lock_path(target_name)
        try:
            with store.file_lock(lock_path):
                dirs = config.skill_dirs(config.load_config())
                skill = discover(dirs).get(target_name)
                if skill is None:
                    raise SkillProposalError(f"skill not found: {target_name}")
                target = (
                    _user_skill_path(skill.name, create=False)
                    if skill.source == "bundled"
                    else skill.path
                )
                roots = (
                    [config.user_skills_dir()]
                    if skill.source == "bundled"
                    else [directory for directory, _source in dirs]
                )
                target_root, target = _canonical_skill_target(
                    target,
                    roots,
                )
                if target.is_symlink() or target.parent.is_symlink():
                    raise SkillProposalError(
                        "skill improve target must not be a symlink"
                    )
                root_fd = (
                    None
                    if os.name == "nt"
                    else _open_directory_tree(target_root)
                )
                try:
                    with tempfile.TemporaryDirectory(
                        prefix=".proposal-",
                    ) as staging_name:
                        staging = Path(staging_name)
                        candidate_dir = staging / target.parent.name
                        shutil.copytree(
                            skill.path.parent,
                            candidate_dir,
                            symlinks=True,
                        )
                        candidate = candidate_dir / "SKILL.md"
                        if candidate.is_symlink():
                            raise SkillProposalError(
                                "staged SKILL.md must not be a symlink"
                            )
                        with candidate.open("a", encoding="utf-8") as fh:
                            fh.write(
                                f"\n\n## Learned ({_today()})\n\n{addition}\n"
                            )
                        verified = _verified_candidate_bytes(
                            candidate,
                            f"skill {target_name!r}",
                        )
                        _publish_skill_bytes(
                            verified,
                            target,
                            target_root,
                            root_fd,
                        )
                finally:
                    if root_fd is not None:
                        os.close(root_fd)
        except store.FileLockTimeout:
            raise SkillProposalError("skill store is busy") from None
        return f"Appended learned note to {target_name!r}."
    raise SkillProposalError(f"unknown skill action: {action!r}")


def _bundled_files(directory: Path, limit: int = 40) -> list[str]:
    """Files bundled with a skill (scripts/references/templates), excluding the
    SKILL.md itself. Returned as POSIX-style paths relative to the skill dir."""
    out: list[str] = []
    try:
        for p in sorted(directory.rglob("*")):
            if p.is_file() and p.name != "SKILL.md" and "__pycache__" not in p.parts:
                out.append(p.relative_to(directory).as_posix())
                if len(out) >= limit:
                    break
    except OSError:
        pass
    return out


def _slug(name: str) -> str:
    """Canonical skill id — also the directory name and the lockfile path.

    Unicode-preserving (same semantics as ``mnemosyne.slug``): an ASCII-only
    filter collapsed every all-Hangul name to the fallback, so '번역 도우미'
    and '회의록 정리' claimed one directory and the second create failed as
    "already exists". The deterministic hash covers names that are pure
    punctuation — distinct inputs stay distinct, the same input stays stable.
    """
    s = re.sub(r"[^\w\s-]", "", name.strip().lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    if s:
        return s
    raw = name.strip()
    if not raw:
        return "skill"
    return "skill-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]


def _skill_exists(canonical: str) -> bool:
    direct = config.user_skills_dir() / canonical / "SKILL.md"
    if direct.is_file():
        return True
    skills = discover(config.skill_dirs(config.load_config())).values()
    return any(
        _slug(skill.name) == canonical
        or _slug(skill.directory.name) == canonical
        for skill in skills)


def _today() -> str:
    from datetime import date
    return date.today().isoformat()


def _user_skill_path(name: str, *, create: bool = True) -> Path:
    root = config.user_skills_dir().resolve()
    root.mkdir(parents=True, exist_ok=True)
    d = root / _slug(name)
    if create:
        d.mkdir(parents=True, exist_ok=True)
    resolved = d.resolve()
    if root != resolved and root not in resolved.parents:
        raise SkillProposalError("skill path escapes the user skills directory")
    return resolved / "SKILL.md"


def _proposal_lock_path(name: str) -> Path:
    root = config.user_skills_dir().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root / f".{_slug(name)}.proposal"


def _render_skill(
    name: str,
    description: str,
    body: str,
    tags: list[str],
) -> str:
    tag_block = "    tags: []\n" if not tags else (
        "    tags:\n" + "".join(
            f"      - {json.dumps(str(tag), ensure_ascii=False)}\n"
            for tag in tags))
    fm = (
        "---\n"
        f"name: {_slug(name)}\n"
        f"description: {json.dumps(description, ensure_ascii=False)}\n"
        "version: 1.0.0\n"
        "author: birkin (self-authored)\n"
        "metadata:\n"
        "  birkin:\n"
        f"{tag_block}"
        "---\n\n"
    )
    return fm + body.strip() + "\n"


def _write_skill(name: str, description: str, body: str, tags: list[str]) -> Path:
    path = _user_skill_path(name)
    path.write_text(
        _render_skill(name, description, body, tags),
        encoding="utf-8",
    )
    return path


def build_manager(cfg: dict[str, Any]) -> SkillManager:
    return SkillManager(config.skill_dirs(cfg))
