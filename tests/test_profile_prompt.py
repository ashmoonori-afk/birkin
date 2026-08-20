"""Profile prompt rendering and trust-boundary regressions."""

from __future__ import annotations

from birkin import config, promptgate, prompts
from birkin.profile_prompt import PRECEDENCE_DECLARATION, render_profile_blocks
from birkin.rolefiles import ProfileDocument, ProfileSnapshot


def _doc(name: str, guidance: str, used: int = 12, limit: int = 100) -> ProfileDocument:
    return ProfileDocument(
        name=name,
        guidance=guidance,
        entries=(guidance,) if guidance else (),
        used=used,
        limit=limit,
        revision=f"{name}-revision-sentinel",
    )


def _snapshot(**documents: ProfileDocument) -> ProfileSnapshot:
    return ProfileSnapshot(documents=documents, revision="aggregate-revision-sentinel")


def test_profile_block_order_and_position_before_vault_memory() -> None:
    profile = render_profile_blocks(_snapshot(
        automation=_doc("automation", "- automate reports"),
        workflow=_doc("workflow", "- run tests first"),
        preferences=_doc("preferences", "- answer in Korean"),
        user=_doc("user", "- user is LG"),
        mask=_doc("mask", "- concise warmth"),
    ))
    prompt = prompts.build_system_prompt(
        persona="SOUL TEXT",
        profile_block=profile,
        memory_block="Vault memory sentinel",
    )

    assert prompt.index("SOUL TEXT") < prompt.index(PRECEDENCE_DECLARATION)
    assert prompt.index(PRECEDENCE_DECLARATION) < prompt.index("### Mask")
    positions = [prompt.index(f"### {title}") for title in (
        "Mask", "User", "Preferences", "Workflow", "Automation",
    )]
    assert positions == sorted(positions)
    assert prompt.index("### Automation") < prompt.rindex("## What you know about the user")


def test_empty_blocks_are_omitted_and_guidance_survives_verbatim() -> None:
    guidance = "- keep this exact § marker\n- preserve punctuation: a,b; c!"
    out = render_profile_blocks(_snapshot(
        mask=_doc("mask", ""),
        preferences=_doc("preferences", guidance, used=len(guidance)),
    ))

    assert "### Mask" not in out
    assert "### Preferences" in out
    assert guidance in out


def test_over_budget_document_is_replaced_by_repair_marker() -> None:
    out = render_profile_blocks(_snapshot(
        preferences=_doc("preferences", "- SECRET TOO LONG", used=101, limit=100),
    ))

    assert "### Preferences [101% - 101/100 chars]" in out
    assert "[profile block omitted: document exceeds its character budget; use /profile to repair]" in out
    assert "SECRET TOO LONG" not in out


def test_rendering_is_byte_identical_and_leaks_no_metadata() -> None:
    snapshot = _snapshot(preferences=_doc("preferences", "- stable guidance"))

    first = render_profile_blocks(snapshot)
    second = render_profile_blocks(snapshot)

    assert first.encode("utf-8") == second.encode("utf-8")
    assert PRECEDENCE_DECLARATION in first
    assert "└" not in first
    assert "─" not in first
    assert "→" not in first
    assert not any("\uac00" <= char <= "\ud7a3" for char in first)
    assert "aggregate-revision-sentinel" not in first
    assert "preferences-revision-sentinel" not in first
    assert "timestamp" not in first.lower()
    assert "mtime" not in first.lower()


def test_untrusted_builders_receive_no_profile_content() -> None:
    secret = render_profile_blocks(_snapshot(mask=_doc("mask", "PRIVATE-PROFILE-SENTINEL")))

    trusted_main = promptgate.compose_main({}, persona_text="", profile_block=secret)
    trusted_cli = promptgate.compose_cli({}, persona_text="", profile_block=secret)
    public = promptgate.compose_public()

    assert "PRIVATE-PROFILE-SENTINEL" in trusted_main
    assert "PRIVATE-PROFILE-SENTINEL" in trusted_cli
    assert "PRIVATE-PROFILE-SENTINEL" not in public


def test_disabled_prompt_build_creates_no_profile_directory_or_block() -> None:
    from birkin import runtime

    cfg = {**config.DEFAULT_CONFIG, "profile": {**config.DEFAULT_CONFIG["profile"], "enabled": False}}

    packet = runtime.build_dry_run_packet("hello", cfg)

    assert "SOUL.md defines authoritative identity" not in packet["system"]
    assert not (config.birkin_home() / "profile").exists()


def test_enabled_prompt_build_bootstraps_profile_files() -> None:
    from birkin import runtime
    from birkin.rolefiles import PROFILE_ORDER

    cfg = {**config.DEFAULT_CONFIG, "profile": {**config.DEFAULT_CONFIG["profile"], "enabled": True}}

    packet = runtime.build_dry_run_packet("hello", cfg)

    assert "SOUL.md defines authoritative identity" not in packet["system"]
    files = sorted(path.name for path in (config.birkin_home() / "profile").glob("*.md"))
    assert files == [f"{name}.md" for name in sorted(PROFILE_ORDER)]
