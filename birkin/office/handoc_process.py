from __future__ import annotations
import hashlib,json,subprocess
from pathlib import Path
from typing import Callable
from .adapters.base import Capability,CapabilityState
REQUIRED_NODE_VERSION='22.14.0'; REQUIRED_PACKAGES={'@handoc/hwpx-parser':'0.1.0','@handoc/hwpx-writer':'0.1.0','@handoc/pdf-export':'0.1.0'}
HINT='Install Node.js 22.14.0 x64 and @handoc/hwpx-parser@0.1.0, @handoc/hwpx-writer@0.1.0, @handoc/pdf-export@0.1.0.'
class HanDocProcess:
    def __init__(self,config:dict,*,runner:Callable=subprocess.run): self.config=config; self.runner=runner
    def capability(self)->Capability:
        c=self.config
        if not c.get('node_path') or c.get('node_version')!=REQUIRED_NODE_VERSION or not c.get('module_root'): return Capability(CapabilityState.UNAVAILABLE,'HanDoc runtime is not configured',HINT)
        manifest=Path(c['module_root'])/'package.json'
        if not manifest.is_file() or hashlib.sha256(manifest.read_bytes()).hexdigest()!=c.get('package_manifest_sha256'): return Capability(CapabilityState.UNAVAILABLE,'HanDoc package manifest hash mismatch',HINT)
        try: deps=json.loads(manifest.read_text(encoding='utf-8')).get('dependencies',{})
        except (OSError,json.JSONDecodeError): return Capability(CapabilityState.UNAVAILABLE,'HanDoc package manifest is invalid',HINT)
        if any(deps.get(k)!=v for k,v in REQUIRED_PACKAGES.items()): return Capability(CapabilityState.UNAVAILABLE,'HanDoc package version mismatch',HINT)
        try: result=self.runner([c['node_path'],'--version'],capture_output=True,text=True,timeout=c.get('timeout_seconds',30),check=False)
        except (OSError,subprocess.TimeoutExpired): return Capability(CapabilityState.UNAVAILABLE,'Node executable unavailable',HINT)
        if result.returncode or result.stdout.strip()!=f'v{REQUIRED_NODE_VERSION}': return Capability(CapabilityState.UNAVAILABLE,'Node version mismatch',HINT)
        return Capability(CapabilityState.AVAILABLE,'exact HanDoc runtime is available')
