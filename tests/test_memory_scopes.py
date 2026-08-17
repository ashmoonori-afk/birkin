"""Scoped-memory contracts, beginning with the legacy vault baseline."""

import json
from pathlib import Path

import pytest

from birkin import config
from birkin import curation
from birkin import memory as memory_module
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


def test_concurrent_replacement_cannot_be_registered_as_trusted(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = {
        **config.load_config(),
        "memory_source_trust": {
            "legacy": "low",
            "signed-import": "high",
        },
    }
    mem = VaultMemory(cfg)
    real_atomic_write = memory_module._atomic_write

    def replace_after_publish(path: Path, text: str) -> None:
        real_atomic_write(path, text)
        if path.suffix == ".md":
            path.write_text("ATTACKER RACE PAYLOAD\n", encoding="utf-8")

    monkeypatch.setattr(
        memory_module,
        "_atomic_write",
        replace_after_publish,
    )

    mem.write_note(
        "Raced note",
        "trusted original",
        source="signed-import",
    )
    record = mem.get_note_record("Raced note")

    assert record is not None
    assert record["record_source"] == "legacy"
    assert record["trust"] == "low"
    assert mem.search("ATTACKER RACE PAYLOAD", min_trust="high") == []


def test_rezone_preserves_authenticated_provenance() -> None:
    cfg = {
        **config.load_config(),
        "memory_source_trust": {
            "legacy": "low",
            "signed-import": "high",
        },
    }
    mem = VaultMemory(cfg)
    mem.write_note(
        "Rezoned note",
        "rezoned provenance marker",
        source="signed-import",
    )

    moved = mem.rezone("Rezoned note", "projects")
    record = mem.get_note_record("Rezoned note")

    assert moved.parent.name == "projects"
    assert record is not None
    assert record["record_source"] == "signed-import"
    assert record["trust"] == "high"
    assert mem.search(
        "rezoned provenance marker",
        min_trust="high",
    )


def test_search_binds_high_trust_to_authenticated_byte_snapshot(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = {
        **config.load_config(),
        "memory_source_trust": {
            "legacy": "low",
            "signed-import": "high",
        },
    }
    mem = VaultMemory(cfg)
    path = mem.write_note(
        "Snapshot note",
        "trusted snapshot marker",
        source="signed-import",
    )
    real_read_bytes = Path.read_bytes
    replaced = False

    def read_then_replace(candidate: Path) -> bytes:
        nonlocal replaced
        payload = real_read_bytes(candidate)
        if candidate == path and not replaced:
            replaced = True
            candidate.write_text(
                "ATTACKER snapshot marker\n",
                encoding="utf-8",
            )
        return payload

    monkeypatch.setattr(Path, "read_bytes", read_then_replace)

    results = mem.search(
        "snapshot marker",
        min_trust="high",
    )

    assert results
    assert results[0]["record_source"] == "signed-import"
    assert results[0]["trust"] == "high"
    assert "trusted snapshot marker" in results[0]["snippet"]
    assert "ATTACKER" not in results[0]["snippet"]


def test_curation_rezone_preserves_authenticated_provenance() -> None:
    cfg = {
        **config.load_config(),
        "memory_source_trust": {
            "legacy": "low",
            "signed-import": "high",
        },
    }
    mem = VaultMemory(cfg)
    mem.write_note(
        "Curated provenance",
        "curation provenance marker",
        source="signed-import",
    )

    def rezone_plan(_prompt: str) -> str:
        return json.dumps({
            "plan_version": 1,
            "ops": [{
                "op": "rezone",
                "slug": "curated-provenance",
                "zone": "projects",
            }],
            "summary": "curate authenticated note",
        })

    outcome = curation.run_curation_pass(
        mem.vault,
        rezone_plan,
        provider="test",
    )
    record = mem.get_note_record("Curated provenance")

    assert outcome.effected
    assert record is not None
    assert record["record_source"] == "signed-import"
    assert record["trust"] == "high"


def test_expiry_archive_preserves_authenticated_provenance() -> None:
    cfg = {
        **config.load_config(),
        "memory_source_trust": {
            "legacy": "low",
            "signed-import": "high",
        },
    }
    mem = VaultMemory(cfg)
    mem.write_note(
        "Expired provenance",
        "expired provenance marker",
        source="signed-import",
        expired_at="2000-01-01",
    )

    assert mem.purge_expired() == 1
    record = mem.get_note_record("Expired provenance")

    assert record is not None
    assert record["record_source"] == "signed-import"
    assert record["trust"] == "high"


def test_provenance_registration_is_scoped_to_one_vault(
        tmp_path: Path,
) -> None:
    trust = {
        "legacy": "low",
        "signed-import": "high",
    }
    vault_a = tmp_path / "vault-a"
    vault_b = tmp_path / "vault-b"
    mem_a = VaultMemory({
        **config.load_config(),
        "vault_path": str(vault_a),
        "memory_source_trust": trust,
    })
    mem_b = VaultMemory({
        **config.load_config(),
        "vault_path": str(vault_b),
        "memory_source_trust": trust,
    })
    registered = mem_a.write_note(
        "Boundary",
        "cross vault provenance marker",
        source="signed-import",
    )
    forged = vault_b / registered.relative_to(vault_a)
    forged.parent.mkdir(parents=True)
    forged.write_bytes(registered.read_bytes())

    record = mem_b.get_note_record("Boundary")

    assert record is not None
    assert record["record_source"] == "legacy"
    assert record["trust"] == "low"
    assert mem_b.search(
        "cross vault provenance marker",
        min_trust="high",
    ) == []


def test_direct_read_binds_content_to_provenance_snapshot(
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = {
        **config.load_config(),
        "memory_source_trust": {
            "legacy": "low",
            "signed-import": "high",
        },
    }
    mem = VaultMemory(cfg)
    path = mem.write_note(
        "Direct snapshot",
        "registered direct content",
        source="signed-import",
    )
    registered = path.read_text(encoding="utf-8")
    attacker = registered.replace(
        "registered direct content",
        "ATTACKER direct content",
    )
    real_find_note = mem._find_note
    real_read_text = Path.read_text
    attacked = False
    restored = False

    def find_then_attack(title: str, scope: MemoryScope) -> Path | None:
        nonlocal attacked
        found = real_find_note(title, scope)
        if found == path and not attacked:
            found.write_text(attacker, encoding="utf-8")
            attacked = True
        return found

    def read_then_restore(candidate: Path, *args, **kwargs) -> str:
        nonlocal restored
        text = real_read_text(candidate, *args, **kwargs)
        if candidate == path and attacked and not restored:
            restored = True
            candidate.write_text(registered, encoding="utf-8")
        return text

    monkeypatch.setattr(mem, "_find_note", find_then_attack)
    monkeypatch.setattr(Path, "read_text", read_then_restore)

    record = mem.get_note_record("Direct snapshot")

    assert record is not None
    assert "ATTACKER direct content" in record["content"]
    assert record["record_source"] == "legacy"
    assert record["trust"] == "low"


def test_memory_link_cannot_preserve_higher_provenance_than_caller() -> None:
    cfg = {
        **config.load_config(),
        "memory_source_trust": {
            "conversation": "low",
            "signed-import": "high",
        },
    }
    mem = VaultMemory(cfg)
    mem.write_note(
        "Trusted link target",
        "trusted link marker",
        source="signed-import",
    )
    tool = next(tool for tool in mem.tools() if tool.name == "memory_link")
    ctx = ToolContext(
        cfg=cfg,
        client=None,
        cwd=Path.cwd(),
        record_source="conversation",
    )

    result = tool.fn(
        {
            "from": "Trusted link target",
            "to": "ATTACKER PAYLOAD",
        },
        ctx,
    )
    record = mem.get_note_record("Trusted link target")

    assert result.is_error is False
    assert record is not None
    assert "[[ATTACKER PAYLOAD]]" in record["content"]
    assert record["record_source"] == "conversation"
    assert record["trust"] == "low"
    assert mem.search("ATTACKER PAYLOAD", min_trust="high") == []


def test_vault_symlink_retarget_cannot_reuse_pinned_provenance(
        tmp_path: Path,
) -> None:
    vault_a = tmp_path / "vault-a"
    vault_b = tmp_path / "vault-b"
    vault_a.mkdir()
    vault_b.mkdir()
    active = tmp_path / "active-vault"
    active.symlink_to(vault_a, target_is_directory=True)
    mem = VaultMemory({
        **config.load_config(),
        "vault_path": str(active),
        "memory_source_trust": {
            "legacy": "low",
            "signed-import": "high",
        },
    })
    trusted = mem.write_note(
        "Retargeted boundary",
        "retargeted vault marker",
        source="signed-import",
    )
    forged = vault_b / trusted.relative_to(active)
    forged.parent.mkdir(parents=True)
    forged.write_bytes(trusted.read_bytes())
    active.unlink()
    active.symlink_to(vault_b, target_is_directory=True)
    mem.reindex()

    record = mem.get_note_record("Retargeted boundary")

    assert record is not None
    assert record["record_source"] == "legacy"
    assert record["trust"] == "low"
    assert mem.search(
        "retargeted vault marker",
        min_trust="high",
    ) == []


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
