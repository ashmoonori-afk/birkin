from __future__ import annotations
import hashlib,re,zipfile
from pathlib import Path
from ..errors import DocumentError,DocumentErrorCode
from ..package import clone_package,preflight_package
class DocxAdapter:
    format='docx'
    def part_hashes(self,path:Path)->dict[str,str]: return {k:v['original_sha256'] for k,v in preflight_package(path)['parts'].items()}
    def inspect(self,path:Path)->dict:
        with zipfile.ZipFile(path) as z:
            names=z.namelist(); body=z.read('word/document.xml')
        return {'paragraphs':re.findall(rb'<w:p\b',body),'tables':re.findall(rb'<w:tbl\b',body),'headers':[n for n in names if n.startswith('word/header')],'styles':[n for n in names if n=='word/styles.xml']}
    def patch_field(self,source:Path,output:Path,key:str,value:str)->None:
        with zipfile.ZipFile(source) as z: xml=z.read('word/document.xml')
        pattern=rb'(<w:sdt\b.*?<w:tag\s+w:val=["\']'+re.escape(key.encode())+rb'["\'].*?<w:t[^>]*>)(.*?)(</w:t>)'
        escaped=value.replace('&','&amp;').replace('<','&lt;').encode(); changed,count=re.subn(pattern,lambda m:m.group(1)+escaped+m.group(3),xml,count=1,flags=re.S)
        if count!=1: raise DocumentError(DocumentErrorCode.NODE_NOT_FOUND,'locate','content control not found')
        clone_package(source,output,{'word/document.xml':changed})
