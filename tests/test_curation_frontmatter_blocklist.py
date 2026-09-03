"""Regression: `annotate` must not eat frontmatter written as YAML block lists.

Obsidian's property editor writes `aliases:` as an indented `- item` block.
Rebuilding the frontmatter by filtering single-line `key: value` entries left
those items orphaned under the preceding key, which the parser then swallowed
along with every key after it.
"""

from __future__ import annotations

from pathlib import Path

from birkin import config, curation, mnemosyne
from birkin.memory import VaultMemory

BLOCK_NOTE = """---
title: Deploy Runbook
type: procedure
version: 3
trust: high
aliases:
  - runbook
tags: [ops, deploy]
expires_at: 2027-01-01
---
Step 1. do the thing.
"""


def _vault_with_block_list_note() -> tuple[Path, Path]:
    m = VaultMemory(config.load_config())
    m.write_note("Deploy Runbook", "Step 1. do the thing.", zone="inbox")
    vault = config.vault_dir(config.load_config())
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    path = vault / dex.note_meta("deploy-runbook")["rel"]
    path.write_text(BLOCK_NOTE, encoding="utf-8")
    return vault, path


def test_annotate_preserves_keys_after_a_block_list_anchor():
    vault, path = _vault_with_block_list_note()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()

    curation.apply_plan([{"op": "annotate", "slug": "deploy-runbook",
                          "aliases": ["deploy-guide"]}], vault, dex)

    meta, body = mnemosyne.frontmatter.parse(
        path.read_text(encoding="utf-8"))
    assert body.strip() == "Step 1. do the thing."
    assert meta.get("trust") == "high"
    assert meta.get("tags") == ["ops", "deploy"]
    assert str(meta.get("expires_at")) == "2027-01-01"
    assert set(meta.get("aliases") or []) == {"runbook", "deploy-guide"}
