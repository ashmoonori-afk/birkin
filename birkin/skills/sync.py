"""Mirror upstream skills (e.g. hermes) into the user skills directory.

Copies each ``SKILL.md`` folder (with its bundled ``scripts``/``references``/
``templates``) into ``~/.birkin/skills/mirrors/<category>/<name>/`` and appends a
source-attribution line. Existing mirrors are skipped unless ``force``.
Standard library only.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .. import config

_ATTRIB = "_Mirrored by `birkin skills sync`"
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".git", "node_modules")


def autodetect_sources() -> list[Path]:
    """Likely local upstream skill trees (hermes), if installed."""
    home = Path.home()
    candidates = [
        home / ".hermes" / "skills",
        home / "AppData" / "Local" / "hermes" / "hermes-agent" / "skills",
        home / ".local" / "share" / "hermes" / "skills",
    ]
    return [c for c in candidates if c.is_dir()]


def sync_skills(source: Path, limit: int | None = None,
                force: bool = False) -> list[str]:
    """Mirror skills from ``source`` into the user mirrors dir. Returns the list
    of relative skill paths that were copied."""
    source = Path(source)
    if not source.is_dir():
        raise NotADirectoryError(source)
    dest_root = config.user_skills_dir() / "mirrors"
    synced: list[str] = []
    rejected: list[str] = []
    for skill_md in sorted(source.rglob("SKILL.md")):
        rel = skill_md.parent.relative_to(source)
        dest = dest_root / rel
        if dest.exists() and not force:
            continue
        shutil.copytree(skill_md.parent, dest, dirs_exist_ok=True, ignore=_IGNORE)
        _attribute(dest / "SKILL.md", skill_md.parent)
        # A mirrored SKILL.md becomes instructions the agent follows, so
        # scan it here too — this path used to copy third-party text in
        # with nothing looking at it.
        from . import guard
        verdict = guard.scan_skill(dest, source="community")
        if verdict.verdict == "dangerous":
            shutil.rmtree(dest, ignore_errors=True)
            rejected.append(rel.as_posix())
            continue
        synced.append(rel.as_posix())
        if limit and len(synced) >= limit:
            break
    for name in rejected:
        print(f"[birkin] skipped {name}: the security scan flagged it "
              f"as dangerous (run `birkin skills scan` to see why).")
    return synced


def _attribute(skill_md: Path, origin: Path) -> None:
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    if _ATTRIB in text:
        return
    try:
        skill_md.write_text(
            text.rstrip() + f"\n\n---\n{_ATTRIB} from `{origin}`._\n",
            encoding="utf-8")
    except OSError:
        pass
