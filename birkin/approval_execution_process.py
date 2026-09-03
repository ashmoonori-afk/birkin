"""Launch one-shot approval helpers without exposing shell evaluation."""

from __future__ import annotations

import secrets
import subprocess
import sys

from . import procreg
from .approval_execution_helper import helper_argv
from .approval_execution_journal import ExecutionJournal, JournalCorruptionError
from .proc import popen_detached


def launch_helper(
    journal: ExecutionJournal,
    *,
    capture_stdout: bool = False,
) -> subprocess.Popen[bytes]:
    """Start one helper and durably bind its process identity."""
    owner_token = secrets.token_hex(32)
    command = helper_argv(
        journal.approval_id,
        owner_token,
        executable=sys.executable,
        frozen=bool(getattr(sys, "frozen", False)),
    )
    stdout = subprocess.PIPE if capture_stdout else subprocess.DEVNULL
    process = popen_detached(
        command,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    try:
        journal.helper_started(
            owner_pid=process.pid,
            owner_token=owner_token,
            owner_generation=procreg.process_generation(process.pid),
        )
    except (OSError, JournalCorruptionError):
        process.kill()
        _ = process.wait()
        raise
    return process
