from __future__ import annotations
import hashlib,re
from pathlib import Path
from ..errors import DocumentError,DocumentErrorCode
class PdfAdapter:
    format='pdf'
    def extract(self,path:Path)->list[dict]:
        raw=Path(path).read_bytes(); digest=hashlib.sha256(raw).hexdigest(); spans=[]
        for match in re.finditer(rb'BT\s+([0-9.]+)\s+([0-9.]+)\s+Td\s+\((.*?)\)\s+Tj\s+ET',raw,re.S):
            x,y,text=match.groups(); decoded=text.decode('latin-1'); spans.append({'text':decoded,'source_sha256':digest,'page_no':1,'bbox':[float(x),float(y),max(1.0,len(decoded)*6.0),12.0],'object_ref':None,'method':'pdf_text_operator'})
        return spans
    def patch(self,path:Path,operation:dict)->None: raise DocumentError(DocumentErrorCode.UNSUPPORTED_EDIT,'apply','general PDF content rewrite is unsupported')
