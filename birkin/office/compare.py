from __future__ import annotations
import hashlib
from pathlib import Path
def compare_bytes(left:Path,right:Path)->dict: return {'equal':Path(left).read_bytes()==Path(right).read_bytes(),'left_sha256':hashlib.sha256(Path(left).read_bytes()).hexdigest(),'right_sha256':hashlib.sha256(Path(right).read_bytes()).hexdigest()}
