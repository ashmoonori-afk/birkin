"""Evidence-linked project document worker (the deterministic cartographer).

WHY: birkin's other workers summarize; Daedalus maps. Every claim it writes
carries a repo-relative `path:line` so a reader can check the map against the
territory, and every claim is labelled fact vs inference so a confident guess
never reads like a measurement. The scan is pure stdlib, offline and read-only:
the same tree in produces the same document out, which is what makes the CAS
refresh loop safe to automate.

Two inspirations. typst: structured markup compiled into a deterministic
document, with errors that say what went wrong AND what to do next.
changeroa/visual-learning: evidence-linked nodes, agent-owned vs human-owned
elements where human edits survive a refresh byte-for-byte, removed-but-
referenced nodes degrade into deprecated anchors instead of dangling, and
revision tokens (cas-N) that make a stale write fail loudly instead of silently
clobbering someone else's map.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config, store

Node = dict[str, Any]
Document = dict[str, Any]

# Copied literal from morpheus._EXCLUDE_DIRS on purpose: importing morpheus
# drags in the live-LLM runtime, and this module must stay offline/stdlib.
# Keep the two sets in sync by hand.
_EXCLUDE_DIRS = {".git", ".birkin", "node_modules", "__pycache__", ".venv",
                 "venv", "dist", "build", "out", "target", ".next",
                 ".codegraph", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                 ".tox"}

_README_NAMES = ("README.md", "README.rst", "README.txt", "README")
_SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_DEFAULT_MAX_FILES = 2000

PROFILE: dict[str, Any] = {
    "name": "daedalus",
    "role": (
        "You are Daedalus, birkin's document cartographer. You map a repository "
        "into an evidence-linked document: every claim carries an evidence "
        "path:line, every claim is labelled fact vs inference, and you never "
        "invent evidence. Human notes are read-only to you; leave them exactly "
        "as written and reference them by id. Answer conclusion-first, in ASCII."
    ),
    "style": "evidence-first, conclusion-first, ASCII",
    "deny_tools": ["run_shell", "spawn_subagent"],
}


class DaedalusError(RuntimeError):
    """Actionable failure: says what was wrong and what to run next."""


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _ascii(text: Any) -> str:
    return str(text).encode("ascii", "replace").decode("ascii")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slugify(text: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", _ascii(text).lower()).strip("-")
    return out or "x"


def _ev(path: str, line: int | None = None) -> dict[str, Any]:
    return {"path": path.replace("\\", "/"), "line": line}


def _node(nid: str, kind: str, text: str, evidence: Any, confidence: float,
          *, owner: str = "agent", refs: Any = ()) -> Node:
    return {
        "id": nid,
        "kind": kind,
        "text": _ascii(text),
        "evidence": list(evidence),
        "confidence": float(confidence),
        "owner": owner,
        "refs": list(refs),
    }


def _cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    # Resolved at call time so tests (and the CLI) can monkeypatch load_config.
    if cfg is not None:
        return cfg
    return config.load_config() or {}


def _max_files(cfg: dict[str, Any] | None) -> int:
    try:
        value = int((_cfg(cfg) or {}).get("daedalus_max_files") or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else _DEFAULT_MAX_FILES


def _check_slug(slug: str) -> str:
    if not _SLUG_RE.match(_ascii(slug)):
        raise DaedalusError(
            "bad document slug '%s': use letters, digits, '-' or '_' (max 64 "
            "chars), e.g. `birkin daedalus create myproj`" % _ascii(slug)
        )
    return _ascii(slug)


def daedalus_dir(cfg: dict[str, Any] | None = None) -> Path:
    """Where documents live: cfg['daedalus_dir'] or ~/.birkin/daedalus."""
    override = _ascii((_cfg(cfg) or {}).get("daedalus_dir") or "").strip()
    if override:
        return Path(override).expanduser()
    return config.birkin_home() / "daedalus"


def _path(slug: str, cfg: dict[str, Any] | None = None) -> Path:
    return daedalus_dir(cfg) / ("%s.json" % _check_slug(slug))


def _md_path(slug: str, cfg: dict[str, Any] | None = None) -> Path:
    return daedalus_dir(cfg) / ("%s.md" % _check_slug(slug))


def _write_text(path: Path, text: str) -> None:
    # Same atomic + 0o600 pattern as store._write_json, for the markdown twin.
    tmp = path.with_suffix(path.suffix + ".%d.%s.tmp"
                           % (os.getpid(), uuid.uuid4().hex[:8]))
    try:
        fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="ascii", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _save(doc: Document, cfg: dict[str, Any] | None) -> Document:
    target = daedalus_dir(cfg)
    target.mkdir(parents=True, exist_ok=True)
    store._write_json(_path(doc["slug"], cfg), doc)
    _write_text(_md_path(doc["slug"], cfg), render(doc))
    return doc


def _bump(token: str) -> str:
    try:
        return "cas-%d" % (int(_ascii(token).split("-", 1)[1]) + 1)
    except (IndexError, ValueError):
        return "cas-1"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# scan (read-only, deterministic)
# ---------------------------------------------------------------------------


def _parse_toml_lines(text: str) -> dict[tuple[str, str], tuple[str, int]]:
    """Line-oriented pyproject reader: keeps the line number of every key so
    evidence can point at `pyproject.toml:<line>` (tomllib drops positions)."""
    table: dict[tuple[str, str], tuple[str, int]] = {}
    section = ""
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().strip('"')
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().strip('"')
        value = value.strip().strip(",").strip()
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        if key:
            table.setdefault((section, key), (value, lineno))
    return table


def _pyproject_nodes(table: dict[tuple[str, str], tuple[str, int]]) -> list[Node]:
    nodes: list[Node] = []
    name = table.get(("project", "name"))
    if name:
        nodes.append(_node("a-project-name", "fact",
                           "project name: %s" % name[0],
                           [_ev("pyproject.toml", name[1])], 1.0))
    description = table.get(("project", "description"))
    if description:
        nodes.append(_node("a-project-description", "fact",
                           "project description: %s" % description[0],
                           [_ev("pyproject.toml", description[1])], 1.0))
    for (section, key), (value, lineno) in sorted(table.items()):
        if section != "project.scripts":
            continue
        nodes.append(_node("a-script-%s" % _slugify(key), "fact",
                           "entry point: %s -> %s" % (key, value),
                           [_ev("pyproject.toml", lineno)], 1.0))
    return nodes


def _layout_nodes(root: Path, max_files: int) -> list[Node]:
    nodes: list[Node] = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name)
    except OSError:
        return nodes
    for entry in entries[:max_files]:
        if entry.name in _EXCLUDE_DIRS or entry.name.startswith("."):
            continue
        if entry.is_dir():
            if (entry / "__init__.py").is_file():
                nodes.append(_node("a-package-%s" % _slugify(entry.name), "fact",
                                   "top-level package: %s" % entry.name,
                                   [_ev("%s/__init__.py" % entry.name)], 1.0))
        elif entry.is_file() and entry.suffix == ".py":
            nodes.append(_node("a-module-%s" % _slugify(entry.stem), "fact",
                               "top-level module: %s" % entry.name,
                               [_ev(entry.name)], 1.0))
    return nodes


def _toplevel_nodes(root: Path, max_files: int) -> list[Node]:
    """Non-Python fallback: describe the top level only, no recursion."""
    nodes: list[Node] = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name)
    except OSError:
        return nodes
    for entry in entries[:max_files]:
        if entry.name in _EXCLUDE_DIRS or entry.name.startswith("."):
            continue
        kind = "directory" if entry.is_dir() else "file"
        nodes.append(_node("a-entry-%s" % _slugify(entry.name), "fact",
                           "top-level %s: %s" % (kind, entry.name),
                           [_ev(entry.name)], 1.0))
    return nodes


def _tests_nodes(root: Path, max_files: int) -> list[Node]:
    tests = root / "tests"
    if not tests.is_dir():
        return [_node("a-tests-missing", "question",
                      "no tests/ directory found; where does the suite live?",
                      [], 0.5)]
    try:
        found = sorted(p for p in tests.rglob("test_*.py") if p.is_file())
    except OSError:
        found = []
    count = min(len(found), max_files)
    return [_node("a-tests", "fact",
                  "test suite: %d test_*.py files under tests/" % count,
                  [_ev("tests")], 1.0)]


def _readme_nodes(root: Path) -> list[Node]:
    for name in _README_NAMES:
        path = root / name
        if not path.is_file():
            continue
        for lineno, raw in enumerate(_read_text(path).splitlines(), 1):
            line = raw.strip()
            if line.startswith("#"):
                return [_node("a-readme", "fact",
                              "README first heading: %s" % line.lstrip("# ").strip(),
                              [_ev(name, lineno)], 1.0)]
        return [_node("a-readme-heading", "question",
                      "README has no top-level heading; add one so the entry "
                      "story is obvious", [_ev(name)], 0.5)]
    return [_node("a-readme-missing", "question",
                  "no README found; document the project entry story", [], 0.5)]


def _infer(nodes: list[Node], root: Path) -> list[Node]:
    """Inferences are always kind='inference' with confidence 0.6-0.8: a guess
    must never be able to read as a measurement."""
    out: list[Node] = []
    ids = {n["id"] for n in nodes}
    has_script = any(n["id"].startswith("a-script-") for n in nodes)
    has_package = any(n["id"].startswith("a-package-") for n in nodes)
    pyproject = "pyproject.toml" if (root / "pyproject.toml").is_file() else ""
    if has_script and pyproject:
        out.append(_node("a-infer-cli", "inference",
                         "declared entry points suggest a CLI application",
                         [_ev(pyproject)], 0.7))
    if has_package and "a-tests" in ids:
        evidence = [_ev(pyproject)] if pyproject else []
        out.append(_node("a-infer-library", "inference",
                         "packaged modules plus a test suite suggest a "
                         "maintained library", evidence, 0.7))
    if (root / "src").is_dir():
        out.append(_node("a-infer-src-layout", "inference",
                         "src layout suggests a distributable library project",
                         [_ev("src")], 0.7))
    return out


def _sort_key(node: Node) -> tuple[str, str]:
    evidence = node.get("evidence") or []
    first = evidence[0].get("path", "") if evidence else ""
    return (str(first), str(node.get("id", "")))


def scan(root: Path | str, *, max_files: int = _DEFAULT_MAX_FILES,
         cfg: dict[str, Any] | None = None) -> list[Node]:
    """Read-only deterministic pass: agent-owned nodes with resolvable evidence."""
    del cfg  # scan never touches config; kept for a uniform call signature
    root = Path(root)
    if not root.is_dir():
        raise DaedalusError(
            "root '%s' is not a directory; pass --root <existing path>"
            % _ascii(root)
        )
    budget = max(1, int(max_files))
    nodes: list[Node] = []
    if (root / "pyproject.toml").is_file():
        nodes.extend(_pyproject_nodes(_parse_toml_lines(
            _read_text(root / "pyproject.toml"))))
        nodes.extend(_layout_nodes(root, budget))
    else:
        nodes.extend(_toplevel_nodes(root, budget))
    nodes.extend(_tests_nodes(root, budget))
    nodes.extend(_readme_nodes(root))
    nodes.extend(_infer(nodes, root))

    unique: dict[str, Node] = {}
    for node in nodes:
        unique.setdefault(node["id"], node)
    return sorted(unique.values(), key=_sort_key)


# ---------------------------------------------------------------------------
# document lifecycle
# ---------------------------------------------------------------------------


def _title(slug: str, nodes: list[Node]) -> str:
    for node in nodes:
        if node["id"] == "a-project-name":
            _, _, name = node["text"].partition(":")
            if name.strip():
                return name.strip()
    return _ascii(slug)


def compose(slug: str, root: Path | str, nodes: list[Node],
            *, cfg: dict[str, Any] | None = None) -> Document:
    """Fresh document at cas-0."""
    del cfg
    stamp = _now()
    nodes = list(nodes)
    return {
        "slug": _check_slug(slug),
        "title": _title(slug, nodes),
        "root": str(Path(root)),
        "token": "cas-0",
        "nodes": nodes,
        "created": stamp,
        "updated": stamp,
    }


def load(slug: str, *, cfg: dict[str, Any] | None = None) -> Document | None:
    """The persisted document, or None when it was never created."""
    doc = store._read_json(_path(slug, _cfg(cfg)), None)
    return doc if isinstance(doc, dict) else None


def create(slug: str, root: Path | str, *,
           cfg: dict[str, Any] | None = None) -> Document:
    """Scan the tree and write the first revision (json + markdown)."""
    conf = _cfg(cfg)
    existing = load(slug, cfg=conf)
    if existing is not None or _path(slug, conf).exists():
        token = (existing or {}).get("token", "cas-0")
        raise DaedalusError(
            "document '%s' already exists; use `birkin daedalus refresh %s "
            "--expected-token %s` to update it"
            % (_check_slug(slug), _check_slug(slug), _ascii(token))
        )
    nodes = scan(root, max_files=_max_files(conf))
    return _save(compose(slug, root, nodes), conf)


def refresh(slug: str, root: Path | str, *, expected_token: str,
            cfg: dict[str, Any] | None = None) -> Document:
    """CAS re-scan: agent nodes are replaced, human nodes survive untouched.

    On a token mismatch nothing is written and the token is not advanced, so a
    stale caller can re-read and retry without having damaged the document.
    """
    conf = _cfg(cfg)
    doc = load(slug, cfg=conf)
    if doc is None:
        raise DaedalusError(
            "no document '%s'; run `birkin daedalus create %s` first"
            % (_check_slug(slug), _check_slug(slug))
        )
    current = _ascii(doc.get("token", "cas-0"))
    if _ascii(expected_token) != current:
        raise DaedalusError(
            "token mismatch: expected %s, document is at %s; re-read with "
            "`birkin daedalus show %s` and retry with the current token"
            % (_ascii(expected_token), current, _check_slug(slug))
        )

    old_nodes = list(doc.get("nodes") or [])
    humans = [n for n in old_nodes if n.get("owner") == "human"]
    old_agents = {n["id"]: n for n in old_nodes if n.get("owner") != "human"}

    fresh = scan(root, max_files=_max_files(conf))
    fresh_ids = {n["id"] for n in fresh}
    referenced = {ref for note in humans for ref in (note.get("refs") or [])}

    anchors: list[Node] = []
    for ref in sorted(referenced - fresh_ids):
        stale = old_agents.get(ref)
        if stale is None:
            continue
        anchor = dict(stale)
        anchor["kind"] = "deprecated-anchor"
        anchor["confidence"] = 0.0
        anchors.append(anchor)

    doc["nodes"] = fresh + anchors + humans  # humans kept byte-for-byte, last
    doc["root"] = str(Path(root))
    doc["title"] = _title(doc["slug"], fresh)
    doc["token"] = _bump(current)
    doc["updated"] = _now()
    return _save(doc, conf)


def add_note(slug: str, text: str, *, refs: Any = (),
             cfg: dict[str, Any] | None = None) -> Document:
    """Append a human-owned note (kind fact, confidence 1.0) and bump the token."""
    conf = _cfg(cfg)
    doc = load(slug, cfg=conf)
    if doc is None:
        raise DaedalusError(
            "no document '%s'; run `birkin daedalus create %s` first"
            % (_check_slug(slug), _check_slug(slug))
        )
    refs = [_ascii(r) for r in refs]
    known = {n["id"] for n in doc.get("nodes") or []}
    unknown = [r for r in refs if r not in known]
    if unknown:
        raise DaedalusError(
            "unknown ref(s): %s; run `birkin daedalus show %s` to list node ids"
            % (", ".join(sorted(unknown)), _check_slug(slug))
        )
    if not _ascii(text).strip():
        raise DaedalusError("note text is empty; pass --text \"<observation>\"")

    index = 1 + sum(1 for n in doc["nodes"] if n.get("owner") == "human")
    note = _node("h-%d" % index, "fact", text, [], 1.0,
                 owner="human", refs=refs)
    doc["nodes"] = list(doc["nodes"]) + [note]
    doc["token"] = _bump(_ascii(doc.get("token", "cas-0")))
    doc["updated"] = _now()
    return _save(doc, conf)


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def verify_evidence(doc: Document, root: Path | str,
                    *, cfg: dict[str, Any] | None = None) -> tuple[int, int]:
    """(resolved, total) evidence entries: resolved = path exists under root."""
    del cfg
    base = Path(root)
    resolved = 0
    total = 0
    for node in doc.get("nodes") or []:
        for item in node.get("evidence") or []:
            total += 1
            rel = _ascii(item.get("path") or "").strip()
            if rel and (base / rel).exists():
                resolved += 1
    return resolved, total


def _verdict(doc: Document) -> str:
    nodes = doc.get("nodes") or []
    agents = [n for n in nodes if n.get("owner") != "human"]
    packages = sum(1 for n in agents if n["id"].startswith("a-package-"))
    modules = sum(1 for n in agents if n["id"].startswith("a-module-"))
    scripts = sum(1 for n in agents if n["id"].startswith("a-script-"))
    facts = sum(1 for n in agents if n["kind"] == "fact")
    inferences = sum(1 for n in agents if n["kind"] == "inference")
    questions = sum(1 for n in agents if n["kind"] == "question")
    notes = sum(1 for n in nodes if n.get("owner") == "human")
    return (
        "%s -- %d package(s), %d top-level module(s), %d entry point(s); "
        "%d facts, %d inferences, %d open questions, %d human notes"
        % (_ascii(doc.get("title") or doc.get("slug") or "document"),
           packages, modules, scripts, facts, inferences, questions, notes)
    )


def _evidence_text(node: Node) -> str:
    parts = []
    for item in node.get("evidence") or []:
        path = _ascii(item.get("path") or "")
        line = item.get("line")
        parts.append("%s:%d" % (path, line) if isinstance(line, int) else path)
    return ", ".join(parts)


def _bullet(node: Node, tag: str) -> str:
    line = "- [%s %s] %s" % (tag, _ascii(node["id"]), _ascii(node["text"]))
    evidence = _evidence_text(node)
    if evidence:
        line += " (evidence: %s)" % evidence
    refs = [_ascii(r) for r in (node.get("refs") or [])]
    if refs:
        line += " (refs: %s)" % ", ".join(refs)
    line += " [conf %.1f]" % float(node.get("confidence", 0.0))
    return line


def render(doc: Document, *, cfg: dict[str, Any] | None = None) -> str:
    """Structured, ASCII-only markdown: frontmatter, VERDICT, sections, footer."""
    del cfg
    nodes = doc.get("nodes") or []
    agents = [n for n in nodes if n.get("owner") != "human"]
    humans = [n for n in nodes if n.get("owner") == "human"]
    sections = (
        ("## Facts", "F", [n for n in agents if n["kind"] == "fact"]),
        ("## Inferences", "I", [n for n in agents if n["kind"] == "inference"]),
        ("## Questions", "Q", [n for n in agents if n["kind"] == "question"]),
        ("## Notes (human)", "H", humans),
        ("## Deprecated anchors", "D",
         [n for n in agents if n["kind"] == "deprecated-anchor"]),
    )

    lines = [
        "---",
        "daedalus: %s" % _ascii(doc.get("slug", "")),
        "token: %s" % _ascii(doc.get("token", "cas-0")),
        "updated: %s" % _ascii(doc.get("updated", "")),
        "---",
        "",
        "# %s" % _ascii(doc.get("title") or doc.get("slug") or "document"),
        "",
        "VERDICT: %s" % _verdict(doc),
    ]
    for heading, tag, group in sections:
        if not group:
            continue  # empty sections are omitted, not left as noise
        lines.extend(["", heading])
        lines.extend(_bullet(node, tag) for node in group)
    resolved, total = verify_evidence(doc, doc.get("root") or ".")
    lines.extend(["", "evidence resolved: %d/%d" % (resolved, total), ""])
    return _ascii("\n".join(lines))


def start_prompt(doc: Document, *, cfg: dict[str, Any] | None = None) -> str:
    """Kickoff prompt seeding a chat that enriches the document via the CLI."""
    del cfg
    slug = _ascii(doc.get("slug", ""))
    questions = [n for n in (doc.get("nodes") or [])
                 if n.get("kind") == "question"]
    open_items = "\n".join("- [%s] %s" % (_ascii(n["id"]), _ascii(n["text"]))
                           for n in questions) or "- (none)"
    return _ascii(
        "%s\n\n"
        "Document: %s (token %s, root %s)\n"
        "Open questions:\n%s\n\n"
        "Review the rendered map (`birkin daedalus show %s`), then record each "
        "finding as a human note with the node ids it answers:\n"
        "  birkin daedalus note %s --text \"<finding>\" --ref <node-id>\n"
        "Cite an existing evidence path for every claim; if you cannot cite "
        "one, say so instead of guessing."
        % (PROFILE["role"], slug, _ascii(doc.get("token", "cas-0")),
           _ascii(doc.get("root", ".")), open_items, slug, slug)
    )
