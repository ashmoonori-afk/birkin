"""Import job manager — tracks background conversation import jobs."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class ImportStatus(str, Enum):
    PENDING = "pending"
    PARSING = "parsing"
    ANALYZING = "analyzing"
    MERGING = "merging"
    COMPILING = "compiling"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class ImportJob:
    """State of a single import job."""

    id: str
    status: ImportStatus = ImportStatus.PENDING
    conversations_found: int = 0
    progress_current: int = 0
    progress_total: int = 0
    progress_phase: str = ""
    pages_created: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    source_format: str = ""  # "chatgpt" or "claude"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status.value,
            "conversations_found": self.conversations_found,
            "progress_current": self.progress_current,
            "progress_total": self.progress_total,
            "progress_phase": self.progress_phase,
            "pages_created": self.pages_created,
            "errors": self.errors,
            "source_format": self.source_format,
        }


class ImportJobManager:
    """Manages background import jobs. In-memory tracking (single-user agent)."""

    def __init__(self) -> None:
        self._jobs: dict[str, ImportJob] = {}
        self._active_job_id: Optional[str] = None

    def create_job(self) -> ImportJob:
        """Create a new import job. Only one active job allowed."""
        if self._active_job_id and self._active_job_id in self._jobs:
            active = self._jobs[self._active_job_id]
            if active.status not in (ImportStatus.DONE, ImportStatus.ERROR, ImportStatus.CANCELLED):
                raise ValueError("An import is already in progress")

        job_id = str(uuid.uuid4())[:12]
        job = ImportJob(id=job_id)
        self._jobs[job_id] = job
        self._active_job_id = job_id
        return job

    def get_job(self, job_id: str) -> Optional[ImportJob]:
        return self._jobs.get(job_id)

    def update_progress(self, job_id: str, phase: str, current: int, total: int) -> None:
        job = self._jobs.get(job_id)
        if job:
            job.progress_phase = phase
            job.progress_current = current
            job.progress_total = total
            job.status = ImportStatus(phase) if phase in ImportStatus.__members__.values() else job.status

    @property
    def has_active_job(self) -> bool:
        if not self._active_job_id:
            return False
        job = self._jobs.get(self._active_job_id)
        if not job:
            return False
        return job.status not in (ImportStatus.DONE, ImportStatus.ERROR, ImportStatus.CANCELLED)
