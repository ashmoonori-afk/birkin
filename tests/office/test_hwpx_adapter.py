import zipfile
from pathlib import Path

from birkin.office.adapters.catalog import adapter_inventory
from birkin.office.adapters.hwpx import HwpxAdapter
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


def test_hwpx_inventory_uses_only_local_python_packages() -> None:
    hwpx = next(
        record for record in adapter_inventory() if record["format"] == "hwpx"
    )
    packages = {str(package["name"]).lower() for package in hwpx["packages"]}
    assert packages == {"python-hwpx", "defusedxml", "lxml", "rfc8785"}
    assert all("external" not in package["integration_mode"] for package in hwpx["packages"])
