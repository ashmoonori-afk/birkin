"""Every config key the READMEs document must actually be a default.

A README listing a key DEFAULT_CONFIG does not define is worse than silence:
the reader sets it, sees the shape they were shown, and has no way to learn
that birkin never advertised it. This check is why the lsp_servers mismatch was
caught before a push rather than by a user.

Only TOP-LEVEL keys are checked. A nested block (channels.telegram.token) is
documented by its parent, and reading its inner keys as top-level ones is a bug
in the checker, not in the README.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from birkin import config

_ROOT = Path(__file__).resolve().parent.parent

# Read by the code (gateway/polish.py) but deliberately absent from
# DEFAULT_CONFIG, and documented that way since 4b1411b -- before this branch.
# Listed rather than silently skipped, so the exception stays visible.
_UNDEFAULTED_BY_DESIGN = {"gateway_polish_provider", "gateway_polish_model"}


def _documented_keys(name: str) -> set[str]:
    """Top-level keys quoted in the README's JSON config example."""
    text = (_ROOT / name).read_text(encoding="utf-8")
    keys: set[str] = set()
    for block in re.findall(r"```json\n(.*?)```", text, re.DOTALL):
        depth = 0
        for line in block.splitlines():
            stripped = line.strip()
            # Digits matter: a key like a2a_enabled is invisible to
            # [a-z_]+, and an invisible key silently passes every check
            # here -- the failure mode this file exists to prevent.
            match = re.match(r'"([a-z0-9_]+)":', stripped)
            if match and depth == 1:
                keys.add(match.group(1))
            depth += stripped.count("{") - stripped.count("}")
    return keys


def _documented_config(name: str) -> dict[str, object]:
    """Return the README JSON block that documents provider defaults."""
    text = (_ROOT / name).read_text(encoding="utf-8")
    for block in re.findall(r"```json\n(.*?)```", text, re.DOTALL):
        parsed = json.loads(block)
        if "provider" in parsed:
            return parsed
    raise AssertionError(f"{name} has no provider config block")


@pytest.mark.parametrize("readme", ["README.md", "README.ko.md"])
def test_every_documented_key_is_a_real_default(readme: str) -> None:
    documented = _documented_keys(readme)
    assert documented, "no JSON config block found in the README"
    unknown = sorted(k for k in documented
                     if k not in config.DEFAULT_CONFIG
                     and k not in _UNDEFAULTED_BY_DESIGN)
    assert unknown == [], f"{readme} documents keys birkin never defines: {unknown}"


def test_the_two_readmes_document_the_same_keys() -> None:
    """A key explained in one language and absent in the other is a trap."""
    english = _documented_keys("README.md")
    korean = _documented_keys("README.ko.md")
    assert english == korean, (
        f"only in README.md: {sorted(english - korean)}; "
        f"only in README.ko.md: {sorted(korean - english)}")


@pytest.mark.parametrize("readme", ["README.md", "README.ko.md"])
def test_readme_provider_defaults_match_default_config(readme: str) -> None:
    documented = _documented_config(readme)
    for key in ("provider", "model", "subagent_model"):
        assert documented[key] == config.DEFAULT_CONFIG[key]


def test_generated_readme_config_blocks_are_current() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/sync_readme_config.py", "--check"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_keys_this_branch_added_are_documented_in_both() -> None:
    added = {
        "redact_secrets",
        "api_keys",
        "lsp_servers",
        "a2a_enabled",
        "cli_network_access",
        "egress",
        "harness_enabled",
        "harness_turn_interval",
        "harness_cooldown_min",
        "harness_compact_review",
        "harness_max_edits",
        "harness_prompt_budget",
        "harness_auto_approve",
    }
    for readme in ("README.md", "README.ko.md"):
        missing = sorted(added - _documented_keys(readme))
        assert missing == [], f"{readme} does not document {missing}"
