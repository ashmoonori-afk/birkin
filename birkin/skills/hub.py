"""Install a skill from GitHub, through quarantine and a security scan.

``sync.py`` could only mirror skill trees already sitting on this disk. This
fetches one from any GitHub repository — but never straight into the live
skills directory: the bundle lands in quarantine, is scanned there, and is only
moved into place once the verdict and the user allow it.

Deliberately one source (GitHub) and one auth method (a token from the
environment). hermes carries ten source adapters, a tap registry and an index
cache; none of that is needed to install a skill you can already name.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from .. import config
from . import guard

API = "https://api.github.com"
USER_AGENT = "birkin-skills-hub"
# Only support files SKILL.md actually references are fetched, and only from
# these directories — so a repo cannot smuggle in arbitrary paths.
SUPPORT_DIRS = ("references", "templates", "scripts", "assets", "examples")
MAX_SUPPORT_FILES = 20
FETCH_TIMEOUT = 30


class HubError(RuntimeError):
    pass


def hub_dir() -> Path:
    d = config.user_skills_dir() / ".hub"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _lock_path() -> Path:
    return hub_dir() / "lock.json"


def _audit_path() -> Path:
    return hub_dir() / "audit.log"


# -- path safety -----------------------------------------------------------
#
# These three are the boundary that keeps an install (and its rmtree on
# uninstall) inside the skills tree. Ported carefully rather than re-derived.

def safe_relpath(value: str) -> Optional[str]:
    """Normalize a bundle-relative path, or None if it tries to escape."""
    if not value or value.startswith(("/", "\\")):
        return None
    candidate = value.replace("\\", "/")
    if ".." in candidate.split("/") or ":" in candidate:
        return None
    parts = [p for p in candidate.split("/") if p not in ("", ".")]
    return "/".join(parts) or None


def valid_skill_name(name: str) -> bool:
    return bool(name) and name not in (".", "..") \
        and all(c.isalnum() or c in "-_." for c in name) \
        and not name.startswith(".")


def resolve_install_path(name: str) -> Path:
    """Where ``name`` may be installed, refusing anything that redirects out.

    Every component is checked for a symlink/junction, then the resolved path
    must still land strictly inside the skills root — otherwise uninstall's
    rmtree could be pointed anywhere.
    """
    if not valid_skill_name(name):
        raise HubError(f"unsafe skill name: {name!r}")
    root = (config.user_skills_dir() / "hub").resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / name
    probe = root
    for part in target.relative_to(root).parts:
        probe = probe / part
        if probe.is_symlink():
            raise HubError(f"refusing to follow a link at {probe}")
    resolved = target.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise HubError(f"install path escapes the skills root: {resolved}")
    return resolved


# -- GitHub ----------------------------------------------------------------

def _get(url: str, raw: bool = False) -> bytes:
    headers = {"User-Agent": USER_AGENT,
               "Accept": ("application/vnd.github.v3.raw" if raw
                          else "application/vnd.github+json")}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise HubError(
                "GitHub refused the request (rate limit or private repo). Set "
                "GITHUB_TOKEN to raise the limit.") from exc
        if exc.code == 404:
            raise HubError("not found on GitHub — check owner/repo/path") from exc
        raise HubError(f"GitHub returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise HubError(f"could not reach GitHub: {exc.reason}") from exc


def _contents_url(owner: str, repo: str, path: str) -> str:
    quoted = urllib.parse.quote(path.strip("/"))
    return f"{API}/repos/{owner}/{repo}/contents/{quoted}"


def parse_identifier(identifier: str) -> tuple[str, str, str]:
    """``owner/repo[/path...]`` -> (owner, repo, path)."""
    parts = [p for p in (identifier or "").strip().strip("/").split("/") if p]
    if len(parts) < 2:
        raise HubError("identifier must be owner/repo or owner/repo/path")
    return parts[0], parts[1], "/".join(parts[2:])


def _list_dir(owner: str, repo: str, path: str) -> dict[str, str]:
    """``{lowercased name: actual name}`` for the files in a repo directory."""
    try:
        entries = json.loads(_get(_contents_url(owner, repo, path)))
    except (HubError, ValueError):
        return {}
    if not isinstance(entries, list):
        return {}
    return {str(e.get("name", "")).lower(): str(e.get("name", ""))
            for e in entries
            if isinstance(e, dict) and e.get("type") == "file"}


def referenced_support_paths(skill_md: str) -> list[str]:
    """Support files SKILL.md actually names.

    Two shapes, because real skills use both: paths under the conventional
    support directories (``scripts/run.sh``), and plain siblings of SKILL.md
    (``reference.md``) — the layout anthropics/skills uses, which a
    directories-only allowlist silently skipped, installing skills without the
    documents they tell the model to read.

    Only names that appear in the text are fetched, so a repo cannot smuggle
    in paths of its own choosing.
    """
    import re
    found: list[str] = []

    def add(raw: str) -> None:
        rel = safe_relpath(raw)
        if rel is None:
            raise HubError(f"SKILL.md references an unsafe path: {raw!r}")
        if rel not in found and rel != "SKILL.md":
            found.append(rel)

    for directory in SUPPORT_DIRS:
        pattern = re.compile(rf"(?<![\w/.-]){re.escape(directory)}/[\w./-]+")
        for m in pattern.finditer(skill_md):
            add(m.group(0))

    sibling = re.compile(
        r"(?<![\w/.-])([\w-]+\.(?:md|py|sh|txt|json|ya?ml|toml|csv))(?![\w/.-])")
    for m in sibling.finditer(skill_md):
        add(m.group(1))
    return found[:MAX_SUPPORT_FILES]


def fetch_bundle(identifier: str, dest: Path) -> dict[str, Any]:
    """Download a skill into ``dest``. Returns bundle metadata."""
    owner, repo, path = parse_identifier(identifier)
    skill_path = f"{path}/SKILL.md" if path else "SKILL.md"
    skill_md = _get(_contents_url(owner, repo, skill_path),
                    raw=True).decode("utf-8", "replace")

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "SKILL.md").write_text(skill_md, encoding="utf-8")

    # One directory listing resolves the names SKILL.md uses to the files that
    # actually exist. Skills routinely refer to REFERENCE.md while shipping
    # reference.md, and GitHub's API is case-sensitive — without this the skill
    # installs without the documents it tells the model to read.
    listing = _list_dir(owner, repo, path)

    fetched = ["SKILL.md"]
    for rel in referenced_support_paths(skill_md):
        actual = listing.get(rel.lower(), rel if "/" in rel else None)
        if actual is None:
            continue                      # named in prose, not in the repo
        remote = f"{path}/{actual}" if path else actual
        try:
            blob = _get(_contents_url(owner, repo, remote), raw=True)
        except HubError:
            continue                      # referenced but absent: not fatal
        rel = actual
        target = dest / rel
        if not target.resolve().is_relative_to(dest.resolve()):
            raise HubError(f"support file escapes the bundle: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        fetched.append(rel)

    from .frontmatter import parse
    meta, _body = parse(skill_md)
    return {"identifier": identifier, "files": fetched,
            "name": str(meta.get("name") or (path.split("/")[-1] if path else repo)),
            "description": str(meta.get("description", ""))}


# -- quarantine and install ------------------------------------------------

def quarantine_dir(name: str) -> Path:
    if not valid_skill_name(name):
        raise HubError(f"unsafe skill name: {name!r}")
    d = hub_dir() / "quarantine" / name
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    return d


def install_from_quarantine(name: str, quarantine: Path,
                            meta: dict[str, Any]) -> Path:
    """Move a scanned bundle into the live skills tree."""
    quarantine = Path(quarantine).resolve()
    if not quarantine.is_relative_to((hub_dir() / "quarantine").resolve()):
        raise HubError("bundle is not in quarantine")
    for path in quarantine.rglob("*"):
        if path.is_symlink():
            raise HubError(f"refusing to install a link: {path}")

    target = resolve_install_path(name)
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(quarantine), str(target))
    _record(name, {**meta, "install_path": str(target),
                   "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    audit("INSTALL", name, meta.get("identifier", ""),
          meta.get("verdict", "?"))
    return target


def uninstall(name: str) -> bool:
    entry = load_lock().get(name)
    if not entry:
        return False
    # Re-derive the path rather than trusting what the lock file says: a
    # tampered lock must not be able to aim rmtree somewhere else.
    target = resolve_install_path(name)
    if target.exists():
        shutil.rmtree(target)
    lock = load_lock()
    lock.pop(name, None)
    _write_lock(lock)
    audit("UNINSTALL", name, entry.get("identifier", ""), "-")
    return True


def load_lock() -> dict[str, Any]:
    from .. import store
    data = store._read_json(_lock_path(), {})
    return data if isinstance(data, dict) else {}


def _write_lock(lock: dict[str, Any]) -> None:
    from .. import store
    store._write_json(_lock_path(), lock)


def _record(name: str, entry: dict[str, Any]) -> None:
    lock = load_lock()
    lock[name] = entry
    _write_lock(lock)


def audit(action: str, name: str, identifier: str, verdict: str) -> None:
    try:
        with _audit_path().open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {action} {name} "
                     f"{identifier} {verdict}\n")
    except OSError:
        pass


def read_audit(limit: int = 50) -> list[str]:
    try:
        return _audit_path().read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []


# -- the install flow ------------------------------------------------------

def install(identifier: str, *, force: bool = False,
            confirm: Optional[Any] = None) -> tuple[bool, str]:
    """Fetch, scan and (if allowed) install. Returns (installed, report)."""
    quarantine = None
    try:
        probe = parse_identifier(identifier)
        name = probe[2].split("/")[-1] if probe[2] else probe[1]
        if not valid_skill_name(name):
            return False, f"unsafe skill name derived from {identifier!r}"
        quarantine = quarantine_dir(name)
        meta = fetch_bundle(identifier, quarantine)
        name = meta["name"] if valid_skill_name(meta["name"]) else name

        result = guard.scan_skill(quarantine, source=identifier)
        report = guard.format_report(result, name)
        allowed = guard.should_allow_install(result, force=force)

        if allowed is False:
            shutil.rmtree(quarantine, ignore_errors=True)
            audit("BLOCKED", name, identifier, result.verdict)
            return False, (f"{report}\n\nRefused: a {result.verdict} verdict "
                           f"from a {result.trust} source is not installable.")
        if allowed is None:
            if confirm is None or not confirm(report):
                shutil.rmtree(quarantine, ignore_errors=True)
                audit("DECLINED", name, identifier, result.verdict)
                return False, f"{report}\n\nNot installed."
        elif confirm is not None and not confirm(report):
            shutil.rmtree(quarantine, ignore_errors=True)
            audit("DECLINED", name, identifier, result.verdict)
            return False, f"{report}\n\nNot installed."

        target = install_from_quarantine(name, quarantine, {
            "identifier": identifier, "verdict": result.verdict,
            "trust": result.trust, "content_hash": result.content_hash,
            "files": meta["files"], "description": meta["description"]})
        return True, f"{report}\n\nInstalled {name} -> {target}"
    except HubError as exc:
        if quarantine is not None:
            shutil.rmtree(quarantine, ignore_errors=True)
        return False, str(exc)
