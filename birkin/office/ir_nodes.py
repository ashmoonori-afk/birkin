from __future__ import annotations
from dataclasses import dataclass
@dataclass(frozen=True)
class DocumentNode:
    id:str
    kind:str
    source_locator:dict[str,object]
    revision:int
