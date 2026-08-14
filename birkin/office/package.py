"""Safe inventory and verbatim package emission."""
from __future__ import annotations
import hashlib, os, tempfile, zipfile
from pathlib import Path,PurePosixPath
from typing import Mapping
from .errors import DocumentError,DocumentErrorCode
from .limits import DEFAULT_LIMITS,PackageLimits
def _invalid(message:str)->DocumentError: return DocumentError(DocumentErrorCode.PACKAGE_INVALID,'import',message)
def preflight_package(path:Path,limits:PackageLimits=DEFAULT_LIMITS)->dict:
    try:
        with zipfile.ZipFile(path) as z:
            infos=z.infolist(); total=0; seen=set(); parts={}
            if len(infos)>limits.max_entries: raise _invalid('too many package entries')
            for i,info in enumerate(infos):
                name=info.filename.replace(chr(92),'/'); pure=PurePosixPath(name)
                if name.startswith('/') or '..' in pure.parts or name in seen: raise _invalid('unsafe or duplicate package path')
                seen.add(name); total+=info.file_size
                if total>limits.max_uncompressed_bytes: raise _invalid('inflated package exceeds limit')
                data=z.read(info)
                if name.lower().endswith(('.xml','.rels')) and (b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper()): raise _invalid('DTD and entities are forbidden')
                parts[name]={'index':i,'original_sha256':hashlib.sha256(data).hexdigest(),'bytes':data,'compress_type':info.compress_type,'date_time':info.date_time,'external_attr':info.external_attr}
            return {'parts':parts,'source_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()}
    except DocumentError: raise
    except (OSError,zipfile.BadZipFile,RuntimeError) as exc: raise _invalid(str(exc)) from exc
def clone_package(source:Path,output:Path,replacements:Mapping[str,bytes])->dict:
    source=Path(source); output=Path(output)
    if output.exists(): raise DocumentError(DocumentErrorCode.OUTPUT_EXISTS,'emit','output exists')
    manifest=preflight_package(source); missing=set(replacements)-set(manifest['parts'])
    if missing: raise DocumentError(DocumentErrorCode.NODE_NOT_FOUND,'locate',f'parts not found: {sorted(missing)}')
    output.parent.mkdir(parents=True,exist_ok=True); fd,name=tempfile.mkstemp(dir=output.parent,suffix='.zip'); os.close(fd); tmp=Path(name)
    try:
        with zipfile.ZipFile(tmp,'w') as out:
            for part,meta in sorted(manifest['parts'].items(),key=lambda x:x[1]['index']):
                info=zipfile.ZipInfo(part,meta['date_time']); info.compress_type=meta['compress_type']; info.external_attr=meta['external_attr']; out.writestr(info,replacements.get(part,meta['bytes']))
        preflight_package(tmp); os.replace(tmp,output); return manifest
    except Exception:
        if tmp.exists(): tmp.unlink()
        raise
