from __future__ import annotations

import hashlib


def _vault_file_manifest(vault):
    files = []
    for path in sorted(vault.rglob("*.md")):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        files.append({
            "path": path.relative_to(vault).as_posix(),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    return files


def _moved_files(before, after):
    remaining = list(after)
    moved = []
    for old in before:
        for new in list(remaining):
            if old["sha256"] == new["sha256"] and old["path"] != new["path"]:
                moved.append({"from": old["path"], "to": new["path"],
                              "sha256": old["sha256"]})
                remaining.remove(new)
                break
    return moved


def cmd_curate_memory(args) -> int:
    from . import config, curation, providers, store
    cfg = config.load_config()
    vault = config.vault_dir(cfg)
    provider = args.provider or (cfg.get("provider", "claude-cli")
                                 .removesuffix("-cli"))
    completer = providers.get_completer(provider, model=args.model, cfg=cfg,
                                        cwd=str(vault))
    print(f"curate-memory: provider={provider} "
          f"model={args.model or '(default)'} vault={vault}")
    before_files = _vault_file_manifest(vault)
    outcome = curation.run_curation_pass(vault, completer,
                                         provider=provider, model=args.model)
    after_files = _vault_file_manifest(vault)
    print(f"proposed {outcome.plan_ops} ops -> "
          f"{len(outcome.accepted)} accepted, {len(outcome.dropped)} dropped "
          f"(archive cap {outcome.archive_cap})")
    for e in outcome.effected:
        print("  applied:", e)
    if outcome.dropped:
        from collections import Counter
        reasons = Counter(d["reason"] for d in outcome.dropped)
        print("  dropped:", dict(reasons))
    if outcome.summary:
        print("\nsummary:", outcome.summary)
    audit_path = store.save_run(
        "curate-memory",
        f"{provider} proposed {outcome.plan_ops} memory curation op(s)",
        details={
            "provider": provider,
            "model": args.model,
            "vault": str(vault),
            "plan_ops": outcome.plan_ops,
            "accepted": outcome.accepted,
            "dropped": outcome.dropped,
            "effected": outcome.effected,
            "archive_cap": outcome.archive_cap,
            "summary": outcome.summary,
            "raw_text": outcome.raw_text,
            "before_files": before_files,
            "after_files": after_files,
            "moved_files": _moved_files(before_files, after_files),
        },
    )
    print(f"audit: {audit_path}")
    return 0
