"""Stdlib typed facade for DocumentIR v1."""
from __future__ import annotations
from dataclasses import dataclass
from .ir_core import Revision
@dataclass(frozen=True)
class DocumentIR:
    document_id:str
    revision:Revision
    source:dict[str,object]
    package:dict[str,object]|None
    nodes:tuple[dict[str,object],...]
