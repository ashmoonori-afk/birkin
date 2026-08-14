from __future__ import annotations
import re,zipfile
from pathlib import Path
from ..errors import DocumentError,DocumentErrorCode
from ..package import clone_package,preflight_package
class XlsxAdapter:
    format='xlsx'
    def part_hashes(self,path:Path)->dict[str,str]: return {k:v['original_sha256'] for k,v in preflight_package(path)['parts'].items()}
    def patch_cell(self,source:Path,output:Path,cell:str,value:object)->dict:
        with zipfile.ZipFile(source) as z: xml=z.read('xl/worksheets/sheet1.xml')
        pattern=rb'(<c\b[^>]*\br=["\']'+re.escape(cell.encode())+rb'["\'][^>]*>.*?<v>)(.*?)(</v>)'; raw=str(value).encode(); changed,count=re.subn(pattern,lambda m:m.group(1)+raw+m.group(3),xml,count=1,flags=re.S)
        if count!=1: raise DocumentError(DocumentErrorCode.NODE_NOT_FOUND,'locate','cell not found')
        clone_package(source,output,{'xl/worksheets/sheet1.xml':changed}); return {'calculated':False,'cell':cell}
