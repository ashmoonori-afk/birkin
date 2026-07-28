from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

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
from .mnemosyne import Mnemosyne


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


def run_curation_pass(vault: Path, complete: Callable[[str], str], *,
                      provider: str = "?", model: str | None = None,
                      untrusted: str = "", apply: bool = True,
                      now: datetime | None = None) -> CurationOutcome:
    now = now or datetime.now(timezone.utc)
    dex = Mnemosyne(vault)
    dex.refresh()
    catalog = mechanical_catalog(dex, now=now)
    snap = {n["slug"]: {"zone": "" if n["zone"] == "inbox" else n["zone"],
                        "type": n["type"], "polarity": n["polarity"],
                        "links": n["links"]}
            for n in catalog["notes"]}
    prompt = build_plan_prompt(catalog, untrusted=untrusted)

    raw = complete(prompt) or ""
    plan = extract_plan(raw)
    gate = validate_clamp(plan, dex, snap, now=now)
    accepted = _dense_zone_links(gate.accepted, snap)
    if apply:
        if accepted:
            snapshot_vault(vault)
        effected = apply_plan(accepted, vault, dex)
    else:
        effected = []        # --dry-run: propose and gate, change nothing
    return CurationOutcome(
        provider=provider, model=model,
        accepted=[sanitize_model_record(o) for o in accepted],
        dropped=[{"op": sanitize_model_record(d.op),
                  "reason": sanitize_summary(d.reason)}
                 for d in gate.dropped],
        effected=effected, archive_cap=gate.archive_cap,
        summary=sanitize_summary(plan.get("summary", "")),
        raw_text=sanitize_summary(raw)[:4000],
        plan_ops=len(plan.get("ops", [])))
