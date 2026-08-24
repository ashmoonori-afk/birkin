from __future__ import annotations

from datetime import datetime, timezone
from collections.abc import Callable
from pathlib import Path

from .curation_apply import apply_plan
from .curation_contract import (
    CurationNote,
    CurationOutcome,
    sanitize_model_object,
    sanitize_summary,
)
from .curation_gate import dense_zone_links, validate_clamp
from .curation_prompt import (
    build_plan_prompt,
    extract_plan,
    mechanical_catalog,
)
from .mnemosyne import Mnemosyne


def run_curation_pass(vault: Path, complete: Callable[[str], str], *,
                      provider: str = "?", model: str | None = None,
                      untrusted: str = "",
                      now: datetime | None = None) -> CurationOutcome:
    now = now or datetime.now(timezone.utc)
    dex = Mnemosyne(vault)
    dex.refresh()
    catalog = mechanical_catalog(dex, now=now)
    snap: dict[str, CurationNote] = {
        note["slug"]: {
            "zone": "" if note["zone"] == "inbox" else note["zone"],
            "type": note["type"],
            "polarity": note["polarity"],
            "links": note["links"],
        }
        for note in catalog["notes"]
    }
    prompt = build_plan_prompt(catalog, untrusted=untrusted)

    raw = complete(prompt) or ""
    plan = extract_plan(raw)
    gate = validate_clamp(plan, dex, snap, now=now)
    accepted = dense_zone_links(gate.accepted, snap)
    effected = apply_plan(accepted, vault, dex)
    summary = plan.get("summary", "")
    operations = plan.get("ops", [])
    return CurationOutcome(
        provider=provider,
        model=model,
        accepted=[sanitize_model_object(operation) for operation in accepted],
        dropped=[
            {
                "op": sanitize_model_object(dropped.op),
                "reason": sanitize_summary(dropped.reason),
            }
            for dropped in gate.dropped
        ],
        effected=effected,
        archive_cap=gate.archive_cap,
        summary=sanitize_summary(summary if isinstance(summary, str) else ""),
        raw_text=sanitize_summary(raw)[:4000],
        plan_ops=len(operations) if isinstance(operations, list) else 0,
    )
