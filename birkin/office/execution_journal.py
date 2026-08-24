"""Write-ahead authority for recoverable Office draft execution."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from .artifact_serialization import canonical_integrity_json
from .errors import DocumentError, DocumentErrorCode
from .journal_record import journal_root, read_record, write_record

_STAGE = "office_execution_journal"
_VERSION = 1


@dataclass(frozen=True, slots=True)
class ExecutionIntent:
    """Exact mutation identity written before a managed draft can appear."""

    output_name: str
    source_sha256: str
    format_name: str
    operations_sha256: str

    @classmethod
    def create(
        cls,
        *,
        output_name: str,
        source_sha256: str,
        format_name: str,
        operations: Sequence[Mapping[str, object]],
    ) -> ExecutionIntent:
        digest = hashlib.sha256(
            canonical_integrity_json([dict(item) for item in operations]).encode("utf-8")
        ).hexdigest()
        return cls(output_name, source_sha256, format_name, digest)


class ExecutionJournal:
    """One immutable execution intent per deterministic managed draft."""

    def __init__(self, home: Path) -> None:
        self._root = journal_root(home / "artifacts" / "execution-journal", _STAGE)

    def _path(self, intent: ExecutionIntent) -> Path:
        key = hashlib.sha256(intent.output_name.encode("utf-8")).hexdigest()
        return self._root / f"{key}.json"

    def prepare(self, intent: ExecutionIntent) -> bool:
        """Persist intent and report whether an identical attempt already existed."""
        path = self._path(intent)
        existing = read_record(path, _STAGE)
        expected: dict[str, object] = {"version": _VERSION, **asdict(intent)}
        if existing is None:
            write_record(path, expected, _STAGE)
            return False
        if existing != expected:
            raise DocumentError(
                DocumentErrorCode.POLICY_DENIED,
                _STAGE,
                "existing draft intent does not match the approved operation",
            )
        return True
