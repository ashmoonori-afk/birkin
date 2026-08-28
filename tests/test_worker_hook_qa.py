from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

import pytest

from birkin import worker_hook_qa

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX shared temporary root contract",
)


def test_run_uses_owner_home_instead_of_shared_temp_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shared_root = tmp_path / "shared"
    shared_root.mkdir(mode=0o777)
    shared_root.chmod(0o777)
    owner_home = tmp_path / "owner-home"
    owner_home.mkdir(mode=0o700)
    monkeypatch.setattr(tempfile, "tempdir", str(shared_root))
    monkeypatch.setattr(worker_hook_qa, "_owner_home", lambda: owner_home)

    result = worker_hook_qa.run("approve")

    assert result == 0
    assert json.loads(capsys.readouterr().out)["cleaned"] is True
    assert tuple(shared_root.iterdir()) == ()
