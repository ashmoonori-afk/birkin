import json
from importlib.metadata import version as installed_version
from pathlib import Path
from typing import cast

import pytest

from birkin.office.adapters import adapter_provenance as publication
from birkin.office.adapters import catalog
from birkin.office.adapters.adapter_provenance import (
    MANIFEST_PATH,
    NOTICE_PATH,
    ProvenanceManifest,
    provenance_manifest,
    render_third_party_notices,
)
from birkin.office.adapters.catalog import adapter_inventory

REQUIRED_LOCKED_PACKAGES = {
    "pillow": (
        "12.3.0",
        "MIT-CMU",
        "https://files.pythonhosted.org/packages/1c/3d/bb7fca845737cf9d7dbde16ed1843984665ff2e0a518f5db43e77ec540b9/pillow-12.3.0.tar.gz",
        "3b8182a766685eaa002637e28b4ec8d6b18819a0c71f579bf0dbaa5830297cce",
    ),
    "rfc8785": (
        "0.1.4",
        "Apache-2.0",
        "https://files.pythonhosted.org/packages/ef/2f/fa1d2e740c490191b572d33dbca5daa180cb423c24396b856f5886371d8b/rfc8785-0.1.4.tar.gz",
        "e545841329fe0eee4f6a3b44e7034343100c12b4ec566dc06ca9735681deb4da",
    ),
    "xlsxwriter": (
        "3.2.9",
        "BSD-2-Clause",
        "https://files.pythonhosted.org/packages/46/2c/c06ef49dc36e7954e55b802a8b231770d286a9758b3d936bd1e04ce5ba88/xlsxwriter-3.2.9.tar.gz",
        "254b1c37a368c444eac6e2f867405cc9e461b0ed97a3233b2ac1e574efb4140c",
    ),
}

OPERATION_STATES = {
    "native",
    "lossless-surgical",
    "conversion-only",
    "read-only",
    "unsupported",
}


def test_external_candidates_are_never_unconditionally_selected() -> None:
    inventory = adapter_inventory()
    packages = [package for entry in inventory for package in entry["packages"]]

    assert packages
    assert all(
        all(
            package[field]
            for field in (
                "version",
                "version_range",
                "artifact_url",
                "artifact_sha256",
                "license",
                "license_sha256",
                "update_procedure",
            )
        )
        for package in packages
        if package["selection"] == "select"
    )
    assert all(
        package["install_probe"] and package["integration_mode"] for package in packages
    )
    assert all(
        package["refusal_reason"]
        for package in packages
        if package["selection"] == "refuse"
    )


def test_inventory_has_typed_operation_and_provenance_evidence() -> None:
    for adapter in adapter_inventory():
        assert all(
            operation["state"] in OPERATION_STATES
            and operation["integration_mode"]
            and operation["security_limits"]
            and operation["fidelity_limits"]
            for operation in adapter["capabilities"].values()
        )
        for package in adapter["packages"]:
            assert set(package) >= {
                "version",
                "version_range",
                "repository_url",
                "tag",
                "commit",
                "artifact_url",
                "artifact_sha256",
                "license",
                "license_sha256",
                "runtime_evidence",
                "os_evidence",
                "install_probe",
                "update_procedure",
                "refusal_reason",
            }


def test_required_office_packages_match_environment_manifest_and_notice() -> None:
    inventory = adapter_inventory()
    manifest_packages = {
        package["name"].casefold(): package
        for adapter in inventory
        for package in adapter["packages"]
    }
    notice = render_third_party_notices()
    for name, (version, license_name, artifact_url, artifact_sha256) in (
        REQUIRED_LOCKED_PACKAGES.items()
    ):
        package = manifest_packages[name]
        assert package["version"] == version == installed_version(package["name"])
        assert package["artifact_url"] == artifact_url
        assert package["artifact_sha256"] == artifact_sha256
        assert package["license"] == license_name
        assert package["license_sha256"]
        assert package["selection"] == "conditional"
        assert f"## {package['name']}\n" in notice
        assert f"- Exact version: {version}\n" in notice


def test_publications_read_the_authoritative_catalog_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(catalog, "adapter_inventory", list)
    assert publication.provenance_manifest()["inventory"] == []
    assert "## defusedxml" not in publication.render_third_party_notices()


def test_provenance_modules_obey_small_module_gate() -> None:
    package_dir = Path(publication.__file__).parent
    modules = [package_dir / "catalog.py", *package_dir.glob("*provenance*.py")]
    assert all(
        len(module.read_text(encoding="utf-8").splitlines()) <= 250
        for module in modules
    )


def test_catalog_operation_contract_matches_registered_runtime() -> None:
    inventory = {item["format"]: item["capabilities"] for item in adapter_inventory()}

    for format_name, capabilities in inventory.items():
        assert capabilities["extract"]["state"] == "read-only", format_name
        assert capabilities["compare"]["state"] == "read-only", format_name
        assert capabilities["compare"]["availability"] == "layered", format_name
        assert capabilities["validate"]["state"] == "read-only", format_name
        assert capabilities["convert"]["state"] == "conversion-only", format_name
        assert capabilities["render"]["state"] == "read-only", format_name
        assert capabilities["render"]["availability"] == "structured-preview-only"

    assert inventory["pdf"]["create"]["state"] == "native"
    assert inventory["pdf"]["create"]["availability"] == "bounded"
    assert inventory["hwpx"]["create"]["state"] == "native"
    assert inventory["hwpx"]["create"]["availability"] == "conditional"
    assert any(
        "blank authoring uses exact-pinned" in limitation.casefold()
        for limitation in next(
            item
            for item in adapter_inventory()
            if item["format"] == "hwpx"
        )["limitations"]
    )


def test_notice_and_manifest_are_exact_catalog_publications() -> None:
    tracked_manifest = cast(
        ProvenanceManifest,
        json.loads(MANIFEST_PATH.read_text(encoding="utf-8")),
    )
    assert tracked_manifest == provenance_manifest()
    assert NOTICE_PATH.read_text(encoding="utf-8") == render_third_party_notices()
    assert tracked_manifest["inventory"] == adapter_inventory()

    # Both publication surfaces live in the shipped package tree rather than a
    # runtime data directory.
    package_dir = Path(__file__).parents[2] / "birkin" / "office" / "adapters"
    assert MANIFEST_PATH.parent == package_dir
    assert NOTICE_PATH.parent == package_dir
