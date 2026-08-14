from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any,Protocol
class CapabilityState(str,Enum): AVAILABLE='available'; UNAVAILABLE='unavailable'; READ_ONLY='read_only'
@dataclass(frozen=True)
class Capability:
    state:CapabilityState; reason:str; install_hint:str|None=None
CAPABILITY_NAMES=('inspect','extract','compare','fill','patch','render','validate')
def default_capabilities(*,read_only:bool=False)->dict[str,Capability]:
    result={name:Capability(CapabilityState.AVAILABLE,'native package support') for name in CAPABILITY_NAMES}
    if read_only:
        for name in ('fill','patch'): result[name]=Capability(CapabilityState.READ_ONLY,'format is immutable')
    for name in ('render','validate'): result[name]=Capability(CapabilityState.UNAVAILABLE,'renderer is not configured','configure the Wave 2 renderer')
    return result
class DocumentAdapter(Protocol):
    format:str
    def capabilities(self)->dict[str,Capability]: ...
    def inspect(self,path:Any)->dict[str,Any]: ...
