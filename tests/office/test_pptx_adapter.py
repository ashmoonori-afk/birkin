import zipfile
from pathlib import Path
from birkin.office.adapters.pptx import PptxAdapter
FIX=Path(__file__).parent/'fixtures/pptx/branded-placeholder.pptx'
def test_pptx_run_patch_keeps_slide_master_placeholder_notes_and_unknown_parts(tmp_path):
    a=PptxAdapter(); before=a.part_hashes(FIX); out=tmp_path/'draft.pptx'; a.patch_placeholder(FIX,out,7,'New title'); after=a.part_hashes(out)
    for part in ('ppt/slideMasters/slideMaster1.xml','ppt/slideLayouts/slideLayout1.xml','ppt/notesSlides/notesSlide1.xml','ppt/theme/theme1.xml','ppt/media/logo.bin','custom/opaque.xml'): assert before[part]==after[part]
    with zipfile.ZipFile(out) as z: assert b'New title' in z.read('ppt/slides/slide1.xml') and b'PLACEHOLDER' not in z.read('ppt/slides/slide1.xml')
