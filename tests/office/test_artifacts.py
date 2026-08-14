import hashlib
import pytest
from birkin.artifacts import ArtifactStore

def test_import_is_content_addressed_deduplicated_and_source_immutable(tmp_path):
    source=tmp_path/'source.bin'; source.write_bytes(b'office-data'); before=hashlib.sha256(source.read_bytes()).hexdigest()
    store=ArtifactStore(tmp_path/'cas'); a=store.import_file(source,sensitivity='confidential',acl_fingerprint='a'*64); b=store.import_file(source,sensitivity='internal',acl_fingerprint='b'*64)
    assert a.content_hash==b.content_hash==before and a.blob_path==b.blob_path
    assert b.sensitivity=='confidential' and b.acl_fingerprint=='a'*64
    assert source.read_bytes()==b'office-data' and hashlib.sha256(source.read_bytes()).hexdigest()==before
    out=tmp_path/'out.bin'; store.copy_out(a,out); assert out.read_bytes()==b'office-data'
    with pytest.raises(FileExistsError): store.copy_out(a,out)
