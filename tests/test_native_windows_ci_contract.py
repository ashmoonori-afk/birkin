"""Machine-consumed contract for the dedicated native Windows workflow."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TypeAlias, cast

import yaml

WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "native-windows.yml"
EXPECTED_JOBS = {
    "python-windows",
    "dotnet-portable",
    "wpf-windows",
    "live-bridge-window",
    "protocol-fixture-freshness",
    "swift-conformance",
    "provider-office-gate",
}
PORTABLE_OSES = ["ubuntu-latest", "macos-latest", "windows-latest"]
PYTHON_DESELECTIONS = {
    "tests/test_native_transport.py::test_uds_listener_rejects_symlinked_parent",
    "tests/test_native_transport.py::test_uds_listener_rejects_symlinked_socket_path",
}
PROVIDER_FILTER = "TestCategory=OfficeWorkflow&TestCategory=ExistingAccountProvider"
PORTABLE_FILTER = "TestCategory!=LiveBridge&TestCategory!=WindowsOnly"
ACTION_PIN = re.compile(r"^[^@]+@[0-9a-f]{40}$")
GOLDEN_ROOT = "macos/BirkinNativeApp/Tests/BirkinNativeProtocolTests/GoldenVectors"
SOLUTION = "windows/BirkinNativeApp/BirkinNativeApp.sln"
NOTIFICATION_SMOKE = (
    "windows/BirkinNativeApp/tests/Birkin.Native.Notification.Smoke/"
    "Birkin.Native.Notification.Smoke.csproj"
)
NOTIFICATION_SMOKE_PROJECT = Path(__file__).parents[1] / NOTIFICATION_SMOKE
NOTIFICATION_SMOKE_ROOT = NOTIFICATION_SMOKE_PROJECT.parent
RESTRICTED_PROCESS_LAUNCHER = NOTIFICATION_SMOKE_ROOT / "RestrictedProcessLauncher.cs"
LOCKED_SYNC = "uv sync --frozen --all-extras --all-groups"
LOCKED_WINDOWS_PYTHON = "./.venv/Scripts/python.exe"
ENSURE_LOCKED_WINDOWS_PIP = f"{LOCKED_WINDOWS_PYTHON} -m ensurepip --upgrade"
YamlScalar: TypeAlias = str | int | float | bool | None
YamlValue: TypeAlias = YamlScalar | list["YamlValue"] | dict[str, "YamlValue"]
YamlMapping: TypeAlias = dict[str, YamlValue]

# PyYAML exposes an untyped boundary; casts stay here while assertions pin every
# consumed workflow node to its machine-readable contract.
def _mapping(value: YamlValue) -> YamlMapping:
    return cast(YamlMapping, value)


def _workflow() -> YamlMapping:
    return cast(
        YamlMapping,
        yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")),
    )


def _job(workflow: YamlMapping, name: str) -> YamlMapping:
    return _mapping(_mapping(workflow["jobs"])[name])


def _steps(job: YamlMapping) -> list[YamlMapping]:
    return cast(list[YamlMapping], job["steps"])


def _commands(job: YamlMapping) -> list[str]:
    return [cast(str, step["run"]) for step in _steps(job) if "run" in step]


def _joined_commands(job: YamlMapping) -> str:
    return "\n".join(_commands(job)).replace("\\", "/")


def _normalized(command: str) -> str:
    return " ".join(command.replace("\\", "/").split())


def test_dedicated_native_windows_workflow_exists() -> None:
    assert WORKFLOW.is_file(), f"missing dedicated workflow: {WORKFLOW}"


def test_triggers_cover_every_client_breaking_path() -> None:
    workflow = _workflow()
    raw_triggers = workflow.get("on")
    if raw_triggers is None:
        raw_triggers = cast(dict[str | bool, YamlValue], workflow)[True]
    triggers = _mapping(raw_triggers)
    assert {"push", "pull_request", "schedule", "workflow_dispatch"} <= set(triggers)

    required_paths = {
        "windows/**",
        "birkin/native/**",
        "birkin/office/**",
        "birkin/workspace/**",
        "scripts/native/**",
        f"{GOLDEN_ROOT}/**",
        "docs/native-app/**",
        "pyproject.toml",
        "uv.lock",
        ".github/workflows/native-windows.yml",
        "tests/test_native_windows_import.py",
        "tests/test_native_windows_ci_contract.py",
        "tests/test_native_office*.py",
    }
    for event in ("push", "pull_request"):
        config = _mapping(triggers[event])
        assert set(cast(list[str], config["paths"])) == required_paths


def test_workflow_uses_least_privilege_concurrency_and_pinned_actions() -> None:
    workflow = _workflow()
    assert set(_mapping(workflow["jobs"])) == EXPECTED_JOBS
    assert workflow["permissions"] == {"contents": "read"}
    assert _mapping(workflow["concurrency"]) == {
        "group": "native-windows-${{ github.workflow }}-${{ github.ref }}",
        "cancel-in-progress": True,
    }

    action_uses = [
        cast(str, step["uses"])
        for raw_job in _mapping(workflow["jobs"]).values()
        for step in _steps(_mapping(raw_job))
        if "uses" in step
    ]
    assert action_uses
    assert all(ACTION_PIN.fullmatch(action) for action in action_uses)
    checkout_steps = [
        step
        for raw_job in _mapping(workflow["jobs"]).values()
        for step in _steps(_mapping(raw_job))
        if str(step.get("uses", "")).startswith("actions/checkout@")
    ]
    assert len(checkout_steps) == len(EXPECTED_JOBS)
    assert all(_mapping(step["with"])["persist-credentials"] is False for step in checkout_steps)


def test_python_windows_gate_runs_the_complete_locked_suite_with_only_two_deselections() -> None:
    job = _job(_workflow(), "python-windows")
    assert job["runs-on"] == "windows-latest"
    steps = _steps(job)
    python = next(step for step in steps if str(step.get("uses", "")).startswith("actions/setup-python@"))
    assert _mapping(python["with"])["python-version"] == "3.13"
    assert any(str(step.get("uses", "")).startswith("astral-sh/setup-uv@") for step in steps)

    normalized = [_normalized(command) for command in _commands(job)]
    assert LOCKED_SYNC in normalized
    assert ENSURE_LOCKED_WINDOWS_PIP in normalized
    pytest_commands = [command for command in normalized if " pytest " in f" {command} "]
    assert len(pytest_commands) == 1
    pytest_command = pytest_commands[0]
    assert normalized.index(LOCKED_SYNC) < normalized.index(ENSURE_LOCKED_WINDOWS_PIP)
    assert normalized.index(ENSURE_LOCKED_WINDOWS_PIP) < normalized.index(pytest_command)
    assert pytest_command.startswith(
        f'{LOCKED_WINDOWS_PYTHON} -m pytest -q -o addopts="" '
    )
    assert "uv run" not in pytest_command
    assert set(re.findall(r"--deselect\s+(\S+)", pytest_command)) == PYTHON_DESELECTIONS
    without_deselections = re.sub(r"\s*--deselect\s+\S+", "", pytest_command)
    assert without_deselections == (
        f'{LOCKED_WINDOWS_PYTHON} -m pytest -q -o addopts=""'
    )
    assert not any(token in pytest_command for token in ("--ignore", "--ignore-glob", " -k "))


def test_dotnet_portable_runs_protocol_and_shell_on_all_three_operating_systems() -> None:
    workflow = _workflow()
    portable = _job(workflow, "dotnet-portable")
    assert portable["runs-on"] == "${{ matrix.os }}"
    strategy = _mapping(portable["strategy"])
    matrix = _mapping(strategy["matrix"])
    assert matrix["os"] == PORTABLE_OSES

    setup = next(
        step
        for step in _steps(portable)
        if str(step.get("uses", "")).startswith("actions/setup-dotnet@")
    )
    assert _mapping(setup["with"])["dotnet-version"] == "8.x"
    commands = [_normalized(command) for command in _commands(portable)]
    projects = (
        "windows/BirkinNativeApp/tests/Birkin.Native.Protocol.Tests/Birkin.Native.Protocol.Tests.csproj",
        "windows/BirkinNativeApp/tests/Birkin.Native.Shell.Tests/Birkin.Native.Shell.Tests.csproj",
    )
    expected_tests = {
        f'dotnet test {project} -c Release --no-restore --filter "{PORTABLE_FILTER}"'
        for project in projects
    }
    for project in projects:
        assert f"dotnet restore {project}" in commands
    assert {command for command in commands if command.startswith("dotnet test ")} == expected_tests


def test_wpf_job_prepares_locked_python_before_unfiltered_full_release_solution() -> None:
    wpf = _job(_workflow(), "wpf-windows")
    assert wpf["runs-on"] == "windows-latest"
    env = _mapping(wpf.get("env", {}))
    assert "BIRKIN_EXISTING_ACCOUNT_RUNNER" not in env
    assert env["UV_NO_SYNC"] == "1"
    steps = _steps(wpf)
    python_index, python = next(
        (index, step)
        for index, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("actions/setup-python@")
    )
    uv_index = next(
        index
        for index, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")
    )
    sync_index = next(
        index for index, step in enumerate(steps) if step.get("run") == LOCKED_SYNC
    )
    test_index = next(
        index for index, step in enumerate(steps) if f"dotnet test ./{SOLUTION}" in str(step.get("run", ""))
    )
    assert _mapping(python["with"])["python-version"] == "3.13"
    assert python_index < uv_index < sync_index < test_index

    commands = [_normalized(command) for command in _commands(wpf)]
    assert f"dotnet restore ./{SOLUTION}" in commands
    assert f"dotnet build ./{SOLUTION} -c Release --no-restore" in commands
    test_commands = [command for command in commands if command.startswith(f"dotnet test ./{SOLUTION}")]
    assert test_commands == [
        f'dotnet test ./{SOLUTION} -c Release --no-build --logger "trx;LogFilePrefix=native-windows"'
    ]
    assert "--filter" not in test_commands[0]


def test_wpf_job_executes_real_windows_notification_smoke() -> None:
    commands = [
        _normalized(command)
        for command in _commands(_job(_workflow(), "wpf-windows"))
    ]
    restore = f"dotnet restore ./{NOTIFICATION_SMOKE}"
    build = (
        f"dotnet build ./{NOTIFICATION_SMOKE} -c Release --no-restore "
        "--disable-build-servers -p:UseSharedCompilation=false -m:1"
    )
    smoke = next(
        command
        for command in commands
        if "WINDOWS_APPROVAL_TOAST_ACCEPTED:" in command
    )
    runtime_registration = next(
        command
        for command in commands
        if "Get-AuthenticodeSignature" in command
        and "Add-AppxPackage" in command
    )
    solution_restore = f"dotnet restore ./{SOLUTION}"
    solution_build = f"dotnet build ./{SOLUTION} -c Release --no-restore"

    assert _mapping(_job(_workflow(), "wpf-windows")["env"])[
        "MSBUILDDISABLENODEREUSE"
    ] == "1"
    assert restore in commands
    assert build in commands
    assert commands.index(restore) < commands.index(build)
    assert "& $executable" in smoke
    assert "WINDOWS_APPROVAL_TOAST_INTEGRITY:medium" in smoke
    assert "New-ScheduledTaskPrincipal" not in smoke
    assert "Register-ScheduledTask" not in smoke
    assert "Birkin.Native.Notification.Smoke.exe" in smoke
    assert commands.index(build) < commands.index(smoke)
    assert "microsoft.windowsappsdk.runtime/2.4.0" in runtime_registration
    assert "Microsoft.WindowsAppRuntime.Singleton.2.msix" in runtime_registration
    assert "Microsoft.WindowsAppRuntime.DDLM.2.msix" in runtime_registration
    assert "Get-AuthenticodeSignature" in runtime_registration
    assert "O=Microsoft Corporation" in runtime_registration
    assert "Invoke-WebRequest" not in runtime_registration
    assert commands.index(build) < commands.index(runtime_registration)
    assert commands.index(runtime_registration) < commands.index(smoke)
    assert commands.index(smoke) < commands.index(solution_restore)
    assert commands.index(solution_restore) < commands.index(solution_build)


def test_notification_smoke_creates_a_lua_process_from_the_runner_token() -> None:
    launcher = RESTRICTED_PROCESS_LAUNCHER.read_text(encoding="utf-8")

    assert "CreateRestrictedToken" in launcher
    assert "LuaToken" in launcher
    assert "SetTokenInformation" in launcher
    assert "S-1-16-8192" in launcher
    assert "CreateProcessAsUser" in launcher
    assert "inheritHandles: false" in launcher
    assert "WaitForSingleObject" in launcher
    assert "TerminateProcess" in launcher


def test_notification_smoke_uses_installed_runtime_package_graph() -> None:
    root = ET.parse(NOTIFICATION_SMOKE_PROJECT).getroot()
    properties = {
        child.tag: child.text
        for group in root.findall("PropertyGroup")
        for child in group
    }

    assert properties["OutputType"] == "Exe"
    assert properties["WindowsPackageType"] == "None"
    assert properties["WindowsAppSDKSelfContained"] == "false"


def test_fixture_freshness_regenerates_every_normative_vector() -> None:
    job = _job(_workflow(), "protocol-fixture-freshness")
    assert job["runs-on"] == "ubuntu-latest"
    commands = _joined_commands(job)
    assert "uv sync --frozen" in commands
    assert "uv run --frozen python scripts/native/generate_golden_vectors.py" in commands
    assert "uv run --frozen python scripts/native/generate_projection_vectors.py" in commands
    for fixture in (
        "native-protocol-vectors.json",
        "native-projection-vectors.json",
        "native-protocol-invalid-vectors.json",
    ):
        assert f"{GOLDEN_ROOT}/{fixture}" in commands
    assert "git diff --exit-code" in commands
    assert '"status", "--porcelain", "--untracked-files=all"' in commands
    assert "if status.stdout:" in commands
    assert "raise SystemExit(1)" in commands


def test_live_job_runs_real_authenticated_loopback_journey_and_only_uploads_trx() -> None:
    job = _job(_workflow(), "live-bridge-window")
    assert job["runs-on"] == "windows-latest"
    assert _mapping(job["env"])["UV_NO_SYNC"] == "1"
    normalized = [_normalized(command) for command in _commands(job)]
    assert [command for command in normalized if command.startswith("uv sync ")] == [LOCKED_SYNC]
    commands = _joined_commands(job)
    assert "TestCategory=LiveBridge" in commands
    assert "--logger \"trx;LogFilePrefix=native-windows-live\"" in commands

    uploads = [
        step
        for step in _steps(job)
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert len(uploads) == 1
    upload = uploads[0]
    assert upload["if"] == "failure()"
    upload_config = _mapping(upload["with"])
    assert upload_config["path"] == "windows/BirkinNativeApp/**/TestResults/*.trx"
    assert upload_config["if-no-files-found"] == "error"
    assert upload_config["retention-days"] == 7


def test_swift_job_runs_the_full_package_suite() -> None:
    job = _job(_workflow(), "swift-conformance")
    assert job["runs-on"] == "macos-latest"
    assert _commands(job)[-1] == (
        "swift test --package-path macos/BirkinNativeApp --no-parallel"
    )


def test_provider_office_gate_is_manual_protected_and_requires_existing_account_runner() -> None:
    job = _job(_workflow(), "provider-office-gate")
    assert job["if"] == "github.event_name == 'workflow_dispatch' && github.ref_protected"
    assert job["environment"] == "native-windows-existing-account"
    assert job["runs-on"] == ["self-hosted", "Windows", "X64", "birkin-existing-account"]
    env = _mapping(job["env"])
    assert env["BIRKIN_EXISTING_ACCOUNT_RUNNER"] == "1"
    assert env["UV_NO_SYNC"] == "1"

    commands = [_normalized(command) for command in _commands(job)]
    assert LOCKED_SYNC in commands
    test_commands = [command for command in commands if command.startswith("dotnet test ")]
    assert len(test_commands) == 1
    assert re.findall(r'--filter "([^"]+)"', test_commands[0]) == [PROVIDER_FILTER]
    assert not any("${{ secrets." in command for command in commands)
    assert not any("upload-artifact@" in str(step.get("uses", "")) for step in _steps(job))


def test_all_jobs_have_timeouts_and_no_failure_bypasses_or_write_permissions() -> None:
    workflow = _workflow()
    raw = WORKFLOW.read_text(encoding="utf-8")
    assert "continue-on-error" not in raw
    assert "permissions:" in raw
    assert "write" not in raw
    assert "${{ secrets." not in raw
    for raw_job in _mapping(workflow["jobs"]).values():
        job = _mapping(raw_job)
        assert isinstance(job.get("timeout-minutes"), int)
        assert "permissions" not in job


def test_jobs_use_platform_appropriate_shell_commands() -> None:
    workflow = _workflow()
    for name in ("python-windows", "wpf-windows", "live-bridge-window"):
        for step in _steps(_job(workflow, name)):
            command = step.get("run")
            if not isinstance(command, str):
                continue
            assert step.get("shell", "pwsh") == "pwsh"
            assert not any(token in command for token in ("set -o pipefail", "mkdir -p", "tee "))
