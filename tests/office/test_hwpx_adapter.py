import hashlib
import subprocess
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from birkin.office.adapters.base import CapabilityState
from birkin.office.adapters.hwpx import HwpxAdapter
from birkin.office.handoc_process import (
    REQUIRED_NODE_VERSION,
    REQUIRED_PACKAGES,
    HanDocProcess,
)
from tests.office.fixture_builders import build_hwpx_template


def test_hwpx_inventory_and_narrow_field_patch_preserve_unknown_xml(
    tmp_path: Path,
) -> None:
    source = build_hwpx_template(tmp_path / "form-table.hwpx")
    adapter = HwpxAdapter()
    info = adapter.inspect(source)
    assert {"sections", "paragraphs", "fields", "tables", "fonts"} <= info.keys()
    before = adapter.part_hashes(source)
    output = tmp_path / "draft.hwpx"
    _ = adapter.patch_field(source, output, "customer", "Ada")
    after = adapter.part_hashes(output)
    assert before["Contents/opaque.xml"] == after["Contents/opaque.xml"]
    with zipfile.ZipFile(output) as archive:
        assert b"Ada" in archive.read("Contents/section0.xml")


def test_missing_node_or_handoc_is_clean_capability_result():
    cap = HanDocProcess({}).capability()
    assert cap.install_hint is not None
    assert cap.state is CapabilityState.UNAVAILABLE
    assert "Node.js 22.14.0 x64" in cap.install_hint
    assert "@handoc/hwpx-parser@0.1.0" in cap.install_hint


def test_handoc_process_requires_pinned_isolation_beyond_package_manifest(
    tmp_path: Path,
) -> None:
    calls: list[tuple[Sequence[str], dict[str, object]]] = []

    def run(
        args: Sequence[str],
        *,
        capture_output: bool,
        text: bool,
        timeout: float,
        check: bool,
        env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        calls.append(
            (
                args,
                {
                    "capture_output": capture_output,
                    "text": text,
                    "timeout": timeout,
                    "check": check,
                    "env": env,
                },
            )
        )
        return subprocess.CompletedProcess(
            args,
            0,
            stdout="v22.14.0\n",
            stderr="",
        )

    manifest = tmp_path / "package.json"
    manifest_content = (
        '{"dependencies":{"@handoc/hwpx-parser":"0.1.0",'
        + '"@handoc/hwpx-writer":"0.1.0"}}'
    )
    _ = manifest.write_text(manifest_content)
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    cfg: dict[str, object] = {
        "node_path": "/verified/node",
        "node_version": REQUIRED_NODE_VERSION,
        "module_root": str(tmp_path),
        "package_manifest_sha256": digest,
        "timeout_seconds": 5,
    }
    capability = HanDocProcess(cfg, runner=run).capability()
    assert capability.state is CapabilityState.UNAVAILABLE
    assert "isolation" in capability.reason.lower()
    assert calls == []
    assert (
        HanDocProcess({**cfg, "node_version": "22.13.0"}, runner=run).capability().state
        is CapabilityState.UNAVAILABLE
    )


def test_handoc_required_packages_exclude_unverified_pdf_export():
    assert REQUIRED_PACKAGES == {
        "@handoc/hwpx-parser": "0.1.0",
        "@handoc/hwpx-writer": "0.1.0",
    }
