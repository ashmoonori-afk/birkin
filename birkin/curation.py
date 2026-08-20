from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from .curation_apply import apply_plan
from .curation_contract import (
    CurationOutcome,
    sanitize_model_record,
    sanitize_summary,
)
from .curation_gate import _dense_zone_links, validate_clamp
from .curation_prompt import (
    build_plan_prompt,
    extract_plan,
    mechanical_catalog,
)


def snapshot_vault(vault: Path, cfg: dict | None = None) -> str | None:
    """Checkpoint the vault before curation rewrites it.

    "No delete op is expressible" bounds what curation *can* do; this makes
    even the accepted ops reversible. Reuses the workspace checkpoint store —
    it was already generic over any directory.
    """
    from . import checkpoints
    from . import config as _config
    cfg = cfg if cfg is not None else _config.load_config()
    if not cfg.get("checkpoints", True):
        return None
    mgr = checkpoints.CheckpointManager(
        enabled=True, keep=int(cfg.get("checkpoint_keep", 20)))
    mgr.new_turn()
    return mgr.ensure_checkpoint(vault, reason="curate-memory")


@contextmanager
def _pinned_vault_locator(
    vault: Path,
) -> Iterator[tuple[Callable[[], Path], Path, int | None]]:
    canonical = Path(vault).expanduser().resolve()
    if os.name == "nt":
        from .skills.bundle_publish_windows_io import (
            READ_ATTRIBUTES,
            close,
            open_handle,
        )
        from .skills.manager import _windows_kernel32

        kernel32 = _windows_kernel32()
        handle = open_handle(
            kernel32,
            canonical,
            access=READ_ATTRIBUTES,
        )
        try:
            yield (lambda: canonical), canonical, None
        finally:
            close(kernel32, handle)
        return

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(canonical, flags)
    fd_root = Path("/dev/fd")
    if not fd_root.is_dir():
        fd_root = Path("/proc/self/fd")
    mutation_root = fd_root / str(descriptor)

    def current_path() -> Path:
        if sys.platform == "darwin":
            import fcntl

            encoded = fcntl.fcntl(
                descriptor,
                50,
                b"\0" * 1024,
            )
            return Path(
                encoded.split(b"\0", 1)[0].decode()
            )
        return Path(
            os.readlink(f"/proc/self/fd/{descriptor}")
        )

    try:
        yield current_path, mutation_root, descriptor
    finally:
        active_error = sys.exc_info()[1]
        try:
            os.close(descriptor)
        except OSError:
            if active_error is None:
                raise


def run_curation_pass(vault: Path, complete: Callable[[str], str], *,
                      provider: str = "?", model: str | None = None,
                      untrusted: str = "", apply: bool = True,
                      now: datetime | None = None) -> CurationOutcome:
    with _pinned_vault_locator(vault) as (
        current_vault,
        mutation_root,
        root_fd,
    ):
        return _run_curation_pass_pinned(
            vault,
            current_vault,
            mutation_root,
            root_fd,
            complete,
            provider=provider,
            model=model,
            untrusted=untrusted,
            apply=apply,
            now=now,
        )


def _run_curation_pass_pinned(
    configured_vault: Path,
    current_vault: Callable[[], Path],
    mutation_root: Path,
    root_fd: int | None,
    complete: Callable[[str], str],
    *,
    provider: str,
    model: str | None,
    untrusted: str,
    apply: bool,
    now: datetime | None,
) -> CurationOutcome:
    from .memory import VaultMemory

    now = now or datetime.now(timezone.utc)
    memory = VaultMemory(
        {"vault_path": str(configured_vault)},
        filesystem_root=current_vault(),
    )
    dex = memory.dex
    dex.refresh()
    pinned_entries = dex.entries()
    catalog = mechanical_catalog(dex, now=now)
    snap = {n["slug"]: {"zone": "" if n["zone"] == "inbox" else n["zone"],
                        "type": n["type"], "polarity": n["polarity"],
                        "links": n["links"]}
            for n in catalog["notes"]}
    prompt = build_plan_prompt(catalog, untrusted=untrusted)

    move_note = memory.rezone
    read_note = None
    write_note = None
    windows_anchor = None
    if apply:
        memory = VaultMemory(
            {"vault_path": str(configured_vault)},
            filesystem_root=mutation_root,
        )
        memory.pin_index(pinned_entries)
        dex = memory.dex
        move_note = memory.rezone
        if root_fd is not None:
            from .curation_anchor import AnchoredCuration

            anchor = AnchoredCuration(
                root_fd,
                pinned_entries,
                memory,
            )
            move_note = anchor.move
            read_note = anchor.read
            write_note = anchor.write
        elif os.name == "nt":
            from .curation_anchor_windows import (
                WindowsAnchoredCuration,
            )

            windows_anchor = WindowsAnchoredCuration(
                current_vault(),
                pinned_entries,
                memory,
            )
            move_note = windows_anchor.move
            read_note = windows_anchor.read
            write_note = windows_anchor.write

    outcome: CurationOutcome | None = None
    try:
        raw = complete(prompt) or ""
        plan = extract_plan(raw)
        gate = validate_clamp(plan, dex, snap, now=now)
        accepted = _dense_zone_links(gate.accepted, snap)
        if apply:
            if accepted:
                snapshot_vault(current_vault())
            effected = apply_plan(
                accepted,
                memory.vault,
                dex,
                move_note=move_note,
                validate_vault=memory.assert_vault_identity,
                read_note=read_note,
                write_note=write_note,
            )
        else:
            effected = []        # --dry-run: propose and gate, change nothing
        outcome = CurationOutcome(
            provider=provider, model=model,
            accepted=[sanitize_model_record(o) for o in accepted],
            dropped=[{"op": sanitize_model_record(d.op),
                      "reason": sanitize_summary(d.reason)}
                     for d in gate.dropped],
            effected=effected, archive_cap=gate.archive_cap,
            summary=sanitize_summary(plan.get("summary", "")),
            raw_text=sanitize_summary(raw)[:4000],
            plan_ops=len(plan.get("ops", [])),
        )
    finally:
        if windows_anchor is not None:
            active_error = sys.exc_info()[1]
            try:
                windows_anchor.close()
            except OSError as close_error:
                if active_error is None and outcome is not None:
                    outcome.effected.append({
                        "op": "close",
                        "error": str(close_error),
                        "residue": True,
                        "retryable": False,
                    })
                elif active_error is None:
                    raise
    if outcome is None:
        raise RuntimeError("curation outcome was not produced")
    return outcome
