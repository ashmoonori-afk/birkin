"""Where a skill comes from, behind one protocol.

``hub.py`` installs from GitHub through quarantine, a security scan and an
audit log, and says plainly why it carries only that one source: hermes'
"ten source adapters, a tap registry and an index cache" are not needed to
install a skill you can already name. That judgement still stands, and none of
that machinery is ported here.

What it did not cover is the *identifier*. ``parse_identifier`` understands
``owner/repo`` and raises on anything else, so a skill sitting in a directory
on this disk -- one the user wrote, or a colleague handed over on a USB stick --
could not be installed at all. Not because installing it is unsafe: quarantine,
scan and audit are the safety boundary, and they are identical whichever way
the bytes arrived. It simply had no way in.

Three sources, one protocol, the same boundary behind all of them.

Search is honest about what each source can answer: a local skills directory
can be searched because it is right there, one URL is one skill with no index
behind it, and GitHub's code search needs the authenticated index this module
deliberately does not carry.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from . import hub

# Support directories a bundle may carry, mirroring hub.SUPPORT_DIRS so a
# locally-installed skill and a fetched one hold the same shape.
_SUPPORT_DIRS = hub.SUPPORT_DIRS


@dataclass(frozen=True, slots=True)
class SkillMeta:
    """What a search knows about a skill before anything is downloaded."""
    name: str
    description: str
    source_id: str


def _name_and_description(skill_md: str, fallback: str) -> tuple[str, str]:
    from .frontmatter import parse
    meta, _body = parse(skill_md)
    name = str(meta.get("name") or fallback).strip()
    return name, str(meta.get("description", "")).strip()


class SkillSource:
    """A place skills come from.

    ``root`` is accepted by every ``search`` and used only by the local source;
    the others have no directory to look in. Keeping one signature is what lets
    a caller hold a source without knowing which one it got.
    """

    def source_id(self) -> str:
        raise NotImplementedError

    def probe_name(self, identifier: str) -> str:
        """The skill name implied by the identifier, before any download."""
        raise NotImplementedError

    def fetch(self, identifier: str, dest: Path) -> dict[str, Any]:
        """Put the bundle in ``dest``; return its manifest."""
        raise NotImplementedError

    def search(self, query: str, *, limit: int = 10,
               root: Optional[Path] = None) -> list[SkillMeta]:
        return []


class GitHubSource(SkillSource):
    """The original source: ``owner/repo[/path]`` through the Contents API."""

    def source_id(self) -> str:
        return "github"

    def probe_name(self, identifier: str) -> str:
        _owner, repo, path = hub.parse_identifier(identifier)
        return path.split("/")[-1] if path else repo

    def fetch(self, identifier: str, dest: Path) -> dict[str, Any]:
        return hub.fetch_bundle(identifier, dest)

    def search(self, query: str, *, limit: int = 10,
               root: Optional[Path] = None) -> list[SkillMeta]:
        """Nothing, deliberately.

        GitHub code search needs an authenticated index, which is the piece
        hub.py declines to carry. Returning nothing is honest; guessing repo
        names would not be.
        """
        return []


class LocalSource(SkillSource):
    """A skill directory already on this disk."""

    def source_id(self) -> str:
        return "local"

    def probe_name(self, identifier: str) -> str:
        return Path(identifier).expanduser().resolve().name

    def fetch(self, identifier: str, dest: Path) -> dict[str, Any]:
        src = Path(identifier).expanduser().resolve()
        skill_md_path = src / "SKILL.md"
        if skill_md_path.is_symlink():
            raise hub.HubError(f"SKILL.md is a link: {skill_md_path}")
        if not skill_md_path.is_file():
            raise hub.HubError(f"no SKILL.md in {src}")
        skill_md = skill_md_path.read_text(encoding="utf-8", errors="replace")
        name, description = _name_and_description(skill_md, src.name)
        if not hub.valid_skill_name(name):
            raise hub.HubError(f"unsafe skill name: {name!r}")

        dest.mkdir(parents=True, exist_ok=True)
        (dest / "SKILL.md").write_text(skill_md, encoding="utf-8")
        files = ["SKILL.md"]
        for folder in _SUPPORT_DIRS:
            origin = src / folder
            if not origin.is_dir():
                continue
            for path in sorted(origin.rglob("*")):
                rel = path.relative_to(src).as_posix()
                # Refuse the link itself, the way guard.py's escape-symlink
                # check does: copying its content would turn a file outside
                # the bundle into an ordinary trusted file in quarantine,
                # where every later scan sees only the copy.
                if path.is_symlink() or not path.resolve().is_relative_to(src):
                    raise hub.HubError(f"support file leaves the bundle: {rel}")
                if not path.is_file():
                    continue
                if hub.safe_relpath(rel) is None:
                    raise hub.HubError(f"support file escapes the bundle: {rel}")
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                files.append(rel)
                if len(files) > hub.MAX_SUPPORT_FILES:
                    raise hub.HubError(
                        f"bundle carries more than {hub.MAX_SUPPORT_FILES} files")
        return {"identifier": identifier, "files": files,
                "name": name, "description": description}

    def search(self, query: str, *, limit: int = 10,
               root: Optional[Path] = None) -> list[SkillMeta]:
        """Skills under ``root`` whose name or description mentions ``query``."""
        from .. import config
        base = Path(root) if root is not None else config.user_skills_dir()
        needle = (query or "").strip().lower()
        found: list[SkillMeta] = []
        if not base.is_dir():
            return found
        for skill_md in sorted(base.glob("*/SKILL.md")):
            text = skill_md.read_text(encoding="utf-8", errors="replace")
            name, description = _name_and_description(text, skill_md.parent.name)
            if needle and needle not in f"{name} {description}".lower():
                continue
            found.append(SkillMeta(name, description, self.source_id()))
            if len(found) >= limit:
                break
        return found


class UrlSource(SkillSource):
    """One https URL pointing straight at a SKILL.md."""

    def source_id(self) -> str:
        return "url"

    def probe_name(self, identifier: str) -> str:
        parts = [p for p in identifier.split("?")[0].split("/") if p]
        return parts[-2] if len(parts) >= 2 else "skill"

    def fetch(self, identifier: str, dest: Path) -> dict[str, Any]:
        if not identifier.lower().startswith("https://"):
            raise hub.HubError(
                "a skill must arrive over https: its SKILL.md becomes "
                "instructions the agent follows")
        skill_md = hub._get(identifier, raw=True).decode("utf-8", "replace")
        name, description = _name_and_description(
            skill_md, self.probe_name(identifier))
        if not hub.valid_skill_name(name):
            raise hub.HubError(f"unsafe skill name: {name!r}")
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "SKILL.md").write_text(skill_md, encoding="utf-8")
        return {"identifier": identifier, "files": ["SKILL.md"],
                "name": name, "description": description}

    def search(self, query: str, *, limit: int = 10,
               root: Optional[Path] = None) -> list[SkillMeta]:
        """Nothing: one URL is one skill, with no index behind it to query."""
        return []


def source_for(identifier: str) -> SkillSource:
    """Pick the source an identifier names.

    A path is only local when it actually exists. Otherwise a typo'd
    ``owner/repo`` would become a baffling "no SKILL.md here" instead of the
    GitHub 404 the user is expecting.
    """
    text = (identifier or "").strip()
    if text.lower().startswith(("https://", "http://")):
        return UrlSource()
    try:
        if Path(text).expanduser().is_dir():
            return LocalSource()
    except OSError:
        pass
    return GitHubSource()
