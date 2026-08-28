from __future__ import annotations

import os
from pathlib import Path

import pytest

from birkin.office.errors import DocumentError
from birkin.office.journal_record import read_record


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink semantics")
def test_shared_journal_reader_refuses_symlinked_record(
    tmp_path: Path,
) -> None:
    victim = tmp_path / "victim.json"
    _ = victim.write_text('{"trusted":false}', encoding="utf-8")
    linked = tmp_path / "record.json"
    linked.symlink_to(victim)

    with pytest.raises(DocumentError, match="unavailable"):
        _ = read_record(linked, "test_journal")

    assert victim.read_text(encoding="utf-8") == '{"trusted":false}'
