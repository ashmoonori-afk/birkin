from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "native"
    / "packaged_journey.sh"
)


def test_packaged_journey_is_executable_and_valid_bash() -> None:
    result = subprocess.run(
        ["/bin/bash", "-n", str(SCRIPT)],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert os.access(SCRIPT, os.X_OK)
    assert result.returncode == 0, result.stderr


def test_packaged_processes_start_from_allowlisted_environments() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert source.count("/usr/bin/env -i") >= 3
    assert "/usr/bin/env -i \\\n  HOME=\"$HOME\"" in source
    assert "BIRKIN_NATIVE_JOURNEY=\"$BIRKIN_NATIVE_JOURNEY\"" in source
    private_network_rule = (
        'BIRKIN_BROWSER_PRIVATE_NETWORK_RULES="$BIRKIN_BROWSER_PRIVATE_NETWORK_RULES"'
    )
    assert private_network_rule in source


def test_owned_bridge_cleanup_uses_recorded_process_ids() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "owned_bridge_pids" in source
    assert 'pgrep -f "$bridge_pattern"' not in source


def test_journey_uses_only_per_step_window_captures() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "BIRKIN_NATIVE_SCREENSHOT" not in source


def test_journey_ignores_persisted_window_restoration_state() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "-ApplePersistenceIgnoreState YES" in source
