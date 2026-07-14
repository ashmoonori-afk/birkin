"""Model discovery — surface API models *and* locally-installed CLI agents.

Three sources, shown together in the picker:
1. **API models** from the configured provider (live via ``/v1/models`` when a
   key is present; otherwise the curated baseline in ``config.KNOWN_MODELS``).
2. **Local CLI agents** that are installed on this machine and authenticated on
   their own — **Claude Code** (``claude``) and **Codex** (``codex``). Selecting
   one routes birkin through that CLI (no API key needed).
3. **Ollama** local models, if an Ollama server is running.

All probes use short timeouts / ``shutil.which`` and fail silently.
"""

from __future__ import annotations

import json
import os
import shutil
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

from . import config

OLLAMA_HOST = "http://localhost:11434"


@dataclass
class Model:
    id: str               # display name
    source: str           # "anthropic" | "openai" | "claude-cli" | "codex-cli" | "ollama"
    note: str = ""
    param: str = ""       # value stored as cfg["model"] (defaults to id)

    def model_value(self) -> str:
        return self.param or self.id

    @property
    def is_cli(self) -> bool:
        return self.source in ("claude-cli", "codex-cli", "local-cli")

    @property
    def is_ollama(self) -> bool:
        return self.source == "ollama"


def _get_json(url: str, headers: dict[str, str], timeout: float) -> Optional[dict[str, Any]]:
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None


def fetch_api_models(cfg: dict[str, Any]) -> list[Model]:
    provider = cfg.get("provider", "anthropic")
    if provider not in ("anthropic", "openai"):
        return []
    key = config.get_api_key(cfg)
    if not key or key == "cli":
        return []
    base = config.resolve_base_url(cfg)
    if provider == "anthropic":
        data = _get_json(f"{base}/v1/models",
                         {"x-api-key": key, "anthropic-version": "2023-06-01"}, 4.0)
        return [Model(m["id"], "anthropic", "api") for m in (data or {}).get("data", [])
                if m.get("id", "").startswith("claude")]
    data = _get_json(f"{base}/v1/models", {"Authorization": f"Bearer {key}"}, 4.0)
    return [Model(m["id"], "openai", "api") for m in (data or {}).get("data", [])
            if any(k in m.get("id", "") for k in ("gpt", "o1", "o3", "o4"))]


# Codex model ids the `codex exec -m <id>` CLI accepts. Curated (verified
# working); the user's own ~/.codex default is added on top, and extra ids can
# be added via cfg["codex_models"], so the list stays current without a release.
CODEX_KNOWN_MODELS = (
    "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5",
    "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex-spark",
)


def _codex_default_model() -> Optional[str]:
    """The `model = "..."` line from the user's Codex config, if any — always a
    valid id for this install, so we surface it first."""
    import re as _re
    from pathlib import Path as _Path
    home = os.environ.get("CODEX_HOME") or str(_Path.home() / ".codex")
    try:
        txt = (_Path(home) / "config.toml").read_text(encoding="utf-8",
                                                      errors="replace")
    except OSError:
        return None
    m = _re.search(r'(?m)^\s*model\s*=\s*"([^"]+)"', txt)
    return m.group(1) if m else None


def codex_model_ids(cfg: Optional[dict[str, Any]] = None) -> list[str]:
    """Ordered, de-duplicated codex model ids to offer: the config default
    first, then curated known ids, then any cfg['codex_models'] extras."""
    ids: list[str] = []
    default = _codex_default_model()
    if default:
        ids.append(default)
    for mid in CODEX_KNOWN_MODELS:
        if mid not in ids:
            ids.append(mid)
    for mid in (cfg or {}).get("codex_models", []) or []:
        if isinstance(mid, str) and mid and mid not in ids:
            ids.append(mid)
    return ids


def detect_cli_agents(cfg: Optional[dict[str, Any]] = None) -> list[Model]:
    """Locally installed agent CLIs, usable as model backends (no API key)."""
    out: list[Model] = []
    if shutil.which("claude"):
        for alias in ("sonnet", "opus", "haiku"):
            out.append(Model(f"claude-code ({alias})", "claude-cli",
                             "local CLI · Claude Code", param=alias))
    if shutil.which("codex"):
        for mid in codex_model_ids(cfg):
            out.append(Model(f"codex · {mid}", "codex-cli",
                             "local CLI · Codex", param=mid))
    return out


def fetch_ollama_models() -> list[Model]:
    data = _get_json(f"{OLLAMA_HOST}/api/tags", {}, 1.5)
    return [Model(m["name"], "ollama", "local · ollama") for m in (data or {}).get("models", [])
            if m.get("name")]


def discover(cfg: dict[str, Any], *, api: bool = True, cli: bool = True,
             ollama: bool = True) -> list[Model]:
    """Curated baseline + live API + installed CLI agents + Ollama, deduped."""
    seen: set[str] = set()
    out: list[Model] = []

    def add(m: Model) -> None:
        kkey = f"{m.source}:{m.id}"
        if kkey not in seen:
            seen.add(kkey)
            out.append(m)

    # Always show the full curated catalog (both vendors) so the picker lists
    # every model, not just the current provider's — the user can switch freely.
    for prov in ("anthropic", "openai"):
        for mid, note in config.KNOWN_MODELS.get(prov, []):
            add(Model(mid, prov, note))
    if api:
        for m in fetch_api_models(cfg):
            add(m)
    if cli:
        for m in detect_cli_agents(cfg):
            add(m)
        cmd = cfg.get("cli_command") or []
        if cmd:
            add(Model("local-cli", "local-cli",
                      "configured: " + " ".join(str(p) for p in cmd)))
    if ollama:
        for m in fetch_ollama_models():
            add(m)
    return out


def apply_selection(cfg: dict[str, Any], model: Model) -> None:
    """Point cfg at the chosen model, rewiring provider/base_url as needed."""
    if model.source == "claude-cli":
        cfg["provider"] = "claude-cli"
        cfg["model"] = model.model_value()   # "sonnet" | "opus"
        cfg["base_url"] = ""
    elif model.source == "codex-cli":
        cfg["provider"] = "codex-cli"
        # store the specific codex model id (e.g. "gpt-5.5"); llm.py passes it
        # through as `codex exec -m <id>`. Empty only for a bare "codex" entry.
        cfg["model"] = model.model_value()
        cfg["base_url"] = ""
    elif model.source == "local-cli":
        cfg["provider"] = "local-cli"  # uses config.cli_command
        cfg["base_url"] = ""
    elif model.is_ollama:
        cfg["provider"] = "openai"
        cfg["base_url"] = f"{OLLAMA_HOST}/v1"
        cfg["model"] = model.id
        if not config.get_api_key(cfg) or config.get_api_key(cfg) == "cli":
            cfg["api_key"] = "ollama"
    else:  # anthropic / openai API
        cfg["provider"] = model.source
        cfg["model"] = model.id


def pick_interactive(cfg: dict[str, Any], prompt: str = "Choose a model") -> Optional[Model]:
    """Discover models, show the interactive picker, and apply the choice to cfg.
    Returns the chosen Model, or None if the user cancelled."""
    from . import menu
    found = display_order(discover(cfg))
    labels = [f"{m.id}  [{m.source}]" + (f" · {m.note}" if m.note else "")
              for m in found]
    cur = cfg.get("model")
    default_i = next((i for i, m in enumerate(found) if m.model_value() == cur), 0)
    mi = menu.select(prompt, labels, default=default_i)
    if mi is None:
        return None
    apply_selection(cfg, found[mi])
    return found[mi]


_GROUPS = (
    ("API models", lambda m: m.source in ("anthropic", "openai")),
    ("Local CLI agents (no API key — uses the CLI's own login)",
     lambda m: m.is_cli),
    ("Local models (Ollama)", lambda m: m.is_ollama),
)


def display_order(models: list[Model]) -> list[Model]:
    """Models in the exact order ``render`` numbers them (grouped: API, CLI,
    Ollama), so a user-typed number maps to the model shown at that number."""
    out: list[Model] = []
    for _, pred in _GROUPS:
        out.extend(m for m in models if pred(m))
    seen = {id(m) for m in out}
    out.extend(m for m in models if id(m) not in seen)   # any ungrouped, last
    return out


def resolve(models: list[Model], arg: str) -> Optional[Model]:
    """Resolve a ``/models`` argument to a Model, or None.

    Accepts a 1-based number exactly as shown in ``render``, or a model
    name/param (exact ``id``/``model_value`` match first, then a
    case-insensitive substring). Returning the Model — not just a string — lets
    the caller rewire the provider via :func:`apply_selection`, so picking e.g.
    ``claude-code (opus)`` switches to the claude-cli backend instead of leaving
    a stale provider pointed at a model it cannot run."""
    arg = arg.strip()
    if not arg:
        return None
    ordered = display_order(models)
    if arg.isdigit():
        i = int(arg) - 1
        return ordered[i] if 0 <= i < len(ordered) else None
    for m in ordered:                       # exact id / stored value
        if arg in (m.id, m.model_value()):
            return m
    low = arg.lower()
    for m in ordered:                       # then case-insensitive substring
        if low in m.id.lower():
            return m
    return None


def render(models: list[Model], current: str) -> list[Model]:
    """Print a grouped, sequentially-numbered list; numbers match :func:`resolve`.
    Returns the models in the displayed (numbered) order."""
    n = 0
    shown_cli = False
    for title, pred in _GROUPS:
        items = [m for m in models if pred(m)]
        if title.startswith("Local CLI"):
            shown_cli = bool(items)
        if not items:
            continue
        print(f"  {title}:")
        for m in items:
            n += 1
            mark = "*" if m.model_value() == current else " "
            note = f" — {m.note}" if m.note else ""
            print(f"   {mark} {n}. {m.id} [{m.source}]{note}")
    if not shown_cli:
        print("  Local CLI agents: (install `claude` or `codex` to use them)")
    return display_order(models)
