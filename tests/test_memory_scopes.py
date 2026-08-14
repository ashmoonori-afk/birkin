"""Scoped-memory contracts, beginning with the legacy vault baseline."""

from birkin import config
from birkin.memory import VaultMemory


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
