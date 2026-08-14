from __future__ import annotations
import re,zipfile
from pathlib import Path
from ..errors import DocumentError,DocumentErrorCode
from ..package import clone_package,preflight_package
class HwpxAdapter:
    format='hwpx'
    def part_hashes(self,path:Path)->dict[str,str]: return {k:v['original_sha256'] for k,v in preflight_package(path)['parts'].items()}
    def inspect(self,path:Path)->dict:
        with zipfile.ZipFile(path) as z:
            sections=[n for n in z.namelist() if re.fullmatch(r'Contents/section\d+\.xml',n)]; xml=b''.join(z.read(n) for n in sections)
        return {'sections':sections,'paragraphs':re.findall(rb'<hp:p\b',xml),'fields':re.findall(rb'<hp:field\b',xml),'tables':re.findall(rb'<hp:tbl\b',xml),'fonts':re.findall(rb'<hp:fontRef\b',xml)}
    def patch_field(self,source:Path,output:Path,key:str,value:str)->None:
        part='Contents/section0.xml'
        with zipfile.ZipFile(source) as z: xml=z.read(part)
        pattern=rb'(<hp:field\b[^>]*\bid=["\']'+re.escape(key.encode())+rb'["\'][^>]*>.*?<hp:t[^>]*>)(.*?)(</hp:t>)'; escaped=value.replace('&','&amp;').replace('<','&lt;').encode(); changed,count=re.subn(pattern,lambda m:m.group(1)+escaped+m.group(3),xml,count=1,flags=re.S)
        if count!=1: raise DocumentError(DocumentErrorCode.NODE_NOT_FOUND,'locate','HWPX field not found')
        clone_package(source,output,{part:changed})
