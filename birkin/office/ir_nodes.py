from __future__ import annotations
from dataclasses import dataclass
from typing import Any
@dataclass(frozen=True)
class DocumentNode:
    id:str; kind:str; source_locator:dict[str,Any]; revision:int
