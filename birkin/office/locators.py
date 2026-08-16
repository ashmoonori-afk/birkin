from __future__ import annotations
import hashlib
import uuid
def stable_node_id(source_sha256:str,native_identity:str)->str: return str(uuid.uuid5(uuid.NAMESPACE_URL,f'{source_sha256}:{native_identity}'))
def fingerprint(data:bytes)->str: return hashlib.sha256(data).hexdigest()
