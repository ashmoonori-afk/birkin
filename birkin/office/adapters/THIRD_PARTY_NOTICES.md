# Office adapter third-party provenance

This file is generated from `birkin.office.adapters.catalog`. Packages are
optional or refused candidates; none is bundled or unconditionally selected.
Operation capability comes from the inventory, not package discovery alone.

Catalog revision: 6
Inventory SHA-256: `a9a8459320ffa05cbd7e93ecbee414e65574f057ff9703eb3e727020a3112168`

## defusedxml

- Publication: published
- Decision: conditional
- Integration: optional-python
- Exact version: 0.7.1
- Approved range: >=0.7,<1
- Repository: https://github.com/tiran/defusedxml
- Tag: not proven
- Commit: not proven
- Artifact: https://files.pythonhosted.org/packages/0f/d5/c66da9b79e5bdb124974bfe172b4daf3c984ebd9c2a06e2b8a4dc7331c72/defusedxml-0.7.1.tar.gz
- Artifact SHA-256: 1bb3032db185915b62d7c6209c5a8792be6a32ab2fedacc84e01b52c51aa3e69
- License expression: PSF-2.0
- License text SHA-256: not proven
- Runtime evidence: CPython >=3.10; package is imported lazily and is not bundled.
- OS evidence: OS-independent Python package according to the locked wheel.
- Install probe: `python-import:defusedxml`
- Update procedure: Update the approved range and uv.lock together; verify the locked sdist SHA-256, upstream license expression and license-file SHA-256, then regenerate the manifest and notices.
- Refusal reason: not proven
- Role: Optional hardened XML parsing at validation boundaries.

## lxml

- Publication: published
- Decision: conditional
- Integration: optional-python
- Exact version: 6.1.1
- Approved range: >=5.3,<7
- Repository: https://github.com/lxml/lxml
- Tag: not proven
- Commit: not proven
- Artifact: https://files.pythonhosted.org/packages/05/3b/aab6728cae887456f409b4d75e8a01856e4f04bd510de38052a47768b680/lxml-6.1.1.tar.gz
- Artifact SHA-256: ba96ae44888e0185281e937633a743ea90d5a196c6000f82565ebb0580012d40
- License expression: BSD-3-Clause
- License text SHA-256: not proven
- Runtime evidence: CPython >=3.10; package is imported lazily and is not bundled.
- OS evidence: Platform-specific wheels are lock-recorded; no universal OS claim.
- Install probe: `python-import:lxml`
- Update procedure: Update the approved range and uv.lock together; verify the locked sdist SHA-256, upstream license expression and license-file SHA-256, then regenerate the manifest and notices.
- Refusal reason: not proven
- Role: Optional schema-aware deep XML validation.

## openpyxl

- Publication: published
- Decision: conditional
- Integration: optional-python
- Exact version: 3.1.5
- Approved range: >=3.1.5,<4
- Repository: https://foss.heptapod.net/openpyxl/openpyxl
- Tag: not proven
- Commit: not proven
- Artifact: https://files.pythonhosted.org/packages/3d/f9/88d94a75de065ea32619465d2f77b29a0469500e99012523b91cc4141cd1/openpyxl-3.1.5.tar.gz
- Artifact SHA-256: cf0e3cf56142039133628b5acffe8ef0c12bc902d2aadd3e0fe5878dc08d1050
- License expression: MIT
- License text SHA-256: not proven
- Runtime evidence: CPython >=3.10; package is imported lazily and is not bundled.
- OS evidence: OS-independent Python package according to the locked wheel.
- Install probe: `python-import:openpyxl`
- Update procedure: Update the approved range and uv.lock together; verify the locked sdist SHA-256, upstream license expression and license-file SHA-256, then regenerate the manifest and notices.
- Refusal reason: not proven
- Role: Conditional XLSX creation backend.

## Pillow

- Publication: published
- Decision: conditional
- Integration: optional-python
- Exact version: 12.3.0
- Approved range: >=11,<13
- Repository: https://github.com/python-pillow/Pillow
- Tag: 12.3.0
- Commit: not proven
- Artifact: https://files.pythonhosted.org/packages/1c/3d/bb7fca845737cf9d7dbde16ed1843984665ff2e0a518f5db43e77ec540b9/pillow-12.3.0.tar.gz
- Artifact SHA-256: 3b8182a766685eaa002637e28b4ec8d6b18819a0c71f579bf0dbaa5830297cce
- License expression: MIT-CMU
- License text SHA-256: 15181e7363dca9aed78b79bebebc7fde7f1814b8bd311ea3b87ae8ccadfc185b
- Runtime evidence: CPython >=3.10; package is imported lazily and is not bundled.
- OS evidence: Platform-specific wheels are lock-recorded; no universal OS claim.
- Install probe: `python-import:PIL`
- Update procedure: Update the approved range and uv.lock together; verify the locked sdist SHA-256, upstream license expression and license-file SHA-256, then regenerate the manifest and notices.
- Refusal reason: not proven
- Role: Office advanced image codec and python-pptx transitive dependency; package discovery alone does not establish an adapter capability.

## pypdf

- Publication: published
- Decision: conditional
- Integration: optional-python
- Exact version: 6.16.1
- Approved range: >=5.9,<7
- Repository: https://github.com/py-pdf/pypdf
- Tag: not proven
- Commit: not proven
- Artifact: https://files.pythonhosted.org/packages/b6/5a/df92d1c1ef8806ca28f20f978ee059894868d93de797a7e2edebe7fe1a43/pypdf-6.16.1.tar.gz
- Artifact SHA-256: c4d1b43ddae921387321cf63936cd16a7743b91d2da92f165c149a195c972ba9
- License expression: BSD-3-Clause
- License text SHA-256: not proven
- Runtime evidence: CPython >=3.10; package is imported lazily and is not bundled.
- OS evidence: OS-independent Python package according to the locked wheel.
- Install probe: `python-import:pypdf`
- Update procedure: Update the approved range and uv.lock together; verify the locked sdist SHA-256, upstream license expression and license-file SHA-256, then regenerate the manifest and notices.
- Refusal reason: not proven
- Role: Approved optional PDF inspection and bounded native-text extraction backend, wired lazily through PdfAdapter.

## pypdfium2

- Publication: published
- Decision: conditional
- Integration: optional-python
- Exact version: 4.30.0
- Approved range: >=4.30,<5
- Repository: https://github.com/pypdfium2-team/pypdfium2
- Tag: not proven
- Commit: not proven
- Artifact: https://files.pythonhosted.org/packages/a1/14/838b3ba247a0ba92e4df5d23f2bea9478edcfd72b78a39d6ca36ccd84ad2/pypdfium2-4.30.0.tar.gz
- Artifact SHA-256: 48b5b7e5566665bc1015b9d69c1ebabe21f6aee468b509531c3c8318eeee2e16
- License expression: (Apache-2.0 OR BSD-3-Clause) AND LicenseRef-PdfiumThirdParty
- License text SHA-256: not proven
- Runtime evidence: CPython >=3.10; package is imported lazily and is not bundled.
- OS evidence: Platform-specific PDFium wheels; runtime support varies by OS/architecture.
- Install probe: `python-import:pypdfium2`
- Update procedure: Update the approved range and uv.lock together; verify the locked sdist SHA-256, upstream license expression and license-file SHA-256, then regenerate the manifest and notices.
- Refusal reason: not proven
- Role: Approved optional PDF rasterization candidate; not wired as a capability.

## python-docx

- Publication: published
- Decision: conditional
- Integration: optional-python
- Exact version: 1.2.0
- Approved range: >=1.2,<2
- Repository: https://github.com/python-openxml/python-docx
- Tag: not proven
- Commit: not proven
- Artifact: https://files.pythonhosted.org/packages/a9/f7/eddfe33871520adab45aaa1a71f0402a2252050c14c7e3009446c8f4701c/python_docx-1.2.0.tar.gz
- Artifact SHA-256: 7bc9d7b7d8a69c9c02ca09216118c86552704edc23bac179283f2e38f86220ce
- License expression: MIT
- License text SHA-256: not proven
- Runtime evidence: CPython >=3.10; package is imported lazily and is not bundled.
- OS evidence: OS-independent Python package according to the locked wheel.
- Install probe: `python-import:docx`
- Update procedure: Update the approved range and uv.lock together; verify the locked sdist SHA-256, upstream license expression and license-file SHA-256, then regenerate the manifest and notices.
- Refusal reason: not proven
- Role: Conditional DOCX creation backend.

## python-hwpx

- Publication: published
- Decision: conditional
- Integration: optional-python
- Exact version: 6.1.0
- Approved range: ==6.1.0
- Repository: https://github.com/airmang/python-hwpx
- Tag: v6.1.0
- Commit: not proven
- Artifact: https://files.pythonhosted.org/packages/cc/62/85356d56026fe5079f1a8b65b20ab036356be94a9d04985649a8aebd8eac/python_hwpx-6.1.0.tar.gz
- Artifact SHA-256: b607a6fb543f1b8d1bf6e2b28b3607085bf60aade06a9acf9ca795d87a9eaabf
- License expression: Apache-2.0
- License text SHA-256: fee6f3e30bfe064913de5de0bbe42e1fb2467958ee458199a192bde5e36c0875
- Runtime evidence: CPython >=3.10; package is imported lazily and is not bundled.
- OS evidence: OS-independent Python package according to the locked wheel.
- Install probe: `python-import:hwpx`
- Update procedure: Update the approved range and uv.lock together; verify the locked sdist SHA-256, upstream license expression and license-file SHA-256, then regenerate the manifest and notices.
- Refusal reason: not proven
- Role: Exact-pinned local Python HWPX blank-authoring backend.

## python-pptx

- Publication: published
- Decision: conditional
- Integration: optional-python
- Exact version: 1.0.2
- Approved range: >=1.0.2,<2
- Repository: https://github.com/scanny/python-pptx
- Tag: not proven
- Commit: not proven
- Artifact: https://files.pythonhosted.org/packages/52/a9/0c0db8d37b2b8a645666f7fd8accea4c6224e013c42b1d5c17c93590cd06/python_pptx-1.0.2.tar.gz
- Artifact SHA-256: 479a8af0eaf0f0d76b6f00b0887732874ad2e3188230315290cd1f9dd9cc7095
- License expression: MIT
- License text SHA-256: not proven
- Runtime evidence: CPython >=3.10; package is imported lazily and is not bundled.
- OS evidence: OS-independent Python package according to the locked wheel.
- Install probe: `python-import:pptx`
- Update procedure: Update the approved range and uv.lock together; verify the locked sdist SHA-256, upstream license expression and license-file SHA-256, then regenerate the manifest and notices.
- Refusal reason: not proven
- Role: Conditional PPTX creation backend.

## ReportLab

- Publication: published
- Decision: refuse
- Integration: optional-python
- Exact version: not proven
- Approved range: not proven
- Repository: https://github.com/MrBitBucket/reportlab-mirror
- Tag: not proven
- Commit: not proven
- Artifact: not proven
- Artifact SHA-256: not proven
- License expression: not proven
- License text SHA-256: not proven
- Runtime evidence: No approved project dependency or lock artifact.
- OS evidence: Not evaluated.
- Install probe: `approval-required:reportlab`
- Update procedure: Add an approved dependency range and lock artifact, verify license evidence, then regenerate the manifest and notices.
- Refusal reason: Not present in an approved dependency extra or the lock as a direct package.
- Role: Refused PDF creation candidate; it does not establish a capability.

## rfc8785

- Publication: published
- Decision: conditional
- Integration: optional-python
- Exact version: 0.1.4
- Approved range: >=0.1.4,<1
- Repository: https://github.com/trailofbits/rfc8785.py
- Tag: v0.1.4
- Commit: not proven
- Artifact: https://files.pythonhosted.org/packages/ef/2f/fa1d2e740c490191b572d33dbca5daa180cb423c24396b856f5886371d8b/rfc8785-0.1.4.tar.gz
- Artifact SHA-256: e545841329fe0eee4f6a3b44e7034343100c12b4ec566dc06ca9735681deb4da
- License expression: Apache-2.0
- License text SHA-256: 0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594
- Runtime evidence: CPython >=3.10; package is imported lazily and is not bundled.
- OS evidence: OS-independent Python package according to the locked wheel.
- Install probe: `python-import:rfc8785`
- Update procedure: Update the approved range and uv.lock together; verify the locked sdist SHA-256, upstream license expression and license-file SHA-256, then regenerate the manifest and notices.
- Refusal reason: not proven
- Role: Shared Office JSON Canonicalization Scheme dependency; no format capability is inferred from installation.

## XlsxWriter

- Publication: published
- Decision: conditional
- Integration: optional-python
- Exact version: 3.2.9
- Approved range: >=0.5.7
- Repository: https://github.com/jmcnamara/XlsxWriter
- Tag: RELEASE_3.2.9
- Commit: not proven
- Artifact: https://files.pythonhosted.org/packages/46/2c/c06ef49dc36e7954e55b802a8b231770d286a9758b3d936bd1e04ce5ba88/xlsxwriter-3.2.9.tar.gz
- Artifact SHA-256: 254b1c37a368c444eac6e2f867405cc9e461b0ed97a3233b2ac1e574efb4140c
- License expression: BSD-2-Clause
- License text SHA-256: cf08b60a4ded986b58a617cb8304373bda5c4eff42fb4e30d7597b616e116e87
- Runtime evidence: CPython >=3.10; package is imported lazily and is not bundled.
- OS evidence: OS-independent Python package according to the locked wheel.
- Install probe: `python-import:xlsxwriter`
- Update procedure: Update the approved range and uv.lock together; verify the locked sdist SHA-256, upstream license expression and license-file SHA-256, then regenerate the manifest and notices.
- Refusal reason: not proven
- Role: Locked python-pptx dependency for embedded chart workbooks; it is not Birkin's XLSX adapter backend.

## Format specifications and internal implementation

Built-in inspection and lossless-surgical operations use Birkin's internal
implementation. The machine manifest records each cited format specification,
security limit, fidelity limit, operation state, and availability separately.
