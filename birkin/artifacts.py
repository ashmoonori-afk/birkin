"""Immutable content-addressed artifact storage."""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    content_hash: str
    media_type: str
    byte_length: int
    blob_path: Path
    sensitivity: str
    acl_fingerprint: str
    lifecycle: str = 'draft'

class ArtifactStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def import_file(self, source: Path, *, media_type: str = 'application/octet-stream', sensitivity: str = 'unknown', acl_fingerprint: str = '') -> Artifact:
        source = Path(source)
        h = hashlib.sha256()
        tmp_dir = self.root / 'tmp'
        tmp_dir.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=tmp_dir)
        os.close(fd)
        tmp = Path(name)
        try:
            with source.open('rb') as inp, tmp.open('wb') as out:
                while chunk := inp.read(1024 * 1024):
                    h.update(chunk)
                    out.write(chunk)
            digest = h.hexdigest()
            blob = self.root / 'sha256' / digest[:2] / digest
            blob.parent.mkdir(parents=True, exist_ok=True)
            if blob.exists():
                tmp.unlink()
            else:
                os.replace(tmp, blob)
                blob.chmod(0o444)
            meta = blob.with_suffix('.json')
            if meta.exists():
                raw = json.loads(meta.read_text(encoding='utf-8'))
                sensitivity = raw['sensitivity']
                acl_fingerprint = raw['acl_fingerprint']
            else:
                meta.write_text(json.dumps({'sensitivity': sensitivity, 'acl_fingerprint': acl_fingerprint}), encoding='utf-8')
            return Artifact(digest, digest, media_type, blob.stat().st_size, blob, sensitivity, acl_fingerprint)
        finally:
            if tmp.exists():
                tmp.unlink()

    def open(self, artifact: Artifact):
        return artifact.blob_path.open('rb')

    def copy_out(self, artifact: Artifact, destination: Path) -> None:
        destination = Path(destination)
        with destination.open('xb') as out, artifact.blob_path.open('rb') as inp:
            shutil.copyfileobj(inp, out)
