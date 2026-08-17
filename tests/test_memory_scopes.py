"""Scoped-memory contracts, beginning with the legacy vault baseline."""

from pathlib import Path

import pytest

from birkin import config
from birkin.memory import VaultMemory
from birkin.memory_scopes import (
    MemoryScope,
    SharedBlockWriteError,
    VisibilityDeniedError,
    scope_root,
)
from birkin.tools import ToolContext


def test_unscoped_vault_keeps_legacy_storage_and_lexical_search():
    """P1-8 baseline: metadata-free callers still use the original vault."""
    mem = VaultMemory(config.load_config())
    exact = mem.write_note("Exact", "orchid orchid orchid deployment", source="test")
    mem.write_note("Partial", "orchid gardening", source="test")

    assert exact.parent.name == "knowledge"
    assert not (mem.vault / ".birkin-scopes").exists()
    assert [hit["title"] for hit in mem.search("orchid deployment", limit=2)] == [
        "exact",
        "partial",
    ]


def _scoped(scope: MemoryScope, **overrides):
    cfg = {
        **config.load_config(),
        "memory_scope": scope.value,
        **overrides,
    }
    return VaultMemory(cfg)


def test_scope_storage_and_resolution_follow_explicit_precedence():
    for scope in reversed(tuple(MemoryScope)):
        mem = _scoped(scope)
        path = mem.write_note("Policy", f"owned by {scope.value}", source="test")
        assert scope_root(mem.vault, scope) in (path, *path.parents)

    record = _scoped(MemoryScope.USER).get_note_record("Policy")

    assert record is not None
    assert record["scope"] == "workflow"
    assert "owned by workflow" in record["content"]


def test_shared_read_only_block_is_readable_and_labeled_but_not_writable():
    owner = _scoped(MemoryScope.PROJECT)
    owner.write_note(
        "Shared standards",
        "release checklist",
        source="signed-import",
        shared_read_only=True,
    )
    agent = _scoped(MemoryScope.AGENT)

    record = agent.get_note_record("Shared standards")

    assert record is not None
    assert record["scope"] == "project"
    assert record["shared_read_only"] is True
    with pytest.raises(SharedBlockWriteError):
        agent.write_note(
            "Shared standards",
            "tampered",
            scope="project",
            source="chat",
        )


def test_minimum_trust_filters_per_source_without_changing_threshold_default():
    mem = _scoped(
        MemoryScope.USER,
        memory_source_trust={"signed-import": "high", "chat": "low"},
    )
    mem.write_note("Verified", "launch marker", source="signed-import")
    mem.write_note("Rumor", "launch marker", source="chat")

    strict = mem.search("launch marker", min_trust="medium")
    permissive = mem.search("launch marker", min_trust="low")

    assert [hit["title"] for hit in strict] == ["verified"]
    assert {hit["title"] for hit in permissive} == {"verified", "rumor"}


def test_visibility_denied_scope_returns_no_hits_and_direct_read_is_typed():
    _scoped(MemoryScope.ORGANIZATION).write_note(
        "Secret launch title", "classified marker", source="signed-import"
    )
    agent = _scoped(
        MemoryScope.AGENT,
        memory_visible_scopes=["agent", "user"],
    )

    assert agent.search("classified marker") == []
    with pytest.raises(VisibilityDeniedError):
        agent.get_note_record("Secret launch title", scope="organization")


def test_search_result_discloses_record_scope_source_and_trust_with_signals():
    mem = _scoped(
        MemoryScope.PROJECT,
        memory_source_trust={"signed-import": "high"},
    )
    mem.write_note("Contract", "disclosure marker", source="signed-import")

    hit = mem.search("disclosure marker")[0]

    assert hit["scope"] == "project"
    assert hit["record_source"] == "signed-import"
    assert hit["trust"] == "high"
    assert hit["source"] == ["lexical"]
    assert hit["signal_scores"]["lexical"] > 0


def test_memory_tool_source_cannot_self_attest_high_trust() -> None:
    cfg = {
        **config.load_config(),
        "memory_source_trust": {
            "conversation": "low",
            "signed-import": "high",
        },
    }
    mem = VaultMemory(cfg)
    tool = next(tool for tool in mem.tools() if tool.name == "memory_write_note")
    ctx = ToolContext(cfg=cfg, client=None, cwd=Path.cwd())

    result = tool.fn(
        {
            "title": "Forged provenance",
            "body": "trust boundary marker",
            "source": "signed-import",
        },
        ctx,
    )

    assert result.is_error is False
    record = mem.get_note_record("Forged provenance")
    assert record is not None
    assert record["record_source"] == "conversation"
    assert mem.search("trust boundary marker", min_trust="high") == []
    assert "source" not in tool.input_schema["properties"]


def test_unregistered_vault_frontmatter_cannot_self_attest_high_trust() -> None:
    cfg = {
        **config.load_config(),
        "memory_source_trust": {
            "legacy": "low",
            "signed-import": "high",
        },
    }
    mem = VaultMemory(cfg)
    note = scope_root(mem.vault, MemoryScope.USER) / "knowledge" / "forged.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\n"
        "title: Forged provenance\n"
        "type: fact\n"
        "record_source: signed-import\n"
        "sources: [signed-import]\n"
        "---\n\n"
        "unregistered provenance marker\n",
        encoding="utf-8",
    )

    record = mem.get_note_record("forged")

    assert record is not None
    assert record["record_source"] == "legacy"
    assert record["trust"] == "low"
    assert mem.search(
        "unregistered provenance marker",
        min_trust="high",
    ) == []


def test_tampered_note_loses_registered_high_trust() -> None:
    cfg = {
        **config.load_config(),
        "memory_source_trust": {
            "legacy": "low",
            "signed-import": "high",
        },
    }
    mem = VaultMemory(cfg)
    path = mem.write_note(
        "Signed note",
        "registered provenance marker",
        source="signed-import",
    )
    path.write_text(
        path.read_text(encoding="utf-8") + "\ntampered\n",
        encoding="utf-8",
    )

    record = mem.get_note_record("Signed note")

    assert record is not None
    assert record["record_source"] == "legacy"
    assert record["trust"] == "low"


def test_protected_user_role_files_remain_in_legacy_user_scope():
    mem = _scoped(MemoryScope.USER)
    system = mem.vault / "system"
    system.mkdir(parents=True)
    for name in ("user", "preferences", "soul", "workflow", "automation"):
        (system / f"{name}.md").write_text(f"{name} protected marker", encoding="utf-8")

    for name in ("user", "preferences", "soul", "workflow", "automation"):
        record = mem.get_note_record(name)
        assert record is not None
        assert record["scope"] == "user"
        assert f"{name} protected marker" in record["content"]
