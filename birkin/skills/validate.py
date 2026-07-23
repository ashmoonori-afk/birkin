"""Skill integrity checks (P6 — approval-first & skill integrity).

A small, stdlib-only linter for the bundled and user skill catalogs:

- **Frontmatter lint** — every ``SKILL.md`` must have ``name`` and
  ``description``; soft-warn on missing ``version`` / ``license``.
- **Bundled-script compile** — every Python file shipped *inside* a skill
  directory (e.g. ``skills/research/arxiv/scripts/search_arxiv.py``) is run
  through :func:`py_compile.compile` so a broken script can't ride along into
  the catalog.
- **Required-section check** — the skill body must contain at least one
  ``## When to Use`` (or ``## When to use``) section so the agent has a routing
  signal beyond the one-line description.

Used by ``birkin skills validate``; returns a structured report that the CLI
formats. No network, no subprocesses — safe to run anywhere.
"""

from __future__ import annotations

import py_compile
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import frontmatter

REQUIRED_FIELDS = ("name", "description")
RECOMMENDED_FIELDS = ("version", "license")
WHEN_TO_USE_RE = re.compile(r"^##\s+when\s+to\s+use\s*$", re.IGNORECASE | re.MULTILINE)


@dataclass
class SkillReport:
    """One skill's validation outcome."""
    name: str
    path: Path
    source: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class ValidationSummary:
    reports: list[SkillReport]

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.reports)

    @property
    def n_errors(self) -> int:
        return sum(len(r.errors) for r in self.reports)

    @property
    def n_warnings(self) -> int:
        return sum(len(r.warnings) for r in self.reports)


def validate_skill(skill_md: Path, source: str = "user") -> SkillReport:
    """Validate one ``SKILL.md`` plus any bundled Python scripts next to it."""
    rep = SkillReport(name=skill_md.parent.name, path=skill_md, source=source)
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        rep.errors.append(f"cannot read SKILL.md: {exc}")
        return rep

    meta, body = frontmatter.extract_meta(text)
    if not isinstance(meta, dict):
        rep.errors.append("frontmatter is not a YAML mapping")
        return rep

    rep.name = str(meta.get("name") or skill_md.parent.name).strip() or rep.name

    for fld in REQUIRED_FIELDS:
        if not str(meta.get(fld) or "").strip():
            rep.errors.append(f"missing required frontmatter field: {fld!r}")
    for fld in RECOMMENDED_FIELDS:
        if not str(meta.get(fld) or "").strip():
            rep.warnings.append(f"missing recommended frontmatter field: {fld!r}")

    if not WHEN_TO_USE_RE.search(body or ""):
        # The section IS the routing signal, so a skill without one is
        # degraded either way. It is an ERROR for skills birkin ships — as a
        # warning this was reported and ignored until one shipped without it
        # — and a warning for the user's own skills, whose exit code is not
        # birkin's to fail.
        note = "no '## When to Use' section — agent routing degraded"
        (rep.errors if source == "bundled" else rep.warnings).append(note)

    # Compile every Python file in this skill's directory (bundled scripts).
    for py in skill_md.parent.rglob("*.py"):
        try:
            py_compile.compile(str(py), doraise=True)
        except py_compile.PyCompileError as exc:
            rep.errors.append(f"py_compile failed for {py.name}: {exc.msg.strip()}")
        except OSError as exc:
            rep.errors.append(f"cannot compile {py.name}: {exc}")

    return rep


def validate_dirs(dirs: list[tuple[Path, str]]) -> ValidationSummary:
    """Validate every ``SKILL.md`` under each ``(directory, source)`` pair."""
    reports: list[SkillReport] = []
    for base, source in dirs:
        if not base or not base.is_dir():
            continue
        for skill_md in sorted(base.rglob("SKILL.md")):
            reports.append(validate_skill(skill_md, source=source))
    return ValidationSummary(reports=reports)


def validate_all(cfg: dict | None = None) -> ValidationSummary:
    """Validate bundled + user + extra skill dirs from config."""
    from .. import config
    cfg = cfg or config.load_config()
    dirs = config.skill_dirs(cfg)
    return validate_dirs(dirs)


def format_summary(summary: ValidationSummary, *, verbose: bool = False) -> str:
    """Human-friendly text report (used by the CLI)."""
    lines = []
    bad = [r for r in summary.reports if not r.ok]
    warn_only = [r for r in summary.reports if r.ok and r.warnings]
    if not summary.reports:
        return "No skills found."
    for rep in bad:
        lines.append(f"✗ [{rep.source}] {rep.name}  ({rep.path})")
        for e in rep.errors:
            lines.append(f"    ERROR: {e}")
        for w in rep.warnings:
            lines.append(f"    warn:  {w}")
    if verbose:
        for rep in warn_only:
            lines.append(f"~ [{rep.source}] {rep.name}")
            for w in rep.warnings:
                lines.append(f"    warn:  {w}")
    n_ok = sum(1 for r in summary.reports if r.ok and not r.warnings)
    lines.append("")
    lines.append(
        f"{len(summary.reports)} skill(s): "
        f"{n_ok} clean, {len(warn_only)} with warnings, {len(bad)} with errors.")
    return "\n".join(lines)
