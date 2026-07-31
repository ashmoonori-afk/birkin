from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from birkin import promptgate, runtime, subagent
from birkin import presets
from birkin.tools import ToolContext, ToolRegistry, build_registry


def _tool_names(registry: ToolRegistry) -> set[str]:
    return {spec["name"] for spec in registry.specs()}


def test_subagent_uses_selected_model_for_prompt_and_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class CapturingAgent:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def run(self, task: str) -> str:
            return task

    monkeypatch.setattr(subagent, "Agent", CapturingAgent)
    ctx = ToolContext(
        cfg={
            "model": "claude-sonnet-5",
            "subagent_model": "claude-haiku-4-5",
        },
        client=SimpleNamespace(),
        cwd=tmp_path,
    )

    assert subagent.run_subagent("inspect", ctx) == "inspect"

    registry = captured["registry"]
    assert isinstance(registry, ToolRegistry)
    names = _tool_names(registry)
    assert not any("web" in name for name in names)
    assert "spawn_subagent" not in names
    assert captured["model"] == "claude-haiku-4-5"
    assert "fast, small engine" in str(captured["system"])


def test_reload_client_rebuilds_registry_for_new_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = {"model": "claude-opus-4-8", "provider": "anthropic"}
    old_client = SimpleNamespace()
    ctx = ToolContext(cfg=cfg, client=old_client, cwd=tmp_path)
    agent = SimpleNamespace(
        client=old_client,
        model=cfg["model"],
        registry=build_registry(ctx),
    )
    session = runtime.Session(
        cfg=cfg,
        client=old_client,
        skills=SimpleNamespace(),
        memory=SimpleNamespace(),
        ctx=ctx,
        agent=agent,
    )
    new_client = SimpleNamespace()
    monkeypatch.setattr(runtime.config, "get_api_key", lambda _cfg: "key")
    monkeypatch.setattr(
        runtime,
        "build_client",
        lambda _cfg, _key: new_client,
    )
    assert any("web" in name for name in _tool_names(agent.registry))

    cfg["model"] = "claude-haiku-4-5"
    session.reload_client()

    assert session.agent.registry.ctx.client is new_client
    names = _tool_names(session.agent.registry)
    assert not any("web" in name for name in names)
    assert "spawn_subagent" not in names

    cfg["model"] = "claude-opus-4-8"
    session.reload_client()
    restored = _tool_names(session.agent.registry)
    assert any("web" in name for name in restored)
    assert "spawn_subagent" in restored


def test_unknown_model_uses_explicit_neutral_preset() -> None:
    assert presets.family_of("future-provider/model-v1") == "neutral"
    resolved = presets.resolve("future-provider/model-v1")
    assert resolved["family"] == "neutral"
    assert set(resolved["deny_tools"]) == {"web", "subagent"}
    assert presets.role_overlay("future-provider/model-v1") == ""


def test_preset_override_can_only_add_restrictions() -> None:
    cfg = {
        "model_presets": {
            "haiku": {
                "deny_tools": [],
                "role": "custom role",
            },
            "": {"role": "must not match every model"},
        }
    }

    resolved = presets.resolve("claude-haiku-4-5", cfg)

    assert set(resolved["deny_tools"]) == {"web", "subagent"}
    assert resolved["role"] == "custom role"


def test_tool_policy_mode_matches_prompt_surface() -> None:
    assert presets.tool_policy_mode("native") == "enforced"
    assert presets.tool_policy_mode("cli") == "advisory"

    cfg = {"model": "claude-haiku-4-5"}
    native = promptgate.compose_main(cfg, persona_text="")
    cli = promptgate.compose_cli(cfg, persona_text="")

    assert "## Tool policy (enforced)" in native
    assert "## Tool policy (advisory)" in cli
    assert "## Tool policy (enforced)" not in cli


def test_denied_native_tools_are_not_executable(tmp_path: Path) -> None:
    full = build_registry(ToolContext(
        cfg={"model": "claude-opus-4-8"},
        client=SimpleNamespace(),
        cwd=tmp_path,
    ))
    restricted = build_registry(ToolContext(
        cfg={"model": "claude-haiku-4-5"},
        client=SimpleNamespace(),
        cwd=tmp_path,
    ))
    denied_names = _tool_names(full) - _tool_names(restricted)

    assert denied_names
    for name in denied_names:
        result = restricted.execute(name, {})
        assert result.is_error is True
        assert result.content.startswith("Unknown tool:")


@pytest.mark.parametrize(
    ("model", "family"),
    [
        ("claude-opus-4-8", "opus"),
        ("claude-sonnet-5", "sonnet"),
        ("claude-haiku-4-5", "haiku"),
        ("gpt-5.3-codex-spark", "spark"),
        ("gpt-5.6", "gpt"),
        ("llama3", "local"),
        ("future-provider/model-v1", "neutral"),
    ],
)
def test_prompt_surfaces_use_the_same_resolved_family(
    model: str,
    family: str,
) -> None:
    cfg = {"model": model}
    role = str(presets.PRESETS[family]["role"])
    marker = role.splitlines()[0] if role else ""

    native = promptgate.compose_main(cfg, persona_text="")
    cli = promptgate.compose_cli(cfg, persona_text="")

    if marker:
        assert marker in native
        assert marker in cli
    else:
        assert "## Engine preset" not in native
        assert "## Engine preset" not in cli
    assert native.rstrip().endswith("</research-evidence-policy>")
    assert cli.rstrip().endswith("</research-evidence-policy>")


@pytest.mark.parametrize(
    "model",
    [
        "claude-opus-4-8",
        "claude-haiku-4-5",
        "gpt-5.6",
        "future-provider/model-v1",
    ],
)
def test_model_overlays_remain_byte_stable(model: str) -> None:
    cfg = {"model": model}

    assert (
        promptgate.compose_main(cfg, persona_text="")
        == promptgate.compose_main(cfg, persona_text="")
    )
