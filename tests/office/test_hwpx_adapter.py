import hashlib,subprocess,zipfile
from pathlib import Path
from birkin.office.adapters.base import CapabilityState
from birkin.office.adapters.hwpx import HwpxAdapter
from birkin.office.handoc_process import HanDocProcess,REQUIRED_NODE_VERSION,REQUIRED_PACKAGES
FIX=Path(__file__).parent/'fixtures/hwpx/form-table.hwpx'
def test_hwpx_inventory_and_narrow_field_patch_preserve_unknown_xml(tmp_path):
    a=HwpxAdapter(); info=a.inspect(FIX); assert {'sections','paragraphs','fields','tables','fonts'}<=info.keys()
    before=a.part_hashes(FIX); out=tmp_path/'draft.hwpx'; a.patch_field(FIX,out,'customer','Ada'); after=a.part_hashes(out)
    assert before['Contents/opaque.xml']==after['Contents/opaque.xml']
    with zipfile.ZipFile(out) as z: assert b'Ada' in z.read('Contents/section0.xml')
def test_missing_node_or_handoc_is_clean_capability_result():
    cap=HanDocProcess({}).capability(); assert cap.state is CapabilityState.UNAVAILABLE and 'Node.js 22.14.0 x64' in cap.install_hint and '@handoc/hwpx-parser@0.1.0' in cap.install_hint
def test_handoc_process_requires_exact_node_and_package_manifest(tmp_path):
    calls=[]
    def run(argv,**kwargs): calls.append((argv,kwargs)); return subprocess.CompletedProcess(argv,0,stdout='v22.14.0\n',stderr='')
    manifest=tmp_path/'package.json'; manifest.write_text('{"dependencies":{"@handoc/hwpx-parser":"0.1.0","@handoc/hwpx-writer":"0.1.0","@handoc/pdf-export":"0.1.0"}}')
    digest=hashlib.sha256(manifest.read_bytes()).hexdigest(); cfg={'node_path':'node','node_version':REQUIRED_NODE_VERSION,'module_root':str(tmp_path),'package_manifest_sha256':digest,'timeout_seconds':5}
    assert HanDocProcess(cfg,runner=run).capability().state is CapabilityState.AVAILABLE and calls[0][1]['timeout']==5
    assert HanDocProcess({**cfg,'node_version':'22.13.0'},runner=run).capability().state is CapabilityState.UNAVAILABLE
