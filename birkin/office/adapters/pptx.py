from __future__ import annotations
import re,zipfile
from pathlib import Path
from ..errors import DocumentError,DocumentErrorCode
from ..package import clone_package,preflight_package
class PptxAdapter:
    format='pptx'
    def inspect(self,path:Path)->dict:
        with zipfile.ZipFile(path) as z: names=z.namelist()
        return {'slides':[n for n in names if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)],'masters':[n for n in names if n.startswith('ppt/slideMasters/')],'layouts':[n for n in names if n.startswith('ppt/slideLayouts/')],'notes':[n for n in names if n.startswith('ppt/notesSlides/')]}
    def part_hashes(self,path:Path)->dict[str,str]: return {k:v['original_sha256'] for k,v in preflight_package(path)['parts'].items()}
    def patch_placeholder(self,source:Path,output:Path,placeholder_idx:int,value:str)->None:
        with zipfile.ZipFile(source) as z: xml=z.read('ppt/slides/slide1.xml')
        pattern=rb'(<p:sp\b.*?<p:ph\s+idx=["\']'+str(placeholder_idx).encode()+rb'["\'].*?<a:t[^>]*>)(.*?)(</a:t>)'; escaped=value.replace('&','&amp;').replace('<','&lt;').encode(); changed,count=re.subn(pattern,lambda m:m.group(1)+escaped+m.group(3),xml,count=1,flags=re.S)
        if count!=1: raise DocumentError(DocumentErrorCode.NODE_NOT_FOUND,'locate','placeholder not found')
        clone_package(source,output,{'ppt/slides/slide1.xml':changed})
