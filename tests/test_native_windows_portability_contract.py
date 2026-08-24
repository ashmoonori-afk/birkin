"""Regression contracts for native Windows CI portability and provisioning."""

from __future__ import annotations

from pathlib import Path
from typing import TypeAlias, cast

import yaml

REPOSITORY = Path(__file__).parents[1]
WORKFLOW = REPOSITORY / ".github" / "workflows" / "native-windows.yml"
SHELL_TESTS = (
    REPOSITORY
    / "windows"
    / "BirkinNativeApp"
    / "tests"
    / "Birkin.Native.Shell.Tests"
)
YamlValue: TypeAlias = (
    str | int | float | bool | None | list["YamlValue"] | dict[str, "YamlValue"]
)
YamlMapping: TypeAlias = dict[str, YamlValue]


def _mapping(value: YamlValue) -> YamlMapping:
    return cast(YamlMapping, value)


def test_python_windows_gate_provisions_runtimes_and_uses_locked_launcher() -> None:
    workflow = cast(
        YamlMapping,
        yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")),
    )
    job = _mapping(_mapping(workflow["jobs"])["python-windows"])
    env = _mapping(job["env"])
    assert env["BIRKIN_BROWSER_INTEGRATION"] == "1"
    assert "PYTHONPATH" not in env

    steps = cast(list[YamlMapping], job["steps"])
    bun = next(
        step
        for step in steps
        if str(step.get("uses", "")).startswith("oven-sh/setup-bun@")
    )
    assert _mapping(bun["with"])["bun-version"] == "1.2.22"
    commands = [str(step["run"]) for step in steps if "run" in step]
    assert any(
        "./.venv/Scripts/python.exe -m playwright install chromium" in command
        for command in commands
    )
    pytest_command = next(command for command in commands if "pytest" in command)
    assert "./.venv/Scripts/python.exe -m pytest" in pytest_command


def test_swift_gate_provisions_the_python_harness_before_serial_execution() -> None:
    workflow = cast(
        YamlMapping,
        yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")),
    )
    job = _mapping(_mapping(workflow["jobs"])["swift-conformance"])
    assert _mapping(job["env"])["BIRKIN_BROWSER_INTEGRATION"] == "1"
    steps = cast(list[YamlMapping], job["steps"])
    uses = [str(step["uses"]) for step in steps if "uses" in step]
    commands = [str(step["run"]) for step in steps if "run" in step]
    assert any(action.startswith("actions/setup-python@") for action in uses)
    assert any(action.startswith("astral-sh/setup-uv@") for action in uses)
    assert "uv sync --frozen --all-extras --all-groups" in commands
    assert ".venv/bin/python -m playwright install chromium" in commands


def test_portable_shell_fixtures_do_not_embed_windows_drive_paths() -> None:
    offenders = [
        source.relative_to(SHELL_TESTS).as_posix()
        for source in SHELL_TESTS.rglob("*.cs")
        if '"root":"C:\\\\' in source.read_text(encoding="utf-8")
    ]
    assert offenders == []
