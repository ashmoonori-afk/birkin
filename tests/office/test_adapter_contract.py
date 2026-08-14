import importlib
from birkin.office.adapters.base import CapabilityState,default_capabilities

def test_adapter_capabilities_are_exhaustive_and_missing_extras_do_not_import_crash(monkeypatch):
    caps=default_capabilities(read_only=True)
    assert set(caps)=={'inspect','extract','compare','fill','patch','render','validate'}
    assert all(c.state in {CapabilityState.AVAILABLE,CapabilityState.UNAVAILABLE,CapabilityState.READ_ONLY} and c.reason for c in caps.values())
    assert importlib.import_module('birkin')
