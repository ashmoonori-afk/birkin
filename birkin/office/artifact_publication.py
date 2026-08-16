"""Durable, no-overwrite publication for managed Office artifacts."""

from __future__ import annotations

import errno
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from .errors import DocumentError, DocumentErrorCode
from .path_security import (
    canonical_name,
    close_guard,
    descriptor_identity,
    ensure_directory_identity,
    hash_descriptor,
    open_directory_guard,
    open_identity_guard,
    open_regular_guard,
)
from .publication_platform import (
    acquire_publication_lock,
    collision,
    ensure_temporary_identity,
    link_temporary,
    published_matches,
    release_publication_lock,
    sync_cleanup,
    sync_publication,
    temporary_path_matches,
    unlink,
)

IdentityVerifier = Callable[[int, Path], str]
Writer = Callable[[Path], None]
Validator = Callable[[Path], None]


def _exists(name: str) -> DocumentError:
    return DocumentError(
        DocumentErrorCode.OUTPUT_EXISTS,
        "emit",
        "output exists or canonically collides",
        details={
            "publication": "refused",
            "reason": "destination_exists",
            "destination_name": name,
        },
    )


def _filesystem_error(exc: OSError, action: str) -> DocumentError:
    if exc.errno in {errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)}:
        return DocumentError(
            DocumentErrorCode.STORAGE_EXHAUSTED,
            "emit",
            "artifact storage is exhausted",
            retryable=True,
            details={"publication": "refused", "reason": "storage_exhausted"},
        )
    if exc.errno in {errno.EACCES, errno.EPERM, getattr(errno, "EBUSY", errno.EACCES)}:
        return DocumentError(
            DocumentErrorCode.PERMISSION_DENIED,
            "emit",
            f"{action} was denied",
            details={"publication": "refused", "reason": "filesystem_permission"},
        )
    return DocumentError(
        DocumentErrorCode.INTERNAL_ERROR,
        "emit",
        f"{action} failed",
        details={"publication": "refused", "reason": "filesystem_error"},
    )


def publish_once(
    drafts: Path,
    draft_identity: tuple[int, int],
    output: Path,
    writer: Writer,
    validator: Validator | None,
    verify_identity: IdentityVerifier,
) -> str:
    """Publish one file while a native lock and stable handles close races."""
    directory_handle = -1
    lock_handle = -1
    lock_acquired = False
    descriptor = -1
    temporary_guard = -1
    published_guard = -1
    temporary_name: str | None = None
    published = False
    failure: BaseException | None = None
    failure_cause: BaseException | None = None
    temporary_identity: tuple[int, int] | None = None
    digest = ""
    try:
        ensure_directory_identity(drafts, draft_identity)
        directory_handle = open_directory_guard(drafts, draft_identity)
        lock_handle = acquire_publication_lock(directory_handle, draft_identity)
        lock_acquired = True
        ensure_directory_identity(drafts, draft_identity)
        if collision(directory_handle, drafts, canonical_name(output.name)):
            raise _exists(output.name)
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=".birkin-", suffix=output.suffix, dir=drafts
        )
        temporary_identity = descriptor_identity(descriptor)
        temporary = Path(temporary_path)
        temporary_name = temporary.name
        if os.name == "nt":
            temporary_guard = open_regular_guard(temporary, descriptor)
        writer(temporary)
        ensure_temporary_identity(descriptor, temporary_name, directory_handle, drafts)
        _ = verify_identity(descriptor, output)
        if validator is not None:
            validator(temporary)
        ensure_temporary_identity(descriptor, temporary_name, directory_handle, drafts)
        digest = hash_descriptor(descriptor)
        _ = verify_identity(descriptor, output)
        os.fsync(descriptor)
        ensure_directory_identity(drafts, draft_identity)
        try:
            link_temporary(temporary_name, output.name, directory_handle, drafts)
        except FileExistsError as exc:
            raise _exists(output.name) from exc
        published = True
        ensure_directory_identity(drafts, draft_identity)
        sync_publication(directory_handle, descriptor)
    except DocumentError as exc:
        failure = exc
    except OSError as exc:
        failure = _filesystem_error(exc, "durable publication")
        failure_cause = exc
    except BaseException as exc:  # noqa: BLE001 - cleanup must run for cancellation/crash signals
        failure = exc

    cleanup_error: OSError | None = None
    if temporary_guard >= 0:
        try:
            close_guard(temporary_guard)
        except OSError as exc:
            cleanup_error = exc
    if descriptor >= 0:
        try:
            os.close(descriptor)
        except OSError as exc:
            cleanup_error = cleanup_error or exc
    if temporary_name is not None and directory_handle >= 0:
        try:
            if os.name == "nt" and not temporary_path_matches(
                drafts / temporary_name,
                temporary_identity,
            ):
                raise OSError(errno.ESTALE, "temporary file identity changed")
            unlink(temporary_name, directory_handle, drafts)
            if failure is None:
                sync_cleanup(directory_handle)
        except FileNotFoundError:
            visible = drafts / temporary_name
            try:
                if temporary_path_matches(visible, temporary_identity):
                    visible.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                cleanup_error = cleanup_error or exc
        except OSError as exc:
            cleanup_error = cleanup_error or exc
    if failure is None and cleanup_error is None and published and directory_handle >= 0:
        try:
            ensure_directory_identity(drafts, draft_identity)
            if os.name == "nt":
                if temporary_identity is None:
                    raise OSError(errno.ESTALE, "published identity is unavailable")
                published_guard = open_identity_guard(output, temporary_identity)
            if not published_matches(
                directory_handle,
                drafts,
                output.name,
                temporary_identity,
            ):
                raise DocumentError(
                    DocumentErrorCode.PERMISSION_DENIED,
                    "emit",
                    "published destination identity changed",
                )
        except (DocumentError, OSError) as exc:
            failure = exc
    if (failure is not None or cleanup_error is not None) and published and directory_handle >= 0:
        try:
            if published_matches(
                directory_handle,
                drafts,
                output.name,
                temporary_identity,
            ):
                if published_guard >= 0:
                    close_guard(published_guard)
                    published_guard = -1
                unlink(output.name, directory_handle, drafts)
                sync_cleanup(directory_handle)
            else:
                cleanup_error = cleanup_error or OSError(
                    errno.ESTALE, "published destination identity changed"
                )
        except FileNotFoundError:
            pass
        except OSError as exc:
            cleanup_error = cleanup_error or exc
    if published_guard >= 0:
        try:
            close_guard(published_guard)
        except OSError as exc:
            cleanup_error = cleanup_error or exc
    if lock_acquired and directory_handle >= 0:
        try:
            release_publication_lock(directory_handle, lock_handle)
        except OSError as exc:
            cleanup_error = cleanup_error or exc
    if directory_handle >= 0:
        try:
            close_guard(directory_handle)
        except OSError as exc:
            cleanup_error = cleanup_error or exc

    if cleanup_error is not None:
        cleanup_failure = DocumentError(
            DocumentErrorCode.INTERNAL_ERROR,
            "emit",
            "private publication cleanup failed",
            details={
                "publication": "indeterminate" if published else "refused",
                "reason": "cleanup_failed",
            },
        )
        raise cleanup_failure from (failure or cleanup_error)
    if failure is not None:
        if failure_cause is not None:
            raise failure from failure_cause
        raise failure
    return digest
