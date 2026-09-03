"""web_session.json carries a capability token, so it must be owner-only."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from birkin.web import server as web_server
from tests.test_native_private_storage import assert_owner_only

_PAYLOAD = {"port": 8787, "token": "capability", "bootstrap_nonce": "nonce"}


def test_discovery_write_is_readable_only_by_the_owner(tmp_path: Path) -> None:
    path = tmp_path / "home" / "web_session.json"

    web_server._write_session_discovery(path, _PAYLOAD)

    assert json.loads(path.read_text(encoding="utf-8")) == _PAYLOAD
    assert_owner_only(path, posix_mode=0o600)


@pytest.mark.skipif(os.name != "nt", reason="Windows DACL widening")
def test_discovery_write_tightens_a_world_readable_predecessor(
    tmp_path: Path,
) -> None:
    # A file left behind by the chmod-only writer: on Windows the grant stuck.
    home = tmp_path / "home"
    home.mkdir()
    path = home / "web_session.json"
    _ = path.write_text("{}", encoding="utf-8")
    system = Path(os.environ["SystemRoot"]) / "System32"
    _ = subprocess.run(
        [str(system / "icacls.exe"), str(path), "/grant", "*S-1-1-0:(F)"],
        check=True,
        capture_output=True,
    )

    web_server._write_session_discovery(path, _PAYLOAD)

    assert_owner_only(path, posix_mode=0o600)
