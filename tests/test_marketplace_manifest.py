"""The marketplace manifest must match the published schema.

A manifest that looks plausible but does not parse — or points at a plugin
directory that is not there — fails only in the user's Claude Code, at install
time, with nothing here to catch it.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKET = ROOT / ".claude-plugin" / "marketplace.json"


def test_marketplace_manifest_has_the_required_fields():
    data = json.loads(MARKET.read_text(encoding="utf-8"))
    assert data["name"] == "birkin"
    assert isinstance(data["owner"], dict) and data["owner"]["name"]
    assert data["plugins"], "a marketplace with no plugins helps nobody"
    for entry in data["plugins"]:
        assert {"name", "source", "description"} <= set(entry)


def test_every_listed_plugin_exists_with_its_own_manifest():
    data = json.loads(MARKET.read_text(encoding="utf-8"))
    for entry in data["plugins"]:
        src = (ROOT / entry["source"]).resolve()
        assert src.is_dir(), f"missing plugin dir: {entry['source']}"
        manifest = src / ".claude-plugin" / "plugin.json"
        assert manifest.is_file(), f"missing plugin.json in {entry['source']}"
        plugin = json.loads(manifest.read_text(encoding="utf-8"))
        assert plugin["name"] == entry["name"]
        assert plugin["version"], "omitting version makes every commit a release"


def test_the_vault_plugin_mounts_the_real_mcp_command():
    plugin = json.loads(
        (ROOT / "plugins" / "birkin-vault" / ".claude-plugin" /
         "plugin.json").read_text(encoding="utf-8"))
    server = plugin["mcpServers"]["birkin"]
    assert server["command"] == "birkin" and server["args"] == ["mcp-serve"]

    # the subcommand it names must actually exist
    from birkin.cli import build_parser
    args = build_parser().parse_args(["mcp-serve"])
    assert args.func.__name__ == "_cmd_mcp_serve"


def test_manifests_are_plain_utf8_without_a_bom():
    for rel in (".claude-plugin/marketplace.json",
                "plugins/birkin-vault/.claude-plugin/plugin.json"):
        raw = (ROOT / rel).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), f"{rel} has a BOM"
