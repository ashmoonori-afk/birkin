from __future__ import annotations
from dataclasses import dataclass
@dataclass(frozen=True)
class PackagePart:
    part_uri:str
    original_sha256:str
    current_sha256:str
    preservation:str
