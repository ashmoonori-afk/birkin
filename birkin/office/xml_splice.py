from __future__ import annotations
import html,re
from .errors import DocumentError,DocumentErrorCode
from .xml_tokens import text_tokens
def resolve_text_span(xml:bytes,locator:dict)->tuple[int,int]:
    native=locator.get('paragraph_native_id')
    if not native: raise DocumentError(DocumentErrorCode.AMBIGUOUS_LOCATOR,'locate','positional-only locator is forbidden')
    paragraphs=[m for m in re.finditer(rb'<(?:\w+:)?p\b[^>]*\b(?:\w+:)?paraId=["\']'+re.escape(str(native).encode())+rb'["\'][^>]*>.*?</(?:\w+:)?p\s*>',xml,re.S)]
    if not paragraphs: raise DocumentError(DocumentErrorCode.NODE_NOT_FOUND,'locate','paragraph not found')
    if len(paragraphs)>1: raise DocumentError(DocumentErrorCode.AMBIGUOUS_LOCATOR,'locate','paragraph identity is not unique')
    tokens=text_tokens(paragraphs[0].group()); index=int(locator.get('run_index',1))-1
    if index<0 or index>=len(tokens): raise DocumentError(DocumentErrorCode.NODE_NOT_FOUND,'locate','run not found')
    token=tokens[index]; return paragraphs[0].start()+token.start,paragraphs[0].start()+token.end
def splice_text(xml:bytes,locator:dict,value:str)->bytes:
    start,end=resolve_text_span(xml,locator); replacement=html.escape(value,quote=False).encode('utf-8'); return xml[:start]+replacement+xml[end:]
