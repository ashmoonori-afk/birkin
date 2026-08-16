from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from typing import NoReturn

import pytest

from birkin.office.adapters.base import Capability, CapabilityState
from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.handoc_child_process import drain_bounded, read_capture
from birkin.office.handoc_execution import execute_handoc
from birkin.office.handoc_process import (
    MAX_CAPTURE_BYTES,
    REQUIRED_NODE_VERSION,
    Cancellation,
    HanDocProcess,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def _configuration(tmp_path: Path, *, timeout: float = 0.25) -> dict[str, object]:
    runtime = tmp_path / "runtime"
    modules = tmp_path / "modules"
    runtime.mkdir(parents=True)
    modules.mkdir()
    runner = runtime / "isolate"
    node = runtime / "node"
    tool = modules / "pinned-tool.js"
    _ = runner.write_bytes(b"approved isolation runner")
    _ = node.write_bytes(b"approved node")
    _ = tool.write_text("// approved tool", encoding="utf-8")
    manifest = modules / "package.json"
    _ = manifest.write_text(
        '{"dependencies":{"@handoc/hwpx-parser":"0.1.0",'
        + '"@handoc/hwpx-writer":"0.1.0"}}',
        encoding="utf-8",
    )
    return {
        "isolation_runner_path": str(runner.resolve()),
        "isolation_runner_sha256": _sha256(runner),
        "isolation_protocol": "birkin-handoc-isolation-v1",
        "node_path": str(node.resolve()),
        "node_sha256": _sha256(node),
        "node_version": REQUIRED_NODE_VERSION,
        "module_root": str(modules.resolve()),
        "module_tree_sha256": _tree_sha256(modules),
        "package_manifest_sha256": _sha256(manifest),
        "tool_sha256": {"pinned-tool.js": _sha256(tool)},
        "timeout_seconds": timeout,
    }


@pytest.mark.parametrize(
    "removed",
    ["isolation_runner_path", "isolation_runner_sha256", "node_sha256", "module_tree_sha256"],
)
def test_capability_fails_closed_without_every_isolation_identity(
    tmp_path: Path, removed: str
) -> None:
    config = _configuration(tmp_path)
    del config[removed]
    capability = HanDocProcess(config).capability()
    assert capability.state is CapabilityState.UNAVAILABLE
    assert "not configured or identity-bound" in capability.reason


def test_mutated_runner_node_or_module_input_is_refused(tmp_path: Path) -> None:
    for target in ("isolation_runner_path", "node_path"):
        config = _configuration(tmp_path / target)
        _ = Path(str(config[target])).write_bytes(b"mutated")
        capability = HanDocProcess(config).capability()
        assert capability.state is CapabilityState.UNAVAILABLE
        assert "not configured or identity-bound" in capability.reason

    config = _configuration(tmp_path / "module")
    _ = (Path(str(config["module_root"])) / "pinned-tool.js").write_bytes(b"mutated")
    capability = HanDocProcess(config).capability()
    assert capability.state is CapabilityState.UNAVAILABLE
    assert "not configured or identity-bound" in capability.reason


def test_mutable_runtime_bundle_is_refused_before_process_factory(
    tmp_path: Path,
) -> None:
    config = _configuration(tmp_path)
    started = False

    def clear_replace_then_launch(
        args: Sequence[str], **kwargs: object
    ) -> NoReturn:
        _ = kwargs
        nonlocal started
        started = True
        separator = args.index("--")
        for index, label in (
            (0, "runner"),
            (separator + 1, "node"),
            (separator + 2, "tool"),
        ):
            path = Path(args[index])
            if hasattr(os, "chflags"):
                os.chflags(path, 0)
            os.chmod(path, 0o700)
            attacker = tmp_path / f"attacker-{label}"
            _ = attacker.write_bytes(f"attacker {label}".encode())
            os.replace(attacker, path)
        raise AssertionError("mutable HanDoc bundle reached process creation")

    handoc = HanDocProcess(config, process_factory=clear_replace_then_launch)
    capability = handoc.capability()

    assert capability.state is CapabilityState.UNAVAILABLE
    assert "descriptor-bound" in capability.reason
    with pytest.raises(DocumentError) as caught:
        _ = handoc.execute(["pinned-tool.js"])
    assert caught.value.code is DocumentErrorCode.CAPABILITY_UNAVAILABLE
    assert "descriptor-bound" in caught.value.message
    assert not started


def test_execution_layer_refuses_even_if_capability_claims_available() -> None:
    started = False

    def process_factory(args: Sequence[str], **kwargs: object) -> NoReturn:
        _ = args, kwargs
        nonlocal started
        started = True
        raise AssertionError("HanDoc process creation must remain unreachable")

    with pytest.raises(DocumentError) as caught:
        _ = execute_handoc(
            {},
            ["pinned-tool.js"],
            capability=lambda: Capability(CapabilityState.AVAILABLE, "injected"),
            required_packages={},
            timeout=0.25,
            process_factory=process_factory,
            cancellation=None,
        )

    assert caught.value.code is DocumentErrorCode.CAPABILITY_UNAVAILABLE
    assert "descriptor-bound" in caught.value.message
    assert not started


def test_replaced_configured_inputs_fail_identity_scan_without_launch(
    tmp_path: Path,
) -> None:
    config = _configuration(tmp_path)
    runner = Path(str(config["isolation_runner_path"]))
    replacement = tmp_path / "attacker-runner"
    _ = replacement.write_bytes(b"attacker runner")
    os.replace(replacement, runner)
    started = False

    def process_factory(args: Sequence[str], **kwargs: object) -> NoReturn:
        _ = args, kwargs
        nonlocal started
        started = True
        raise AssertionError("identity scan failure reached process creation")

    handoc = HanDocProcess(config, process_factory=process_factory)
    capability = handoc.capability()
    assert capability.state is CapabilityState.UNAVAILABLE
    assert "not configured or identity-bound" in capability.reason
    with pytest.raises(DocumentError) as caught:
        _ = handoc.execute(["pinned-tool.js"])
    assert caught.value.code is DocumentErrorCode.CAPABILITY_UNAVAILABLE
    assert not started


def test_file_backed_capture_returns_only_bounded_output() -> None:
    source = BytesIO(b"x" * (MAX_CAPTURE_BYTES * 2))
    capture = BytesIO()
    errors: list[OSError] = []

    drain_bounded(source, capture, errors)

    assert errors == []
    assert len(read_capture(capture).encode()) == MAX_CAPTURE_BYTES


def test_timeout_configuration_never_reaches_unavailable_process(
    tmp_path: Path,
) -> None:
    started = False

    def process_factory(args: Sequence[str], **kwargs: object) -> NoReturn:
        _ = args, kwargs
        nonlocal started
        started = True
        raise AssertionError("unavailable HanDoc process was started")

    handoc = HanDocProcess(
        _configuration(tmp_path, timeout=0.001),
        process_factory=process_factory,
    )
    with pytest.raises(DocumentError) as caught:
        _ = handoc.execute(["pinned-tool.js"])
    assert caught.value.code is DocumentErrorCode.CAPABILITY_UNAVAILABLE
    assert not started


def test_pre_cancelled_request_never_starts_process(tmp_path: Path) -> None:
    cancellation = Cancellation()
    cancellation.cancel()
    started = False

    def process_factory(args: Sequence[str], **kwargs: object) -> NoReturn:
        _ = args, kwargs
        nonlocal started
        started = True
        raise AssertionError("cancelled HanDoc process was started")

    with pytest.raises(DocumentError, match="cancelled"):
        _ = HanDocProcess(
            _configuration(tmp_path), process_factory=process_factory
        ).execute(["pinned-tool.js"], cancellation=cancellation)
    assert not started
