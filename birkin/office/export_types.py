"""Public request and receipt values for durable Office exports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

JSONValue: TypeAlias = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]


@dataclass(frozen=True, slots=True)
class ExportRequest:
    """Caller-owned export destination and its separate approvals."""

    destination: Path
    actor: str
    proposal_digest: str
    operations: tuple[Mapping[str, JSONValue], ...]
    overwrite_approved: bool = False
    authority_digest: str | None = None
    authority_source_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class ExportReceipt:
    """Audit receipt plus private state required for exact rollback."""

    rollback_token: str
    authority_digest: str
    authority_source_sha256: str
    authority_bound: bool
    destination: Path
    source_sha256: str
    output_sha256: str
    operations: tuple[dict[str, JSONValue], ...]
    actor: str
    proposal_digest: str
    overwrite_approved: bool
    destination_existed: bool
    destination_sha256: str | None
    backup: Path | None

    def public(self) -> dict[str, JSONValue]:
        return {
            "path": str(self.destination),
            "authority_digest": self.authority_digest,
            "authority_source_sha256": self.authority_source_sha256,
            "source_sha256": self.source_sha256,
            "output_sha256": self.output_sha256,
            "operations": [dict(operation) for operation in self.operations],
            "actor": self.actor, "proposal_digest": self.proposal_digest,
            "overwrite_approved": self.overwrite_approved,
            "destination_existed": self.destination_existed,
            "destination_sha256": self.destination_sha256,
            "rollback_token": self.rollback_token,
        }


@dataclass(frozen=True, slots=True)
class RollbackReceipt:
    destination: Path
    restored: bool
    destination_sha256: str | None
    actor: str
    proposal_digest: str

    def public(self) -> dict[str, JSONValue]:
        return {
            "path": str(self.destination), "restored": self.restored,
            "destination_sha256": self.destination_sha256,
            "actor": self.actor, "proposal_digest": self.proposal_digest,
        }
