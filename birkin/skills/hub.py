"""Install a skill from GitHub, through quarantine and a security scan.

``sync.py`` could only mirror skill trees already sitting on this disk. This
fetches one from any GitHub repository — but never straight into the live
skills directory: the bundle lands in quarantine, is scanned there, and is only
moved into place once the verdict and the user allow it.

Deliberately one *fetcher* for remote skills (GitHub) and one auth method (a
token from the environment). hermes carries a tap registry and an index cache;
neither is needed to install a skill you can already name, and neither is
ported.

The identifier is no longer limited to ``owner/repo``. A skill sitting in a
directory on this disk, or behind an https URL, goes through this very same
quarantine, scan and audit -- that boundary is what makes an install safe, and
it does not care how the bytes arrived. See ``sources.py``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from .. import config
from ..httpguard import PinnedHTTPSHandler
from . import guard
from .bundle_publish import (
    BundleSnapshot,
    publish_bundle,
    snapshot_bundle,
)

API = "https://api.github.com"
USER_AGENT = "birkin-skills-hub"
# Only support files SKILL.md actually references are fetched, and only from
# these directories — so a repo cannot smuggle in arbitrary paths.
SUPPORT_DIRS = ("references", "templates", "scripts", "assets", "examples")
MAX_SUPPORT_FILES = 20
FETCH_TIMEOUT = 30
MAX_SKILL_BYTES = 1_000_000
MAX_BUNDLE_BYTES = 5_000_000
_GITHUB_AUTH_HOSTS = frozenset({"api.github.com", "raw.githubusercontent.com"})
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")


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


class _NoCrossOriginRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects that could carry credentials to another origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        source = urllib.parse.urlsplit(req.full_url)
        target = urllib.parse.urlsplit(newurl)
        source_origin = (
            source.scheme.lower(),
            (source.hostname or "").lower(),
            source.port or 443,
        )
        target_origin = (
            target.scheme.lower(),
            (target.hostname or "").lower(),
            target.port or 443,
        )
        if target.scheme.lower() != "https" or target_origin != source_origin:
            raise urllib.error.HTTPError(
                newurl,
                code,
                "cross-origin skill redirect refused",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _get(url: str, raw: bool = False) -> bytes:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise HubError("skill downloads require an HTTPS URL")
    headers = {"User-Agent": USER_AGENT,
               "Accept": ("application/vnd.github.v3.raw" if raw
                          else "application/vnd.github+json")}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and parsed.hostname.lower() in _GITHUB_AUTH_HOSTS:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoCrossOriginRedirect(),
        PinnedHTTPSHandler(),
    )
    try:
        with opener.open(request, timeout=FETCH_TIMEOUT) as resp:
            payload = resp.read(MAX_SKILL_BYTES + 1)
        if len(payload) > MAX_SKILL_BYTES:
            raise HubError(
                f"skill download exceeds the {MAX_SKILL_BYTES}-byte limit"
            )
        return payload
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


def _contents_url(
    owner: str,
    repo: str,
    path: str,
    ref: str | None = None,
) -> str:
    quoted = urllib.parse.quote(path.strip("/"))
    url = f"{API}/repos/{owner}/{repo}/contents/{quoted}"
    return f"{url}?{urllib.parse.urlencode({'ref': ref})}" if ref else url


def _resolve_github_ref(owner: str, repo: str) -> str:
    try:
        repository = json.loads(_get(f"{API}/repos/{owner}/{repo}"))
        if not isinstance(repository, dict):
            raise HubError("GitHub repository metadata is malformed")
        branch = repository.get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise HubError("GitHub repository has no default branch")
        commit = json.loads(
            _get(
                f"{API}/repos/{owner}/{repo}/commits/"
                f"{urllib.parse.quote(branch, safe='')}"
            )
        )
        if not isinstance(commit, dict):
            raise HubError("GitHub commit metadata is malformed")
        sha = commit.get("sha")
        if not isinstance(sha, str) or not _COMMIT_SHA.fullmatch(sha):
            raise HubError("GitHub returned an invalid commit SHA")
        return sha
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HubError("GitHub repository metadata is malformed") from exc


def parse_identifier(identifier: str) -> tuple[str, str, str]:
    """``owner/repo[/path...]`` -> (owner, repo, path)."""
    parts = [p for p in (identifier or "").strip().strip("/").split("/") if p]
    if len(parts) < 2:
        raise HubError("identifier must be owner/repo or owner/repo/path")
    return parts[0], parts[1], "/".join(parts[2:])


def _list_dir(
    owner: str,
    repo: str,
    path: str,
    ref: str,
) -> dict[str, str]:
    """``{lowercased name: actual name}`` for the files in a repo directory."""
    try:
        entries = json.loads(_get(_contents_url(owner, repo, path, ref)))
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
    sha = _resolve_github_ref(owner, repo)
    skill_path = f"{path}/SKILL.md" if path else "SKILL.md"
    skill_payload = _get(
        _contents_url(owner, repo, skill_path, sha),
        raw=True,
    )
    total_bytes = len(skill_payload)
    skill_md = skill_payload.decode("utf-8", "replace")

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "SKILL.md").write_text(skill_md, encoding="utf-8")

    # One directory listing resolves the names SKILL.md uses to the files that
    # actually exist. Skills routinely refer to REFERENCE.md while shipping
    # reference.md, and GitHub's API is case-sensitive — without this the skill
    # installs without the documents it tells the model to read.
    listing = _list_dir(owner, repo, path, sha)

    fetched = ["SKILL.md"]
    for rel in referenced_support_paths(skill_md):
        actual = listing.get(rel.lower(), rel if "/" in rel else None)
        if actual is None:
            continue                      # named in prose, not in the repo
        remote = f"{path}/{actual}" if path else actual
        try:
            blob = _get(_contents_url(owner, repo, remote, sha), raw=True)
        except HubError:
            continue                      # referenced but absent: not fatal
        total_bytes += len(blob)
        if total_bytes > MAX_BUNDLE_BYTES:
            raise HubError(
                f"skill bundle exceeds the {MAX_BUNDLE_BYTES}-byte "
                "aggregate byte quota"
            )
        rel = actual
        target = dest / rel
        if not target.resolve().is_relative_to(dest.resolve()):
            raise HubError(f"support file escapes the bundle: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        fetched.append(rel)

    from .frontmatter import parse
    meta, _body = parse(skill_md)
    return {"identifier": identifier, "sha": sha, "files": fetched,
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
                            meta: dict[str, Any],
                            snapshot: BundleSnapshot) -> Path:
    """Move a scanned bundle into the live skills tree."""
    quarantine = Path(quarantine).resolve()
    if not quarantine.is_relative_to((hub_dir() / "quarantine").resolve()):
        raise HubError("bundle is not in quarantine")
    for path in quarantine.rglob("*"):
        if path.is_symlink():
            raise HubError(f"refusing to install a link: {path}")

    # The name a bundle installs under comes from its own frontmatter, so a
    # second install can claim the directory of one already there. Publishing
    # is replace=True, so that would swap out a skill the agent already reads
    # as instructions. Only the source that installed it may replace it.
    previous = load_lock().get(name)
    if isinstance(previous, dict) \
            and previous.get("identifier") != meta.get("identifier"):
        raise HubError(
            f"'{name}' 스킬은 이미 다른 출처"
            f"({previous.get('identifier', '?')})에서 설치되어 있어 "
            f"덮어쓰지 않았습니다. 교체하려면 먼저 "
            f"`birkin skills uninstall {name}`으로 제거한 뒤 다시 설치하세요."
        )

    target_root = config.user_skills_dir().absolute()
    target = target_root / "hub" / name
    _ = publish_bundle(
        snapshot,
        target,
        target_root=target_root,
        replace=True,
    )
    try:
        _record(name, {**meta, "install_path": str(target),
                       "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        audit("INSTALL", name, meta.get("identifier", ""),
              meta.get("verdict", "?"))
    except OSError as record_error:
        from .manager import PublicationCleanupError
        raise PublicationCleanupError(
            f"hub/{name}",
            snapshot.digest(),
        ) from record_error
    try:
        shutil.rmtree(quarantine)
    except OSError as cleanup_error:
        from .manager import PublicationCleanupError
        raise PublicationCleanupError(
            f"hub/{name}",
            snapshot.digest(),
        ) from cleanup_error
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
        from . import sources
        source = sources.source_for(identifier)
        name = source.probe_name(identifier)
        if not valid_skill_name(name):
            return False, f"unsafe skill name derived from {identifier!r}"
        quarantine = quarantine_dir(name)
        meta = source.fetch(identifier, quarantine)
        name = meta["name"] if valid_skill_name(meta["name"]) else name

        snapshot = snapshot_bundle(quarantine)
        result = guard.scan_skill(
            quarantine,
            source=identifier,
            file_overrides=snapshot.file_overrides(),
        )
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

        target = install_from_quarantine(
            name,
            quarantine,
            {
                "identifier": identifier,
                "source": source.source_id(),
                "verdict": result.verdict,
                "trust": result.trust,
                "content_hash": result.content_hash,
                "files": meta["files"],
                "description": meta["description"],
            },
            snapshot,
        )
        return True, f"{report}\n\nInstalled {name} -> {target}"
    except HubError as exc:
        if quarantine is not None:
            shutil.rmtree(quarantine, ignore_errors=True)
        return False, str(exc)
