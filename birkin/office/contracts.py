"""Stdlib typed facade for DocumentIR v1."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from .ir_core import Revision
@dataclass(frozen=True)
class DocumentIR:
    document_id:str; revision:Revision; source:dict[str,Any]; package:dict[str,Any]|None; nodes:tuple[dict[str,Any],...]
