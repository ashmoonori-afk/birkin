"""Settings and provider detection endpoints."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api", tags=["settings"])

_ALLOWED_KEY_NAMES = frozenset({"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN"})


@router.get("/settings")
def get_settings() -> dict:
    """Get current configuration."""
    from birkin.gateway.config import load_config

    return load_config()


@router.put("/settings")
def update_settings(body: dict) -> dict:
    """Update configuration."""
    from birkin.gateway.config import load_config, save_config

    config = load_config()
    config.update(body)
    save_config(config)
    return config


@router.put("/settings/keys")
def update_api_keys(body: dict) -> dict:
    """Write API keys to the .env file and update os.environ.

    Accepts ``{"ANTHROPIC_API_KEY": "sk-...", "OPENAI_API_KEY": "sk-..."}``.
    Only key names in the allow-list are accepted.
    """
    from pathlib import Path

    invalid = set(body.keys()) - _ALLOWED_KEY_NAMES
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid key names: {sorted(invalid)}. Allowed: {sorted(_ALLOWED_KEY_NAMES)}",
        )

    # Read existing .env (preserving unrelated lines)
    env_path = Path(".env")
    existing_lines: list[str] = []
    if env_path.exists():
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()

    # Parse existing key=value pairs and rebuild
    updated_keys: set[str] = set()
    new_lines: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            key_part = stripped.split("=", 1)[0]
            if key_part in body:
                new_lines.append(f"{key_part}={body[key_part]}")
                updated_keys.add(key_part)
                continue
        new_lines.append(line)

    # Append keys not yet present
    for key_name, key_value in body.items():
        if key_name not in updated_keys:
            new_lines.append(f"{key_name}={key_value}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # Set in current process immediately
    saved: list[str] = []
    for key_name, key_value in body.items():
        os.environ[key_name] = key_value
        saved.append(key_name)

    # Reset Telegram adapter if token changed (so it picks up the new one)
    if "TELEGRAM_BOT_TOKEN" in body:
        from birkin.gateway.deps import reset_telegram_adapter

        reset_telegram_adapter()

    return {"saved": sorted(saved)}


@router.get("/settings/providers")
def detect_providers() -> dict:
    """Detect available providers (API keys, local CLIs)."""
    import shutil

    results = {
        "anthropic": {
            "available": bool(os.getenv("ANTHROPIC_API_KEY")),
            "type": "api",
            "needs_key": True,
            "key_env": "ANTHROPIC_API_KEY",
            "models": ["claude-opus-4-20250805", "claude-sonnet-4-20250514"],
        },
        "openai": {
            "available": bool(os.getenv("OPENAI_API_KEY")),
            "type": "api",
            "needs_key": True,
            "key_env": "OPENAI_API_KEY",
            "models": ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
        },
        "claude-cli": {
            "available": shutil.which("claude") is not None,
            "type": "local",
            "needs_key": False,
            "description": "Claude Code CLI (local)",
        },
        "codex-cli": {
            "available": shutil.which("codex") is not None,
            "type": "local",
            "needs_key": False,
            "description": "OpenAI Codex CLI (local)",
        },
    }
    return results
