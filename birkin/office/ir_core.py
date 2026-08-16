from __future__ import annotations
from dataclasses import dataclass
@dataclass(frozen=True)
class Revision:
    number:int
    parent_ir_sha256:str|None
    ir_sha256:str
    created_at:str
    created_by:str
