"""Mask credential material in text that is about to leave a tool.

Every native tool result passes through :meth:`tools.ToolRegistry.execute`.
Before this module a shell command echoing ``$ANTHROPIC_API_KEY``, a
``read_file`` on ``.env``, or a fetched page carrying a token put that secret
straight into the model's context -- and from there into the saved transcript,
the spill file on disk, and any channel reply quoting it.

Masking happens at that one choke point, *before* ``spill`` writes to disk, so
the secret is absent from every downstream copy rather than from the visible
reply only.

The mask is a **sentinel**, never a head/tail preview. hermes shipped a
head/tail mask (``ghp_S1...Pn2T``) and an agent read that value back out of a
config file and wrote it in, silently destroying the stored credential
(hermes issue #35519). A sentinel is syntactically invalid as a token, so it
cannot be mistaken for a usable-but-truncated one.

Pure standard library. Every pattern sits behind a cheap substring gate, so
clean text -- the overwhelmingly common case -- never pays for the full scan.
"""

from __future__ import annotations

import re
from typing import Any

SENTINEL = "[redacted]"

# Vendor prefixes, longest-first so ``sk-ant-`` wins over ``sk-`` and the label
# stays informative about *which* credential was present.
_PREFIXES = (
    "github_pat_", "sk-ant-", "glpat-", "xoxb-", "xoxp-", "xoxa-", "xoxs-",
    "ghp_", "gho_", "ghu_", "ghs_", "ghr_", "sk-", "AKIA", "AIza", "hf_",
    "npm_", "dop_v1_", "shpat_",
)
_PREFIX_RE = re.compile(
    "(" + "|".join(re.escape(p) for p in _PREFIXES) + r")[A-Za-z0-9_\-]{12,}")

# Header form: ``Authorization: Bearer <token>``, ``x-api-key: <token>``.
_AUTH_HEADER_RE = re.compile(
    r"(?i)\b(authorization|proxy-authorization|x-api-key|api-key)"
    r"(\s*[:=]\s*)(?:bearer\s+|basic\s+|token\s+)?[^\s,;]+")

# Three base64url segments -- a JWT carries its own claims, so the whole thing
# is the secret, not just the signature.
_JWT_RE = re.compile(
    r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")

# ``scheme://user:password@host`` -- the host stays, it is the diagnostic part.
_URL_USERINFO_RE = re.compile(
    r"(?i)\b([a-z][a-z0-9+.\-]*://[^\s:/@]+):[^\s@/]+@")

_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?"
    r"-----END [A-Z ]*PRIVATE KEY-----")

# Assignment whose *name* claims the value is a secret. Gated on the name so a
# plain ``count = 12345`` is never touched.
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b([A-Za-z0-9_.\-]*(?:api[_\-]?key|secret|password|passwd|token|"
    r"credential|access[_\-]?key)[A-Za-z0-9_.\-]*)"
    r"(\s*[=:]\s*)([\"']?)([^\s\"'#,;{}()]{6,})")

# A programmatic lookup references a variable *name*, not secret material.
# Masking it corrupts code and config snippets (hermes issue #2852):
# ``API_KEY=os.getenv("X")`` must survive unchanged.
_CODE_VALUE_RE = re.compile(
    r"(?i)^(?:os\.|process\.|env\.|environ|getenv|self\.|this\.|"
    r"config\.|settings\.|\$|%|<)")


def _has_prefix(text: str) -> bool:
    return any(prefix in text for prefix in _PREFIXES)


def _mask_prefixed(match: re.Match) -> str:
    """Keep the vendor label, drop every byte of the secret body."""
    return f"[redacted:{match.group(1)}...]"


def _mask_assignment(match: re.Match) -> str:
    name, sep, quote, value = match.group(1, 2, 3, 4)
    if _CODE_VALUE_RE.match(value):
        return match.group(0)
    return f"{name}{sep}{quote}{SENTINEL}{quote}"


def redact_sensitive_text(text: str) -> str:
    """Return ``text`` with credential material replaced by sentinels.

    Text that matches nothing is returned as the *same object*, so a caller can
    use an identity check to tell whether anything was masked.
    """
    if not text:
        return text
    out = text
    if "-----BEGIN" in out:
        out = _PRIVATE_KEY_RE.sub(SENTINEL, out)
    if _has_prefix(out):
        out = _PREFIX_RE.sub(_mask_prefixed, out)
    if "eyJ" in out:
        out = _JWT_RE.sub(SENTINEL, out)
    if "://" in out:
        out = _URL_USERINFO_RE.sub(r"\1:" + SENTINEL + "@", out)
    if ":" in out or "=" in out:
        out = _AUTH_HEADER_RE.sub(r"\1\2" + SENTINEL, out)
        out = _SECRET_ASSIGN_RE.sub(_mask_assignment, out)
    return text if out == text else out


def redact_tool_output(content: str, cfg: dict[str, Any]) -> str:
    """Mask a tool result unless the user set ``redact_secrets: false``.

    Never raises: a masking failure must not cost the agent its tool result.
    """
    if not cfg.get("redact_secrets", True):
        return content
    try:
        return redact_sensitive_text(content)
    except (TypeError, ValueError):
        return content
