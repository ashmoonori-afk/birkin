from __future__ import annotations

import zipfile
from pathlib import Path

from pptx import Presentation

from birkin.office.adapters.pptx import PptxAdapter

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"


def _rels(*relations: str) -> bytes:
    return (f'<Relationships xmlns="{PR}">' + "".join(relations) + "</Relationships>").encode()


def _relation(identifier: str, kind: str, target: str, *, external: bool = False) -> str:
    mode = ' TargetMode="External"' if external else ""
    return f'<Relationship Id="{identifier}" Type="{R}/{kind}" Target="{target}"{mode}/>'


def _shape(
    identifier: int,
    name: str,
    text: str,
    *,
    geometry: tuple[int, int, int, int] | None,
    body: str = "",
    placeholder: str = "",
    font: str = "",
    body_children: str = "",
    rotation: int = 0,
) -> str:
    transform = ""
    if geometry is not None:
        x, y, width, height = geometry
        transform = f'<p:spPr><a:xfrm rot="{rotation}"><a:off x="{x}" y="{y}"/><a:ext cx="{width}" cy="{height}"/></a:xfrm></p:spPr>'
    body_markup = f'<a:bodyPr {body}>{body_children}</a:bodyPr>'
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{identifier}" name="{name}"/><p:cNvSpPr/><p:nvPr>{placeholder}</p:nvPr></p:nvSpPr>'
        f'{transform}<p:txBody>{body_markup}<a:lstStyle/><a:p><a:r><a:rPr sz="1800">{font}</a:rPr><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>'
    )


def _package(path: Path) -> Path:
    placeholder = _shape(
        2,
        "Inherited placeholder",
        "This inherited placeholder text is deliberately much too long",
        geometry=None,
        placeholder='<p:ph type="body" idx="7"/>',
    )
    clipped = _shape(
        3,
        "Clipped Korean",
        "한국어 text that is deliberately much too long for its tiny box",
        geometry=(9_700_000, 100_000, 600_000, 250_000),
        body='vertOverflow="clip" wrap="square"',
        font='<a:latin typeface="Fixture Latin"/>',
    )
    autofit = _shape(
        4,
        "Autofit",
        "Autofit text is long but must not be called proven overflow",
        geometry=(100_000, 500_000, 500_000, 100_000),
        body_children='<a:normAutofit fontScale="50000"/>',
    )
    rotated = _shape(
        7,
        "Rotated edge",
        "rotated",
        geometry=(9_600_000, 6_900_000, 300_000, 200_000),
        rotation=2_700_000,
    )
    table = (
        '<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="8" name="Overflow table"/>'
        '<p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>'
        '<p:xfrm><a:off x="1000000" y="1000000"/><a:ext cx="1000000" cy="100000"/></p:xfrm>'
        '<a:graphic><a:graphicData><a:tbl><a:tr h="80000"/><a:tr h="80000"/>'
        '</a:tbl></a:graphicData></a:graphic></p:graphicFrame>'
    )
    slide = (
        f'<p:sld xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}"><p:cSld><p:spTree>'
        f'{placeholder}{clipped}{autofit}{rotated}{table}'
        '<p:pic><p:nvPicPr><p:cNvPr id="5" name="Missing image"/></p:nvPicPr><p:blipFill><a:blip r:embed="rIdImage"/></p:blipFill></p:pic>'
        '<p:pic><p:nvPicPr><p:cNvPr id="6" name="Linked image"/></p:nvPicPr><p:blipFill><a:blip r:link="rIdLinked"/></p:blipFill></p:pic>'
        '</p:spTree></p:cSld></p:sld>'
    ).encode()
    layout_shape = _shape(20, "Layout body", "", geometry=(100_000, 100_000, 450_000, 180_000), placeholder='<p:ph type="body" idx="7"/>')
    content_types = (
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        b'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        b'<Default Extension="xml" ContentType="application/xml"/>'
        b'<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
        b'<Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        b'<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
        b'<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
        b'<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
        b'<Override PartName="/ppt/notesSlides/notesSlide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"/>'
        b'</Types>'
    )
    entries = {
        "[Content_Types].xml": content_types,
        "_rels/.rels": _rels(_relation("rIdOffice", "officeDocument", "ppt/presentation.xml")),
        "ppt/presentation.xml": f'<p:presentation xmlns:p="{P}" xmlns:r="{R}"><p:sldSz cx="10000000" cy="7500000"/><p:sldIdLst><p:sldId id="256" r:id="rIdSlide"/></p:sldIdLst></p:presentation>'.encode(),
        "ppt/_rels/presentation.xml.rels": _rels(_relation("rIdSlide", "slide", "slides/slide1.xml")),
        "ppt/slides/slide1.xml": slide,
        "ppt/slides/_rels/slide1.xml.rels": _rels(
            _relation("rIdLayout", "slideLayout", "../slideLayouts/slideLayout1.xml"),
            _relation("rIdImage", "image", "../media/missing.png"),
            _relation("rIdLinked", "image", "https://invalid.example/image.png", external=True),
        ),
        "ppt/slideLayouts/slideLayout1.xml": f'<p:sldLayout xmlns:p="{P}" xmlns:a="{A}"><p:cSld><p:spTree>{layout_shape}</p:spTree></p:cSld></p:sldLayout>'.encode(),
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": _rels(_relation("rIdMaster", "slideMaster", "../slideMasters/slideMaster1.xml")),
        "ppt/slideMasters/slideMaster1.xml": f'<p:sldMaster xmlns:p="{P}"/>'.encode(),
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": _rels(_relation("rIdTheme", "theme", "../theme/theme1.xml")),
        "ppt/theme/theme1.xml": f'<a:theme xmlns:a="{A}"><a:themeElements><a:fontScheme name="Fixture"><a:majorFont><a:latin typeface="Fixture Latin"/><a:ea typeface=""/></a:majorFont></a:fontScheme></a:themeElements></a:theme>'.encode(),
        "ppt/notesSlides/notesSlide1.xml": f'<p:notes xmlns:p="{P}"/>'.encode(),
        "custom/unknown.bin": b"UNKNOWN-PART-SENTINEL",
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in entries.items():
            info = zipfile.ZipInfo(name, (2024, 1, 2, 3, 4, 6))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    return path


def test_real_pptx_audit_reports_heuristic_clipping_fonts_and_media_truthfully(tmp_path: Path) -> None:
    source = _package(tmp_path / "layout-audit.pptx")
    adapter = PptxAdapter()
    assert len(Presentation(str(source)).slides) == 1
    before = adapter.part_hashes(source)
    audit = adapter.audit_layout(source)
    assert adapter.part_hashes(source) == before
    codes = [warning["code"] for warning in audit["warnings"]]
    assert "PPTX_EXPLICIT_TEXT_CLIPPING" in codes
    assert "PPTX_SHAPE_OUTSIDE_SLIDE" in codes
    assert "PPTX_TEXT_OVERFLOW_RISK" in codes
    assert "PPTX_TABLE_OVERFLOW_RISK" in codes
    assert "PPTX_MISSING_FONT_DECLARATION" in codes
    assert "PPTX_MISSING_MEDIA" in codes
    assert "PPTX_LINKED_MEDIA_UNVERIFIED" in codes
    assert all({"slide", "shape", "locator", "bounds", "reason"} <= warning.keys() for warning in audit["warnings"])
    inherited = next(warning for warning in audit["warnings"] if warning["shape"] == "Inherited placeholder" and warning["code"] == "PPTX_TEXT_OVERFLOW_RISK")
    assert inherited["bounds"] is not None
    assert not any(
        warning["shape"] == "Autofit" and warning["code"] == "PPTX_TEXT_OVERFLOW_RISK"
        for warning in audit["warnings"]
    )
    assert any(item["script"] == "east_asian" for item in audit["fonts"]["missing_declarations"])
    assert audit["fonts"]["availability"] == "unverified"
    assert audit["visual_verification"] == {"state": "not_run", "reason": "renderer_unavailable"}
    assert "not visual proof" in audit["method"]


def test_graph_and_unknown_parts_survive_bounded_placeholder_edit(tmp_path: Path) -> None:
    source = _package(tmp_path / "source.pptx")
    output = tmp_path / "output.pptx"
    adapter = PptxAdapter()
    before = adapter.part_hashes(source)
    _ = adapter.patch_placeholder(source, output, 7, "Short replacement", slide_part="ppt/slides/slide1.xml")
    after = adapter.part_hashes(output)
    assert before.keys() == after.keys()
    assert before["ppt/slides/slide1.xml"] != after["ppt/slides/slide1.xml"]
    for name in before.keys() - {"ppt/slides/slide1.xml"}:
        assert before[name] == after[name]
    audit = adapter.audit_layout(output)
    assert audit["graph"]["broken_relationships"][0]["target"] == "ppt/media/missing.png"
    assert audit["graph"]["masters"] == ["ppt/slideMasters/slideMaster1.xml"]
    assert audit["graph"]["layouts"] == ["ppt/slideLayouts/slideLayout1.xml"]
    assert audit["graph"]["themes"] == ["ppt/theme/theme1.xml"]
    assert audit["graph"]["notes"] == ["ppt/notesSlides/notesSlide1.xml"]
