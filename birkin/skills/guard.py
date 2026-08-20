"""Scan a skill bundle before its text reaches the system prompt.

A SKILL.md is instructions the model follows, and its scripts run on this
machine. ``sync.py`` copied third-party skills straight in, and the agent can
write its own — in both cases nothing inspected the content first.

The scanner looks for the things a hostile or careless skill does: exfiltrating
credentials, hijacking the agent's instructions, destroying data, hiding
payloads in obfuscation or invisible characters, and persisting itself.

A verdict is combined with how much the source is trusted:

===============  ======  =======  =========
source           safe    caution  dangerous
===============  ======  =======  =========
builtin          allow   allow    allow
trusted          allow   allow    block
community        allow   block    block
agent-created    allow   allow    ask
===============  ======  =======  =========

Static regexes are a bar-raiser, not a sandbox: obfuscation beyond the rules
here gets through. The install confirmation and the audit log stay in place
even for a clean verdict, precisely because a "safe" result is not a promise.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# (id, severity, category, regex, description)
THREAT_PATTERNS: list[tuple[str, str, str, str, str]] = [
    # -- exfiltration ------------------------------------------------------
    ("exfil-curl-secret", "critical", "exfiltration",
     r"\b(curl|wget|Invoke-WebRequest|iwr)\b[^\n]*\$\{?(\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)\w*)",
     "sends an environment secret to a remote host"),
    ("exfil-post-env", "critical", "exfiltration",
     r"\b(requests\.post|urlopen|fetch)\s*\([^\n)]*os\.environ",
     "posts environment variables to a URL"),
    ("exfil-credential-read", "critical", "exfiltration",
     r"(cat|type|Get-Content|open)\s*\(?[\"']?[~/\\.]*\.(ssh|aws|gnupg|kube)[/\\]",
     "reads a credential store"),
    ("exfil-cred-file", "high", "exfiltration",
     r"\.(ssh/id_[a-z0-9]+|aws/credentials|netrc|npmrc|pypirc)\b",
     "references a credentials file"),
    ("exfil-env-secret", "medium", "exfiltration",
     r"os\.environ(\.get)?\[?[\"'](\w*(KEY|TOKEN|SECRET|PASSWORD)\w*)[\"']",
     "reads a secret from the environment"),
    ("exfil-dns", "high", "exfiltration",
     r"\b(nslookup|dig)\b[^\n]*\$\(",
     "smuggles data through a DNS lookup"),
    ("exfil-markdown-image", "high", "exfiltration",
     r"!\[[^\]]*\]\(\s*https?://[^)\s]*\{\{?[^)]*\}\}?",
     "embeds data in a remote image URL"),

    # -- prompt injection --------------------------------------------------
    ("inject-ignore", "critical", "prompt-injection",
     r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|rules)",
     "tries to override the agent's instructions"),
    ("inject-disregard", "critical", "prompt-injection",
     r"disregard\s+(all\s+)?(previous|prior|your)\s+(instructions|rules|guidelines)",
     "tries to override the agent's instructions"),
    ("inject-role", "high", "prompt-injection",
     r"you\s+are\s+now\s+(a|an|in)\s+\w+\s*(mode|assistant|agent)",
     "tries to reassign the agent's role"),
    ("inject-jailbreak", "high", "prompt-injection",
     r"\b(DAN\s+mode|developer\s+mode|jailbreak|without\s+any\s+restrictions)\b",
     "jailbreak phrasing"),
    ("inject-hidden-html", "high", "prompt-injection",
     r"<!--[^>]*\b(ignore|instruct|system|prompt)\b[^>]*-->",
     "instructions hidden in an HTML comment"),
    ("inject-do-not-tell", "critical", "prompt-injection",
     r"(do\s+not|don't|never)\s+(tell|inform|mention\s+to|show)\s+the\s+user",
     "asks the agent to hide activity from the user"),

    # -- destructive -------------------------------------------------------
    ("destroy-rm-root", "critical", "destructive",
     r"\brm\s+(-[a-z]*\s+)*-[a-z]*[rf][a-z]*\s+(/|~|\$HOME)\s*($|[;&|])",
     "deletes the filesystem or home root"),
    ("destroy-mkfs", "critical", "destructive",
     r"\bmkfs(\.\w+)?\b|\bformat\s+[a-z]:", "formats a disk"),
    ("destroy-dd", "critical", "destructive",
     r"\bdd\b[^\n]*of=/dev/(sd|nvme|hd)", "overwrites a raw disk"),
    ("destroy-history", "high", "destructive",
     r"\bgit\s+(push\s+[^\n]*--force|reset\s+--hard)\b",
     "discards or overwrites git history"),

    # -- persistence -------------------------------------------------------
    ("persist-cron", "high", "persistence",
     r"\b(crontab\s+-|schtasks\s+/create|systemctl\s+enable)\b",
     "installs a scheduled task"),
    ("persist-rc", "high", "persistence",
     r">>\s*~?/?\.(bashrc|zshrc|profile|bash_profile)\b",
     "appends to a shell startup file"),
    ("persist-authorized-keys", "critical", "persistence",
     r"authorized_keys", "writes an SSH authorized key"),
    ("persist-agent-config", "high", "persistence",
     r">>?\s*[^\n]*(AGENTS\.md|CLAUDE\.md|\.birkin[/\\]config\.json)",
     "rewrites an agent's own configuration"),

    # -- remote control ----------------------------------------------------
    ("net-reverse-shell", "critical", "network",
     r"\bnc\b[^\n]*\s-e\b|/dev/tcp/|\bsocat\b[^\n]*EXEC",
     "opens a reverse shell"),
    ("net-tunnel", "high", "network",
     r"\b(ngrok|localtunnel|cloudflared)\b[^\n]*\b(http|tcp)\b",
     "opens a public tunnel to this machine"),

    # -- obfuscation -------------------------------------------------------
    ("obfus-b64-exec", "critical", "obfuscation",
     r"\b(base64\s+(-d|--decode)|b64decode)\b[^\n]*\|\s*(ba|z|k|)sh\b",
     "decodes and executes a payload"),
    ("obfus-eval-decode", "critical", "obfuscation",
     r"\beval\s*\(\s*(base64|atob|bytes\.fromhex|codecs\.decode)",
     "evaluates a decoded payload"),
    ("obfus-chr-build", "high", "obfuscation",
     r"(chr\(\d+\)\s*\+\s*){4,}", "builds a string from character codes"),
    ("obfus-powershell-enc", "critical", "obfuscation",
     r"powershell[^\n]*-[Ee]nc(odedCommand)?\b",
     "runs a base64-encoded PowerShell command"),

    # -- supply chain ------------------------------------------------------
    ("supply-curl-sh", "critical", "supply-chain",
     r"\b(curl|wget)\b[^|\n]*\|\s*(sudo\s+)?(ba|z|k|)sh\b",
     "pipes a download straight into a shell"),
    ("supply-unpinned", "low", "supply-chain",
     r"\b(pip|npm)\s+install\s+(?!.*[=@])\S+", "installs an unpinned package"),

    # -- privilege ---------------------------------------------------------
    ("priv-sudo", "medium", "privilege",
     r"\bsudo\s+\S+", "runs a command as root"),
    ("priv-setuid", "high", "privilege",
     r"\bchmod\s+[ugoa]*\+s\b", "sets the setuid bit"),

    # -- hardcoded secrets -------------------------------------------------
    ("secret-token", "high", "hardcoded-secret",
     r"\b(ghp_[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{32,}|AKIA[0-9A-Z]{16})\b",
     "contains what looks like a real credential"),
]

_COMPILED = [(pid, sev, cat, re.compile(rx, re.I), desc)
             for pid, sev, cat, rx, desc in THREAT_PATTERNS]

# Zero-width and bidirectional-override characters: invisible to a reviewer,
# meaningful to a parser.
INVISIBLE = {"​", "‌", "‍", "⁠", "﻿",
             "‪", "‫", "‬", "‭", "‮",
             "⁦", "⁧", "⁨", "⁩"}

SCANNABLE_SUFFIXES = {".md", ".py", ".sh", ".bash", ".zsh", ".ps1", ".js",
                      ".ts", ".rb", ".pl", ".yaml", ".yml", ".json", ".toml",
                      ".txt", ".cfg", ".ini", ""}
BINARY_SUFFIXES = {".exe", ".dll", ".so", ".dylib", ".bin", ".msi", ".jar",
                   ".pyc", ".scr", ".com", ".bat", ".cmd"}

MAX_FILES = 50
MAX_TOTAL_BYTES = 1_000_000
MAX_FILE_BYTES = 256_000

TRUSTED_REPOS = ("anthropics/", "openai/", "huggingface/", "NVIDIA/")

# verdict -> allow | block | ask
INSTALL_POLICY: dict[str, dict[str, str]] = {
    "builtin": {"safe": "allow", "caution": "allow", "dangerous": "allow"},
    "trusted": {"safe": "allow", "caution": "allow", "dangerous": "block"},
    "community": {"safe": "allow", "caution": "block", "dangerous": "block"},
    "agent-created": {"safe": "allow", "caution": "allow", "dangerous": "ask"},
}


@dataclass
class Finding:
    pattern_id: str
    severity: str
    category: str
    description: str
    file: str
    line: int
    excerpt: str


@dataclass
class ScanResult:
    verdict: str = "safe"
    findings: list[Finding] = field(default_factory=list)
    trust: str = "community"
    content_hash: str = ""
    errors: list[str] = field(default_factory=list)


def trust_level(source: str) -> str:
    """Classify a source identifier like ``anthropics/skills/pdf``."""
    if source in ("builtin", "agent-created", "official"):
        return "builtin" if source in ("builtin", "official") else source
    lowered = (source or "").lower()
    if any(lowered.startswith(repo.lower()) for repo in TRUSTED_REPOS):
        return "trusted"
    return "community"


def scan_text(text: str, filename: str) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[str, int]] = set()
    normalized = unicodedata.normalize("NFKC", text)
    for lineno, line in enumerate(normalized.splitlines(), 1):
        for pid, severity, category, pattern, desc in _COMPILED:
            if (pid, lineno) in seen:
                continue
            if pattern.search(line):
                seen.add((pid, lineno))
                findings.append(Finding(pid, severity, category, desc,
                                        filename, lineno, line.strip()[:160]))
        hidden = INVISIBLE.intersection(line)
        if hidden and (pid := "hidden-unicode") and (pid, lineno) not in seen:
            seen.add((pid, lineno))
            findings.append(Finding(
                pid, "high", "obfuscation",
                "contains invisible or bidirectional-override characters",
                filename, lineno, line.strip()[:160]))
    return findings


def _check_structure(root: Path) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    errors: list[str] = []
    total = 0
    count = 0
    try:
        entries = sorted(root.rglob("*"))
    except OSError as exc:
        return findings, [str(exc)]

    for path in entries:
        rel = path.relative_to(root).as_posix()
        # A symlink escaping the bundle would let an install read or overwrite
        # something outside it.
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                findings.append(Finding("escape-symlink", "critical", "path",
                                        "points outside the skill bundle",
                                        rel, 0, ""))
                continue
        except (OSError, ValueError):
            continue
        if not path.is_file():
            continue
        count += 1
        try:
            size = path.stat().st_size
        except OSError:
            continue
        total += size
        if path.suffix.lower() in BINARY_SUFFIXES:
            findings.append(Finding("binary-file", "high", "binary",
                                    "ships an executable binary", rel, 0, ""))
        if size > MAX_FILE_BYTES:
            findings.append(Finding("oversized-file", "medium", "structure",
                                    f"file is {size} bytes", rel, 0, ""))
    if count > MAX_FILES:
        errors.append(f"bundle has {count} files (limit {MAX_FILES})")
    if total > MAX_TOTAL_BYTES:
        errors.append(f"bundle is {total} bytes (limit {MAX_TOTAL_BYTES})")
    return findings, errors


def _bundle_files(root: Path) -> list[Path]:
    canonical_root = root.resolve()
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        try:
            if (
                path.is_symlink()
                or not path.resolve().is_relative_to(canonical_root)
                or not path.is_file()
            ):
                continue
        except (OSError, ValueError):
            continue
        files.append(path)
    return files


def content_hash(
    root: Path,
    file_overrides: Mapping[str, bytes] | None = None,
) -> str:
    digest = hashlib.sha256()
    payloads = dict(file_overrides or {})
    for path in _bundle_files(root):
        relative = path.relative_to(root).as_posix()
        if relative in payloads:
            continue
        try:
            payloads[relative] = path.read_bytes()
        except OSError:
            pass
    for relative, payload in sorted(payloads.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(payload)
    return digest.hexdigest()[:16]


def scan_skill(
    root: Any,
    source: str = "community",
    *,
    file_overrides: Mapping[str, bytes] | None = None,
) -> ScanResult:
    """Scan every readable file in a skill bundle."""
    root = Path(root)
    overrides = dict(file_overrides or {})
    result = ScanResult(trust=trust_level(source))
    if not root.is_dir():
        result.errors.append(f"not a directory: {root}")
        result.verdict = "dangerous"
        return result

    structural, errors = _check_structure(root)
    result.findings.extend(structural)
    result.errors.extend(errors)

    for relative, payload in sorted(overrides.items()):
        path = Path(relative)
        if path.suffix.lower() not in SCANNABLE_SUFFIXES:
            continue
        if len(payload) > MAX_FILE_BYTES:
            continue
        result.findings.extend(
            scan_text(
                payload.decode("utf-8", errors="replace"),
                relative,
            )
        )

    for path in _bundle_files(root):
        relative = path.relative_to(root).as_posix()
        if relative in overrides:
            continue
        if path.suffix.lower() not in SCANNABLE_SUFFIXES:
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        result.findings.extend(scan_text(text, relative))

    severities = {f.severity for f in result.findings}
    if "critical" in severities or result.errors:
        result.verdict = "dangerous"
    elif "high" in severities:
        result.verdict = "caution"
    else:
        result.verdict = "safe"
    result.content_hash = content_hash(
        root,
        file_overrides=overrides,
    )
    return result


def should_allow_install(result: ScanResult, force: bool = False
                         ) -> Optional[bool]:
    """True = install, False = refuse, None = ask the user.

    ``force`` can override a policy block, but never a *dangerous* verdict from
    an untrusted source: that is the one case where a human saying "just do it"
    is most likely to be the attack working.
    """
    decision = INSTALL_POLICY.get(result.trust,
                                  INSTALL_POLICY["community"]).get(
        result.verdict, "block")
    if decision == "allow":
        return True
    if decision == "ask":
        return None
    if force and not (result.verdict == "dangerous"
                      and result.trust in ("community", "trusted")):
        return True
    return False


def format_report(result: ScanResult, name: str = "") -> str:
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    lines = [f"Scan of {name or 'skill'} — verdict: {result.verdict.upper()} "
             f"(source trust: {result.trust})"]
    for err in result.errors:
        lines.append(f"  ! {err}")
    for f in sorted(result.findings, key=lambda f: order.get(f.severity, 9)):
        lines.append(f"  [{f.severity:<8}] {f.file}:{f.line} {f.description}")
        if f.excerpt:
            lines.append(f"             {f.excerpt}")
    if not result.findings and not result.errors:
        lines.append("  no findings")
    return "\n".join(lines)
