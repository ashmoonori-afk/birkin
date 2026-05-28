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


def detect_cli_agents() -> list[Model]:
    """Locally installed agent CLIs, usable as model backends (no API key)."""
    out: list[Model] = []
    if shutil.which("claude"):
        out.append(Model("claude-code (sonnet)", "claude-cli",
                         "local CLI · Claude Code", param="sonnet"))
        out.append(Model("claude-code (opus)", "claude-cli",
                         "local CLI · Claude Code", param="opus"))
    if shutil.which("codex"):
        out.append(Model("codex", "codex-cli", "local CLI · Codex", param=""))
    return out


def fetch_ollama_models() -> list[Model]:
    data = _get_json(f"{OLLAMA_HOST}/api/tags", {}, 1.5)
    return [Model(m["name"], "ollama", "local · ollama") for m in (data or {}).get("models", [])
            if m.get("name")]


def discover(cfg: dict[str, Any], *, api: bool = True, cli: bool = True,
             ollama: bool = True) -> list[Model]:
    """Curated baseline + live API + installed CLI agents + Ollama, deduped."""
    provider = cfg.get("provider", "anthropic")
    seen: set[str] = set()
    out: list[Model] = []

    def add(m: Model) -> None:
        kkey = f"{m.source}:{m.id}"
        if kkey not in seen:
            seen.add(kkey)
            out.append(m)

    if provider in ("anthropic", "openai"):
        for mid, note in config.KNOWN_MODELS.get(provider, []):
            add(Model(mid, provider, note))
    if api:
        for m in fetch_api_models(cfg):
            add(m)
    if cli:
        for m in detect_cli_agents():
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
        cfg["model"] = ""   # empty -> codex uses its own configured default
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


def render(models: list[Model], current: str) -> list[Model]:
    """Print a grouped, sequentially-numbered list (index matches `models`)."""
    groups = [
        ("API models", lambda m: m.source in ("anthropic", "openai")),
        ("Local CLI agents (no API key — uses the CLI's own login)",
         lambda m: m.is_cli),
        ("Local models (Ollama)", lambda m: m.is_ollama),
    ]
    n = 0
    shown_cli = False
    for title, pred in groups:
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
    return models
