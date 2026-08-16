from __future__ import annotations
from .errors import DocumentError,DocumentErrorCode
def bind_template(
    fields:list[dict[str, object]],
    bindings:dict[str, object],
    *,
    strict:bool=True,
    raw_token_fallback:bool=False,
) -> list[dict[str, object]]:
    out:list[dict[str, object]]=[]
    for key,value in bindings.items():
        candidates=[f for f in fields if f.get('key')==key and (f.get('kind')!='raw' or raw_token_fallback)]
        native=[f for f in candidates if f.get('kind')!='raw']
        candidates=native or candidates
        if len(candidates)!=1:
            if strict:
                raise DocumentError(DocumentErrorCode.INVALID_INPUT,'plan',f'binding {key!r} is missing or ambiguous')
            continue
        out.append({**candidates[0],'value':value})
    return out
