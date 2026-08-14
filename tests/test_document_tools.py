import hashlib,json
from pathlib import Path
from birkin.tools import build_registry
from birkin.tools._types import ToolContext
NAMES={'inspect_document','extract_document','compare_documents','fill_template','apply_document_patch','render_artifact','validate_artifact'}
def _ctx(tmp_path,cfg=None): return ToolContext(cfg=cfg or {},client=None,cwd=tmp_path)
def test_registry_exposes_exactly_seven_document_tools_and_honors_disabled_group(tmp_path):
    reg=build_registry(_ctx(tmp_path),include={'documents'}); assert set(reg.names())==NAMES
    blocked=build_registry(_ctx(tmp_path,{'disabled_tools':['documents']}),include={'documents'}); assert blocked.names()==[]
    result=blocked.execute('inspect_document',{}); assert result.is_error or 'approval' in str(result.content).lower()
def test_apply_tool_emits_only_a_managed_draft_and_preserves_source(tmp_path,monkeypatch):
    monkeypatch.setenv('BIRKIN_HOME',str(tmp_path/'home')); src=Path(__file__).parent/'office/fixtures/docx/template-fields.docx'; digest=hashlib.sha256(src.read_bytes()).hexdigest(); before=src.read_bytes()
    reg=build_registry(_ctx(tmp_path),include={'documents'}); payload={'base':{'artifact_id':digest,'content_hash':digest,'media_type':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','uri':str(src),'sensitivity':'internal','acl_fingerprint':'a'*64},'patch':{'operations':[{'field':'customer','value':'Ada'}]},'expected_source_sha256':digest,'output_name':'draft.docx','dry_run':False}
    result=reg.execute('apply_document_patch',payload); body=json.loads(result.content); assert not result.is_error and body['draft_artifact'] and Path(body['draft_artifact']['uri']).is_file() and src.read_bytes()==before
    unavailable=json.loads(reg.execute('render_artifact',{'artifact':payload['base']}).content); assert unavailable['error']['code']=='CAPABILITY_UNAVAILABLE'
