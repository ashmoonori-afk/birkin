"""Document service facade over immutable artifacts and format adapters."""
from __future__ import annotations
import hashlib,mimetypes,tempfile
from pathlib import Path
from typing import Any
from .adapters.base import default_capabilities
from .adapters.docx import DocxAdapter
from .adapters.xlsx import XlsxAdapter
from .adapters.pptx import PptxAdapter
from .adapters.pdf import PdfAdapter
from .adapters.hwpx import HwpxAdapter
from .compare import compare_bytes
from .errors import DocumentError,DocumentErrorCode
from .templates import bind_template
class DocumentService:
    def __init__(self,home:Path): self.home=Path(home); (self.home/'artifacts/drafts').mkdir(parents=True,exist_ok=True)
    def _path(self,ref:dict)->Path:
        path=Path(ref['uri']); digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest!=ref.get('content_hash'): raise DocumentError(DocumentErrorCode.SOURCE_CHANGED,'import','artifact hash mismatch',artifact_sha256=digest)
        return path
    @staticmethod
    def _format(path:Path)->str: return path.suffix.lower().lstrip('.')
    def _adapter(self,fmt:str):
        adapters={'docx':DocxAdapter,'xlsx':XlsxAdapter,'pptx':PptxAdapter,'pdf':PdfAdapter,'hwpx':HwpxAdapter}
        if fmt not in adapters: raise DocumentError(DocumentErrorCode.UNSUPPORTED_FORMAT,'probe',f'unsupported format: {fmt}')
        return adapters[fmt]()
    def inspect_document(self,source:dict,**kwargs)->dict:
        path=self._path(source); fmt=self._format(path); adapter=self._adapter(fmt); summary=adapter.inspect(path) if fmt!='pdf' else {'spans':len(adapter.extract(path))}
        return {'document_ir_artifact':None,'summary':summary,'format':fmt,'capabilities':{k:{'state':v.state.value,'reason':v.reason,'install_hint':v.install_hint} for k,v in default_capabilities(read_only=fmt=='pdf').items()},'warnings':[]}
    def extract_document(self,source:dict,**kwargs)->dict:
        path=self._path(source); fmt=self._format(path)
        if fmt=='pdf': spans=self._adapter(fmt).extract(path)
        else: spans=[]
        return {'spans':spans,'nodes':[],'projection':kwargs.get('projection','text'),'truncation':False}
    def compare_documents(self,left:dict,right:dict,**kwargs)->dict: return compare_bytes(self._path(left),self._path(right))
    def fill_template(self,template:dict,bindings:list,**kwargs)->dict:
        fields=kwargs.pop('fields',[]); values={b['key']:b['value'] for b in bindings}; return {'operations':bind_template(fields,values,strict=kwargs.get('strict',True),raw_token_fallback=kwargs.get('raw_token_fallback',False)),'dry_run':True}
    def apply_document_patch(self,base:dict,patch:dict,*,expected_source_sha256:str,output_name:str,dry_run:bool=True)->dict:
        source=self._path(base)
        if expected_source_sha256!=base['content_hash']: raise DocumentError(DocumentErrorCode.SOURCE_CHANGED,'apply','expected source hash mismatch')
        if Path(output_name).name!=output_name: raise DocumentError(DocumentErrorCode.INVALID_INPUT,'emit','output_name must be a logical name')
        output=self.home/'artifacts/drafts'/output_name
        if dry_run: return {'status':'planned','draft_artifact':None,'ir_artifact':None,'edit_log':patch.get('operations',[]),'semantic_diff':{},'package_diff':{},'source_sha256':expected_source_sha256}
        adapter=self._adapter(self._format(source)); operations=patch.get('operations',[])
        if len(operations)!=1: raise DocumentError(DocumentErrorCode.INVALID_INPUT,'plan','one narrow Wave 1 operation is required')
        op=operations[0]
        if hasattr(adapter,'patch_field'): adapter.patch_field(source,output,op['field'],op['value'])
        elif hasattr(adapter,'patch_cell'): adapter.patch_cell(source,output,op['cell'],op['value'])
        elif hasattr(adapter,'patch_placeholder'): adapter.patch_placeholder(source,output,op['placeholder_idx'],op['value'])
        else: raise DocumentError(DocumentErrorCode.UNSUPPORTED_EDIT,'apply','format is read only')
        digest=hashlib.sha256(output.read_bytes()).hexdigest(); ref={'artifact_id':digest,'content_hash':digest,'media_type':mimetypes.guess_type(output.name)[0] or 'application/octet-stream','uri':str(output),'sensitivity':base.get('sensitivity','unknown'),'acl_fingerprint':base.get('acl_fingerprint','')}
        return {'status':'draft','draft_artifact':ref,'ir_artifact':None,'edit_log':operations,'semantic_diff':{},'package_diff':{},'source_sha256':expected_source_sha256}
    def unavailable(self,stage:str)->dict: return DocumentError(DocumentErrorCode.CAPABILITY_UNAVAILABLE,stage,'Wave 2 renderer and validators are not available').envelope()
