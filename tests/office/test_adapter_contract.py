import importlib
from pathlib import Path

from birkin.office.adapters.base import CapabilityState, default_capabilities
from birkin.office.service import DocumentService

FORMATS = {"docx", "xlsx", "pptx", "pdf", "hwpx"}
CAPABILITIES = {
    "inspect",
    "extract",
    "create",
    "compare",
    "fill",
    "patch",
    "render",
    "validate",
    "convert",
}


def test_adapter_capabilities_are_exhaustive_and_missing_extras_do_not_import_crash():
    caps = default_capabilities(read_only=True)
    assert set(caps) == CAPABILITIES
    assert all(
        c.state
        in {
            CapabilityState.AVAILABLE,
            CapabilityState.UNAVAILABLE,
            CapabilityState.READ_ONLY,
        }
        and c.reason
        for c in caps.values()
    )
    assert importlib.import_module("birkin")


def test_service_inventory_has_verified_provenance_and_truthful_capabilities(
    tmp_path: Path,
) -> None:
    inventory = DocumentService(tmp_path).adapter_inventory()
    assert {entry["format"] for entry in inventory} == FORMATS

    for entry in inventory:
        assert entry["standard_url"].startswith("https://")
        assert set(entry["capabilities"]) == CAPABILITIES
        assert all(
            capability["state"]
            in {
                "native",
                "lossless-surgical",
                "conversion-only",
                "read-only",
                "unsupported",
            }
            and capability["reason"]
            and capability["availability"]
            for capability in entry["capabilities"].values()
        )
        assert entry["packages"]
        assert all(
            package["name"]
            and package["repository_url"].startswith("https://")
            and (
                package["selection"] in {"conditional", "refuse"}
                or (
                    package["name"] == "defusedxml"
                    and package["integration_mode"] == "core-python"
                    and package["selection"] == "select"
                )
            )
            for package in entry["packages"]
        )

    by_format = {entry["format"]: entry for entry in inventory}
    assert by_format["docx"]["packages"][0]["name"] == "python-docx"
    assert by_format["xlsx"]["packages"][0]["name"] == "openpyxl"
    assert by_format["pptx"]["packages"][0]["name"] == "python-pptx"
    assert {package["name"] for package in by_format["pdf"]["packages"]} >= {
        "Pillow",
        "pypdf",
        "pypdfium2",
        "ReportLab",
        "rfc8785",
    }
    assert all(
        "rfc8785" in {package["name"] for package in entry["packages"]}
        for entry in inventory
    )
    assert {"Pillow", "XlsxWriter"} <= {
        package["name"] for package in by_format["pptx"]["packages"]
    }
    hwpx_packages = {
        package["name"]: package
        for package in by_format["hwpx"]["packages"]
    }
    python_hwpx = hwpx_packages["python-hwpx"]
    assert python_hwpx["version"] == "6.1.0"
    assert python_hwpx["version_range"] == "==6.1.0"
    assert python_hwpx["license"] == "Apache-2.0"
    assert python_hwpx["integration_mode"] == "optional-python"
    assert all(not name.startswith("@handoc/") for name in hwpx_packages)
