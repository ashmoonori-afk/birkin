"""Approved optional-package evidence referenced by adapter records."""

from __future__ import annotations

from .base import IntegrationMode, PublicationStatus, SelectionDecision
from .provenance_models import PackageRecord

_PYTHON_RUNTIME = "CPython >=3.10; package is imported lazily and is not bundled."
_PURE_PYTHON_OS = "OS-independent Python package according to the locked wheel."


def _published_package(
    *,
    name: str,
    version: str,
    version_range: str,
    repository_url: str,
    artifact_url: str,
    artifact_sha256: str,
    license_name: str,
    import_name: str,
    role: str,
    license_sha256: str | None = None,
    tag: str | None = None,
    os_evidence: str = _PURE_PYTHON_OS,
) -> PackageRecord:
    return PackageRecord(
        name=name,
        publication_status=PublicationStatus.PUBLISHED,
        integration_mode=IntegrationMode.OPTIONAL_PYTHON,
        selection=SelectionDecision.CONDITIONAL,
        version=version,
        version_range=version_range,
        repository_url=repository_url,
        tag=tag,
        commit=None,
        artifact_url=artifact_url,
        artifact_sha256=artifact_sha256,
        license=license_name,
        license_sha256=license_sha256,
        runtime_evidence=_PYTHON_RUNTIME,
        os_evidence=os_evidence,
        install_probe=f"python-import:{import_name}",
        update_procedure=(
            "Update the approved range and uv.lock together; verify the locked sdist "
            "SHA-256, upstream license expression and license-file SHA-256, then "
            "regenerate the manifest and notices."
        ),
        refusal_reason=None,
        role=role,
    )


DEFUSEDXML = _published_package(
    name="defusedxml",
    version="0.7.1",
    version_range=">=0.7,<1",
    repository_url="https://github.com/tiran/defusedxml",
    artifact_url="https://files.pythonhosted.org/packages/0f/d5/c66da9b79e5bdb124974bfe172b4daf3c984ebd9c2a06e2b8a4dc7331c72/defusedxml-0.7.1.tar.gz",
    artifact_sha256="1bb3032db185915b62d7c6209c5a8792be6a32ab2fedacc84e01b52c51aa3e69",
    license_name="PSF-2.0",
    import_name="defusedxml",
    role="Optional hardened XML parsing at validation boundaries.",
)

LXML = _published_package(
    name="lxml",
    version="6.1.1",
    version_range=">=5.3,<7",
    repository_url="https://github.com/lxml/lxml",
    artifact_url="https://files.pythonhosted.org/packages/05/3b/aab6728cae887456f409b4d75e8a01856e4f04bd510de38052a47768b680/lxml-6.1.1.tar.gz",
    artifact_sha256="ba96ae44888e0185281e937633a743ea90d5a196c6000f82565ebb0580012d40",
    license_name="BSD-3-Clause",
    import_name="lxml",
    role="Optional schema-aware deep XML validation.",
    os_evidence="Platform-specific wheels are lock-recorded; no universal OS claim.",
)

PYTHON_DOCX = _published_package(
    name="python-docx",
    version="1.2.0",
    version_range=">=1.2,<2",
    repository_url="https://github.com/python-openxml/python-docx",
    artifact_url="https://files.pythonhosted.org/packages/a9/f7/eddfe33871520adab45aaa1a71f0402a2252050c14c7e3009446c8f4701c/python_docx-1.2.0.tar.gz",
    artifact_sha256="7bc9d7b7d8a69c9c02ca09216118c86552704edc23bac179283f2e38f86220ce",
    license_name="MIT",
    import_name="docx",
    role="Conditional DOCX creation backend.",
)

OPENPYXL = _published_package(
    name="openpyxl",
    version="3.1.5",
    version_range=">=3.1.5,<4",
    repository_url="https://foss.heptapod.net/openpyxl/openpyxl",
    artifact_url="https://files.pythonhosted.org/packages/3d/f9/88d94a75de065ea32619465d2f77b29a0469500e99012523b91cc4141cd1/openpyxl-3.1.5.tar.gz",
    artifact_sha256="cf0e3cf56142039133628b5acffe8ef0c12bc902d2aadd3e0fe5878dc08d1050",
    license_name="MIT",
    import_name="openpyxl",
    role="Conditional XLSX creation backend.",
)

PYTHON_PPTX = _published_package(
    name="python-pptx",
    version="1.0.2",
    version_range=">=1.0.2,<2",
    repository_url="https://github.com/scanny/python-pptx",
    artifact_url="https://files.pythonhosted.org/packages/52/a9/0c0db8d37b2b8a645666f7fd8accea4c6224e013c42b1d5c17c93590cd06/python_pptx-1.0.2.tar.gz",
    artifact_sha256="479a8af0eaf0f0d76b6f00b0887732874ad2e3188230315290cd1f9dd9cc7095",
    license_name="MIT",
    import_name="pptx",
    role="Conditional PPTX creation backend.",
)

PYPDF = _published_package(
    name="pypdf",
    version="6.16.1",
    version_range=">=5.9,<7",
    repository_url="https://github.com/py-pdf/pypdf",
    artifact_url="https://files.pythonhosted.org/packages/b6/5a/df92d1c1ef8806ca28f20f978ee059894868d93de797a7e2edebe7fe1a43/pypdf-6.16.1.tar.gz",
    artifact_sha256="c4d1b43ddae921387321cf63936cd16a7743b91d2da92f165c149a195c972ba9",
    license_name="BSD-3-Clause",
    import_name="pypdf",
    role="Approved optional PDF inspection and bounded native-text extraction backend, wired lazily through PdfAdapter.",
)

PILLOW = _published_package(
    name="Pillow",
    version="12.3.0",
    version_range=">=11,<13",
    repository_url="https://github.com/python-pillow/Pillow",
    artifact_url="https://files.pythonhosted.org/packages/1c/3d/bb7fca845737cf9d7dbde16ed1843984665ff2e0a518f5db43e77ec540b9/pillow-12.3.0.tar.gz",
    artifact_sha256="3b8182a766685eaa002637e28b4ec8d6b18819a0c71f579bf0dbaa5830297cce",
    license_name="MIT-CMU",
    license_sha256="15181e7363dca9aed78b79bebebc7fde7f1814b8bd311ea3b87ae8ccadfc185b",
    tag="12.3.0",
    import_name="PIL",
    role=(
        "Office advanced image codec and python-pptx transitive dependency; package "
        "discovery alone does not establish an adapter capability."
    ),
    os_evidence="Platform-specific wheels are lock-recorded; no universal OS claim.",
)

RFC8785 = _published_package(
    name="rfc8785",
    version="0.1.4",
    version_range=">=0.1.4,<1",
    repository_url="https://github.com/trailofbits/rfc8785.py",
    artifact_url="https://files.pythonhosted.org/packages/ef/2f/fa1d2e740c490191b572d33dbca5daa180cb423c24396b856f5886371d8b/rfc8785-0.1.4.tar.gz",
    artifact_sha256="e545841329fe0eee4f6a3b44e7034343100c12b4ec566dc06ca9735681deb4da",
    license_name="Apache-2.0",
    license_sha256="0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594",
    tag="v0.1.4",
    import_name="rfc8785",
    role=(
        "Shared Office JSON Canonicalization Scheme dependency; no format "
        "capability is inferred from installation."
    ),
)

XLSXWRITER = _published_package(
    name="XlsxWriter",
    version="3.2.9",
    version_range=">=0.5.7",
    repository_url="https://github.com/jmcnamara/XlsxWriter",
    artifact_url="https://files.pythonhosted.org/packages/46/2c/c06ef49dc36e7954e55b802a8b231770d286a9758b3d936bd1e04ce5ba88/xlsxwriter-3.2.9.tar.gz",
    artifact_sha256="254b1c37a368c444eac6e2f867405cc9e461b0ed97a3233b2ac1e574efb4140c",
    license_name="BSD-2-Clause",
    license_sha256="cf08b60a4ded986b58a617cb8304373bda5c4eff42fb4e30d7597b616e116e87",
    tag="RELEASE_3.2.9",
    import_name="xlsxwriter",
    role=(
        "Locked python-pptx dependency for embedded chart workbooks; it is not "
        "Birkin's XLSX adapter backend."
    ),
)

PYPDFIUM2 = _published_package(
    name="pypdfium2",
    version="4.30.0",
    version_range=">=4.30,<5",
    repository_url="https://github.com/pypdfium2-team/pypdfium2",
    artifact_url="https://files.pythonhosted.org/packages/a1/14/838b3ba247a0ba92e4df5d23f2bea9478edcfd72b78a39d6ca36ccd84ad2/pypdfium2-4.30.0.tar.gz",
    artifact_sha256="48b5b7e5566665bc1015b9d69c1ebabe21f6aee468b509531c3c8318eeee2e16",
    license_name="(Apache-2.0 OR BSD-3-Clause) AND LicenseRef-PdfiumThirdParty",
    import_name="pypdfium2",
    role="Approved optional PDF rasterization candidate; not wired as a capability.",
    os_evidence="Platform-specific PDFium wheels; runtime support varies by OS/architecture.",
)
