"""Mirror upstream skills (e.g. hermes) into the user skills directory.

Copies each ``SKILL.md`` folder (with its bundled ``scripts``/``references``/
``templates``) into ``~/.birkin/skills/mirrors/<category>/<name>/`` and appends a
source-attribution line. Existing mirrors are skipped unless ``force``.
Standard library only.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .. import config
from .bundle_publish import (
    UnsafeBundleError,
    publish_bundle,
    snapshot_bundle,
)

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
    target_root = config.user_skills_dir().absolute()
    synced: list[str] = []
    rejected: list[str] = []
    for skill_md in sorted(source.rglob("SKILL.md")):
        rel = skill_md.parent.relative_to(source)
        with tempfile.TemporaryDirectory(
            prefix=".sync-",
        ) as staging_root:
            staging = Path(staging_root)
            candidate = staging / "candidate"
            shutil.copytree(
                skill_md.parent,
                candidate,
                symlinks=True,
                ignore=_IGNORE,
            )
            candidate_skill = candidate / "SKILL.md"
            if candidate_skill.is_symlink():
                rejected.append(rel.as_posix())
                continue
            _attribute(candidate_skill, skill_md.parent)
            # Preserve links until after the policy decision so an escaping
            # source symlink cannot become an ordinary trusted file.
            from . import guard
            try:
                snapshot = snapshot_bundle(candidate)
            except UnsafeBundleError:
                rejected.append(rel.as_posix())
                continue
            verdict = guard.scan_skill(
                candidate,
                source="community",
                file_overrides=snapshot.file_overrides(),
            )
            if guard.should_allow_install(verdict) is not True:
                rejected.append(rel.as_posix())
                continue
            installed = publish_bundle(
                snapshot,
                target_root / "mirrors" / rel,
                target_root=target_root,
                replace=force,
            )
            if not installed:
                continue
        synced.append(rel.as_posix())
        if limit and len(synced) >= limit:
            break
    for name in rejected:
        print(f"[birkin] skipped {name}: the security scan flagged it "
              f"and install policy rejected it "
              f"(run `birkin skills scan` to see why).")
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
