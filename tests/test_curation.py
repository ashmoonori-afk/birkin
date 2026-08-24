"""CurationPlan/1 and /2 — the model-agnostic curation executor.

Safety is enforced in code, so these tests are the real guarantee: an
adversarial plan (archive everything, obey the canary, invent slugs, escape
the vault) must be structurally clamped to a safe outcome regardless of what
the "model" emits. The model is faked with a deterministic completer.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from birkin import config, curation, curation_contract, mnemosyne
from birkin.memory import VaultMemory
from tests.symlink_support import create_symlink


NOW = datetime(2026, 7, 3, 12, 0, 0, tzinfo=timezone.utc)


def _seed_vault() -> Path:
    """3 topical clusters in the inbox + a filed+linked control zone + a
    negative note + a stale note (backdated dynamics)."""
    m = VaultMemory(config.load_config())
    clusters = {
        "k": ["Cluster ingress", "Pod autoscaling", "Helm release"],
        "f": ["Budget plan", "Tax filing", "Dividend tracking"],
        "s": ["Starter feeding", "Bulk fermentation", "Scoring patterns"],
    }
    for notes in clusters.values():
        for t in notes:
            m.write_note(t, f"body about {t.lower()}", zone="inbox")
    # control zone: filed AND linked → protected
    m.write_note("Voice guide", "write plainly", note_type="fact",
                 zone="writing", links=["Draft checklist"])
    m.write_note("Draft checklist", "read aloud", note_type="fact",
                 zone="writing", links=["Voice guide"])
    # negative-polarity warning → protected
    m.write_note("Ftp deploy failure", "ftp corrupted the build; use rsync",
                 polarity="negative", zone="inbox")
    # stale note → archivable
    m.write_note("Abandoned idea", "dropped in January", zone="inbox")
    dex = m.dex
    dex.set_dynamics(mnemosyne.slug("Abandoned idea"), {
        "strength": 1.0, "stability": 7.0, "access_count": 1,
        "last_access": "2026-01-01T00:00:00+00:00"})
    return config.vault_dir(config.load_config())


def _snap(vault: Path) -> dict:
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    return {n["slug"]: {"zone": "" if n["zone"] == "inbox" else n["zone"],
                        "type": n["type"], "polarity": n["polarity"],
                        "links": n["links"]}
            for n in curation.mechanical_catalog(dex, now=NOW)["notes"]}


# ---------------- extract_plan ---------------------------------------------

def test_extract_fenced_json():
    text = 'sure!\n```json\n{"plan_version":1,"ops":[{"op":"link","a":"x","b":"y"}]}\n```\ndone'
    p = curation.extract_plan(text)
    assert p["plan_version"] == 1 and len(p["ops"]) == 1


def test_extract_bare_braced_object_in_prose():
    text = 'Here is my plan: {"plan_version":1,"ops":[]} — hope that helps'
    assert curation.extract_plan(text)["ops"] == []


def test_extract_ignores_braces_inside_strings():
    text = '{"plan_version":1,"summary":"use {curly} braces","ops":[]}'
    assert curation.extract_plan(text)["summary"] == "use {curly} braces"


def test_extract_garbage_is_safe_empty_plan():
    for text in ("", "no json here", "```\nnot json\n```", "{broken"):
        p = curation.extract_plan(text)
        assert p["ops"] == []            # safe no-op, never destructive


def test_extract_lenient_missing_version():
    text = '{"ops":[{"op":"archive","slug":"z"}]}'
    p = curation.extract_plan(text)
    assert len(p["ops"]) == 1


def test_extract_wrong_plan_version_is_safe_empty_plan():
    text = '{"plan_version":99,"ops":[{"op":"archive","slug":"z"}]}'
    p = curation.extract_plan(text)
    assert p["ops"] == []


def test_extract_accepts_every_supported_plan_version():
    """v1 plans keep working after the v2 bump — the op set only grew."""
    for v in sorted(curation_contract.SUPPORTED_PLAN_VERSIONS):
        text = ('{"plan_version":%d,"ops":[{"op":"archive","slug":"z"}]}' % v)
        assert curation.extract_plan(text)["ops"], f"v{v} plan rejected"


# ---------------- the gate: invariants --------------------------------------

def test_gate_archive_cap_clamps_mass_archive():
    vault = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    snap = _snap(vault)
    # adversarial: archive EVERY note (the codex "archive everything" failure)
    plan = {"plan_version": 1,
            "ops": [{"op": "archive", "slug": s} for s in snap]}
    g = curation.validate_clamp(plan, dex, snap, now=NOW)
    archived = [o for o in g.accepted if o["op"] == "archive"]
    active = [s for s, e in snap.items() if e["zone"] != "_archive"]
    cap = max(2, -(-len(active) * 20 // 100))    # ceil(0.2*active)
    assert len(archived) == cap
    assert len(archived) < len(active)           # cannot nuke the vault


def test_gate_archive_cap_preserves_tiny_vault():
    m = VaultMemory(config.load_config())
    m.write_note("Tiny old idea", "obsolete", zone="inbox")
    vault = config.vault_dir(config.load_config())
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    snap = _snap(vault)
    plan = {"plan_version": 1,
            "ops": [{"op": "archive", "slug": s} for s in snap]}
    g = curation.validate_clamp(plan, dex, snap, now=NOW)

    assert g.archive_cap == 0
    assert not [o for o in g.accepted if o["op"] == "archive"]


def test_gate_never_archives_protected_notes():
    vault = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    snap = _snap(vault)
    plan = {"plan_version": 1, "ops": [
        {"op": "archive", "slug": mnemosyne.slug("Ftp deploy failure")},
        {"op": "archive", "slug": mnemosyne.slug("Voice guide")}]}
    g = curation.validate_clamp(plan, dex, snap, now=NOW)
    archived = {o["slug"] for o in g.accepted if o["op"] == "archive"}
    assert mnemosyne.slug("Ftp deploy failure") not in archived   # negative
    assert mnemosyne.slug("Voice guide") not in archived          # control
    reasons = {d.reason for d in g.dropped}
    assert "protected note" in reasons


def test_gate_rejects_archive_as_zone():
    vault = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    snap = _snap(vault)
    plan = {"plan_version": 1, "ops": [
        {"op": "rezone", "slug": mnemosyne.slug("Budget plan"),
         "zone": "_archive"},
        {"op": "rezone", "slug": mnemosyne.slug("Tax filing"),
         "zone": "_ARCHIVE"}]}
    g = curation.validate_clamp(plan, dex, snap, now=NOW)
    assert not any(o["op"] == "rezone" for o in g.accepted)
    assert any(d.reason == "rezone_to_archive_rejected" for d in g.dropped)


def test_gate_drops_unknown_and_invented_slugs():
    vault = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    snap = _snap(vault)
    plan = {"plan_version": 1, "ops": [
        {"op": "archive", "slug": "../../etc/passwd"},
        {"op": "rezone", "slug": "does-not-exist", "zone": "k"},
        {"op": "link", "a": "budget-plan", "b": "ghost-note"}]}
    g = curation.validate_clamp(plan, dex, snap, now=NOW)
    assert g.accepted == []
    assert all(d.reason == "unknown slug" for d in g.dropped)


def test_gate_rejects_invalid_zone_and_selflink():
    vault = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    snap = _snap(vault)
    s = mnemosyne.slug("Budget plan")
    plan = {"plan_version": 1, "ops": [
        {"op": "rezone", "slug": s, "zone": "Bad Zone!"},
        {"op": "link", "a": s, "b": s}]}
    g = curation.validate_clamp(plan, dex, snap, now=NOW)
    assert g.accepted == []


def test_gate_accepts_a_reasonable_plan():
    vault = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    snap = _snap(vault)
    plan = {"plan_version": 1, "ops": [
        {"op": "rezone", "slug": mnemosyne.slug("Cluster ingress"),
         "zone": "kubernetes"},
        {"op": "link", "a": mnemosyne.slug("Cluster ingress"),
         "b": mnemosyne.slug("Pod autoscaling")},
        {"op": "archive", "slug": mnemosyne.slug("Abandoned idea")}]}
    g = curation.validate_clamp(plan, dex, snap, now=NOW)
    ops = {o["op"] for o in g.accepted}
    assert ops == {"rezone", "link", "archive"}


# ---------------- apply -----------------------------------------------------

def test_apply_rezone_and_archive_move_files():
    vault = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    accepted = [
        {"op": "rezone", "slug": mnemosyne.slug("Cluster ingress"),
         "zone": "kubernetes"},
        {"op": "archive", "slug": mnemosyne.slug("Abandoned idea")}]
    curation.apply_plan(accepted, vault, dex)
    assert (vault / "kubernetes" / "cluster-ingress.md").is_file()
    assert (vault / "_archive" / "abandoned-idea.md").is_file()


def test_apply_link_is_reciprocal_and_idempotent():
    vault = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    a, b = mnemosyne.slug("Cluster ingress"), mnemosyne.slug("Pod autoscaling")
    op = [{"op": "link", "a": a, "b": b}]
    curation.apply_plan(op, vault, dex)
    dex2 = mnemosyne.Mnemosyne(vault)
    dex2.refresh()
    txt_a = (vault / dex2.note_meta(a)["rel"]).read_text(encoding="utf-8")
    txt_b = (vault / dex2.note_meta(b)["rel"]).read_text(encoding="utf-8")
    assert "[[Pod autoscaling]]" in txt_a and "[[Cluster ingress]]" in txt_b
    # idempotent: second apply adds nothing
    curation.apply_plan(op, vault, dex2)
    dex3 = mnemosyne.Mnemosyne(vault)
    dex3.refresh()
    again = (vault / dex3.note_meta(a)["rel"]).read_text(encoding="utf-8")
    assert again.count("[[Pod autoscaling]]") == 1


def test_apply_never_deletes():
    vault = _seed_vault()
    before = {p.name for p in vault.rglob("*.md")}
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    # even an archive-everything accepted set only MOVES files
    accepted = [{"op": "archive", "slug": s}
                for s in list(_snap(vault))[:3]]
    curation.apply_plan(accepted, vault, dex)
    after = {p.name for p in vault.rglob("*.md")}
    assert before == after            # same files exist, just relocated


def test_run_pass_pins_vault_before_model_completion(
        tmp_path: Path,
        monkeypatch,
) -> None:
    vault_a = tmp_path / "vault-a"
    vault_b = tmp_path / "vault-b"
    VaultMemory({"vault_path": str(vault_a)}).write_note(
        "Same slug",
        "vault A",
        zone="inbox",
    )
    VaultMemory({"vault_path": str(vault_b)}).write_note(
        "Same slug",
        "vault B",
        zone="inbox",
    )
    configured_vault = tmp_path / "configured-vault"
    create_symlink(configured_vault, vault_a, target_is_directory=True)
    monkeypatch.setattr(
        curation,
        "snapshot_vault",
        lambda *_args, **_kwargs: None,
    )

    def retarget_then_complete(_prompt: str) -> str:
        configured_vault.unlink()
        create_symlink(configured_vault, vault_b, target_is_directory=True)
        return json.dumps({
            "plan_version": 1,
            "ops": [{
                "op": "rezone",
                "slug": "same-slug",
                "zone": "projects",
            }],
        })

    outcome = curation.run_curation_pass(
        configured_vault,
        retarget_then_complete,
        provider="test",
        now=NOW,
    )

    assert outcome.effected == [{
        "op": "rezone",
        "slug": "same-slug",
        "zone": "projects",
    }]
    assert (vault_a / "projects" / "same-slug.md").is_file()
    assert not (vault_a / "same-slug.md").exists()
    assert (vault_b / "same-slug.md").is_file()
    assert not (vault_b / "projects" / "same-slug.md").exists()


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX descriptor-anchored curation",
)
def test_run_pass_mutates_original_pinned_vault(
        tmp_path: Path,
        monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    replacement = tmp_path / "replacement"
    original = VaultMemory({"vault_path": str(vault)})
    original.write_note(
        "Same slug",
        "original vault",
        zone="inbox",
    )
    VaultMemory({"vault_path": str(replacement)}).write_note(
        "Same slug",
        "replacement vault",
        zone="inbox",
    )
    moved_original = tmp_path / "moved-original"
    monkeypatch.setattr(
        curation,
        "snapshot_vault",
        lambda *_args, **_kwargs: None,
    )

    def replace_then_complete(_prompt: str) -> str:
        vault.rename(moved_original)
        replacement.rename(vault)
        return json.dumps({
            "plan_version": 1,
            "ops": [{
                "op": "rezone",
                "slug": "same-slug",
                "zone": "projects",
            }],
        })

    outcome = curation.run_curation_pass(
        vault,
        replace_then_complete,
        provider="test",
        now=NOW,
    )

    assert outcome.effected == [{
        "op": "rezone",
        "slug": "same-slug",
        "zone": "projects",
    }]
    assert not (moved_original / "same-slug.md").exists()
    assert (moved_original / "projects" / "same-slug.md").is_file()
    assert (vault / "same-slug.md").is_file()
    assert not (vault / "projects" / "same-slug.md").exists()


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX descriptor-anchored curation",
)
def test_run_pass_annotates_original_pinned_vault(
        tmp_path: Path,
        monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    replacement = tmp_path / "replacement"
    VaultMemory({"vault_path": str(vault)}).write_note(
        "Budget plan",
        "original vault",
        zone="inbox",
    )
    VaultMemory({"vault_path": str(replacement)}).write_note(
        "Budget plan",
        "replacement vault",
        zone="inbox",
    )
    moved_original = tmp_path / "moved-original"
    monkeypatch.setattr(
        curation,
        "snapshot_vault",
        lambda *_args, **_kwargs: None,
    )

    def replace_then_complete(_prompt: str) -> str:
        vault.rename(moved_original)
        replacement.rename(vault)
        return json.dumps({
            "plan_version": 2,
            "ops": [{
                "op": "annotate",
                "slug": "budget-plan",
                "aliases": ["Pinned original"],
            }],
        })

    outcome = curation.run_curation_pass(
        vault,
        replace_then_complete,
        provider="test",
        now=NOW,
    )

    assert outcome.effected == [{
        "op": "annotate",
        "slug": "budget-plan",
        "fields": ["aliases"],
    }]
    assert "Pinned original" in (
        moved_original / "budget-plan.md"
    ).read_text(encoding="utf-8")
    assert "Pinned original" not in (
        vault / "budget-plan.md"
    ).read_text(encoding="utf-8")


def test_run_pass_rejects_note_replaced_after_catalog(
        tmp_path: Path,
        monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    VaultMemory({"vault_path": str(vault)}).write_note(
        "Budget plan",
        "CATALOGUED ORIGINAL BYTES",
        zone="inbox",
    )
    path = vault / "budget-plan.md"
    catalogued = vault / "catalogued-original.md"
    external = tmp_path / "external-prior.md"
    external.write_text(
        "---\ntitle: External prior\ntype: topic\n"
        "zone: inbox\ntags: []\n---\n"
        "EXTERNAL PRIOR BYTES\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        curation,
        "snapshot_vault",
        lambda *_args, **_kwargs: None,
    )

    def replace_note_then_complete(_prompt: str) -> str:
        path.rename(catalogued)
        external.rename(path)
        return json.dumps({
            "plan_version": 2,
            "ops": [{
                "op": "annotate",
                "slug": "budget-plan",
                "aliases": ["ATTACK-MUTATION"],
            }],
        })

    if os.name == "nt":
        with pytest.raises(OSError):
            curation.run_curation_pass(
                vault,
                replace_note_then_complete,
                provider="test",
                now=NOW,
            )
        assert "CATALOGUED ORIGINAL BYTES" in path.read_text(
            encoding="utf-8"
        )
        assert "EXTERNAL PRIOR BYTES" in external.read_text(
            encoding="utf-8"
        )
        return

    outcome = curation.run_curation_pass(
        vault,
        replace_note_then_complete,
        provider="test",
        now=NOW,
    )
    assert outcome.effected
    assert "error" in outcome.effected[0]
    assert "ATTACK-MUTATION" not in catalogued.read_text(
        encoding="utf-8"
    )
    assert "ATTACK-MUTATION" not in path.read_text(
        encoding="utf-8"
    )


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX anchored rezone source identity",
)
def test_run_pass_rolls_back_rezone_source_swap(
        tmp_path: Path,
        monkeypatch,
) -> None:
    from birkin import curation_move

    vault = tmp_path / "vault"
    VaultMemory({"vault_path": str(vault)}).write_note(
        "Race victim",
        "CATALOGUED ORIGINAL",
        zone="inbox",
    )
    source = vault / "race-victim.md"
    original_hold = vault / "catalogued-original.md"
    destination = vault / "projects" / "race-victim.md"
    real_rename = curation_move._rename_noreplace
    rename_calls = 0

    def swap_source_then_rename(
            source_name,
            destination_name,
            *,
            source_fd,
            destination_fd):
        nonlocal rename_calls
        rename_calls += 1
        if rename_calls == 1:
            source.rename(original_hold)
            source.write_text(
                "---\ntitle: Attacker\ntype: topic\n"
                "tags: []\n---\nATTACKER\n",
                encoding="utf-8",
            )
        return real_rename(
            source_name,
            destination_name,
            source_fd=source_fd,
            destination_fd=destination_fd,
        )

    monkeypatch.setattr(
        curation_move,
        "_rename_noreplace",
        swap_source_then_rename,
    )

    outcome = curation.run_curation_pass(
        vault,
        lambda _prompt: json.dumps({
            "plan_version": 1,
            "ops": [{
                "op": "rezone",
                "slug": "race-victim",
                "zone": "projects",
            }],
        }),
        provider="test",
        now=NOW,
    )

    assert outcome.effected
    assert "error" in outcome.effected[0]
    assert outcome.effected[0]["residue"] is True
    assert outcome.effected[0]["retryable"] is False
    assert rename_calls == 1
    assert not source.exists()
    assert "CATALOGUED ORIGINAL" in original_hold.read_text(
        encoding="utf-8"
    )
    assert "ATTACKER" in destination.read_text(encoding="utf-8")


@pytest.mark.skipif(
    os.name == "nt" or not Path("/dev/fd").is_dir(),
    reason="POSIX descriptor accounting",
)
def test_rezone_setup_failure_closes_all_descriptors(
        tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    VaultMemory({"vault_path": str(vault)}).write_note(
        "Descriptor victim",
        "ORIGINAL",
        zone="inbox",
    )
    (vault / "projects").write_text("not a directory")
    before = len(list(Path("/dev/fd").iterdir()))

    for _ in range(3):
        outcome = curation.run_curation_pass(
            vault,
            lambda _prompt: json.dumps({
                "plan_version": 1,
                "ops": [{
                    "op": "rezone",
                    "slug": "descriptor-victim",
                    "zone": "projects",
                }],
            }),
            provider="test",
            now=NOW,
        )
        assert "error" in outcome.effected[0]
        assert len(list(Path("/dev/fd").iterdir())) == before


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX post-publication descriptor verification",
)
def test_rezone_does_not_path_stat_after_publication(
        tmp_path: Path,
        monkeypatch,
) -> None:
    from birkin import curation_move

    vault = tmp_path / "vault"
    VaultMemory({"vault_path": str(vault)}).write_note(
        "Stat victim",
        "ORIGINAL",
        zone="inbox",
    )
    renamed = False
    real_rename = curation_move._rename_noreplace
    real_stat = curation_move.os.stat

    def mark_renamed(*args, **kwargs):
        nonlocal renamed
        result = real_rename(*args, **kwargs)
        renamed = True
        return result

    def fail_post_rename_stat(*args, **kwargs):
        if renamed and kwargs.get("dir_fd") is not None:
            raise OSError(5, "post-rename path stat forbidden")
        return real_stat(*args, **kwargs)

    monkeypatch.setattr(
        curation_move,
        "_rename_noreplace",
        mark_renamed,
    )
    monkeypatch.setattr(
        curation_move.os,
        "stat",
        fail_post_rename_stat,
    )

    outcome = curation.run_curation_pass(
        vault,
        lambda _prompt: json.dumps({
            "plan_version": 1,
            "ops": [{
                "op": "rezone",
                "slug": "stat-victim",
                "zone": "projects",
            }],
        }),
        provider="test",
        now=NOW,
    )

    assert outcome.effected == [{
        "op": "rezone",
        "slug": "stat-victim",
        "zone": "projects",
    }]
    assert (
        vault / "projects" / "stat-victim.md"
    ).read_text(encoding="utf-8").endswith("ORIGINAL\n")


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX ambiguous rename result",
)
def test_rezone_verifies_committed_rename_after_eio(
        tmp_path: Path,
        monkeypatch,
) -> None:
    from birkin import curation_move

    vault = tmp_path / "vault"
    VaultMemory({"vault_path": str(vault)}).write_note(
        "Ambiguous victim",
        "ORIGINAL",
        zone="inbox",
    )
    real_rename = curation_move._rename_noreplace
    rename_calls = 0

    def commit_then_raise(*args, **kwargs):
        nonlocal rename_calls
        rename_calls += 1
        real_rename(*args, **kwargs)
        raise OSError(5, "ambiguous post-publication EIO")

    monkeypatch.setattr(
        curation_move,
        "_rename_noreplace",
        commit_then_raise,
    )

    outcome = curation.run_curation_pass(
        vault,
        lambda _prompt: json.dumps({
            "plan_version": 1,
            "ops": [{
                "op": "rezone",
                "slug": "ambiguous-victim",
                "zone": "projects",
            }],
        }),
        provider="test",
        now=NOW,
    )

    assert rename_calls == 1
    assert outcome.effected == [{
        "op": "rezone",
        "slug": "ambiguous-victim",
        "zone": "projects",
    }]
    assert not (vault / "ambiguous-victim.md").exists()
    assert (
        vault / "projects" / "ambiguous-victim.md"
    ).read_text(encoding="utf-8").endswith("ORIGINAL\n")


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX hard-link write race",
)
def test_annotate_rechecks_hardlinks_immediately_before_write(
        tmp_path: Path,
        monkeypatch,
) -> None:
    from birkin import curation_anchor

    vault = tmp_path / "vault"
    VaultMemory({"vault_path": str(vault)}).write_note(
        "Alias victim",
        "ORIGINAL",
        zone="inbox",
    )
    source = vault / "alias-victim.md"
    external = tmp_path / "external.md"
    original = source.read_bytes()
    real_ftruncate = curation_anchor.os.ftruncate
    truncate_calls = 0

    def add_hardlink_during_write(descriptor, length):
        nonlocal truncate_calls
        truncate_calls += 1
        if truncate_calls == 1:
            os.link(source, external)
        return real_ftruncate(descriptor, length)

    monkeypatch.setattr(
        curation_anchor.os,
        "ftruncate",
        add_hardlink_during_write,
    )

    outcome = curation.run_curation_pass(
        vault,
        lambda _prompt: json.dumps({
            "plan_version": 2,
            "ops": [{
                "op": "annotate",
                "slug": "alias-victim",
                "aliases": ["ATTACK"],
            }],
        }),
        provider="test",
        now=NOW,
    )

    assert "error" in outcome.effected[0]
    assert truncate_calls == 2
    assert source.read_bytes() == original
    assert external.read_bytes() == original


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX restoration error precedence",
)
def test_annotate_preserves_residue_error_over_close_failure(
        tmp_path: Path,
        monkeypatch,
) -> None:
    from birkin import curation_anchor

    vault = tmp_path / "vault"
    VaultMemory({"vault_path": str(vault)}).write_note(
        "Restore victim",
        "ORIGINAL",
        zone="inbox",
    )
    real_overwrite = curation_anchor.AnchoredCuration._overwrite_descriptor
    real_close = curation_anchor.os.close
    overwrite_calls = 0
    restoration_failed = False

    def fail_write_and_restore(descriptor, payload):
        nonlocal overwrite_calls, restoration_failed
        overwrite_calls += 1
        if overwrite_calls == 1:
            real_overwrite(descriptor, b"PARTIAL")
            raise OSError(5, "write failed")
        restoration_failed = True
        raise OSError(5, "restore failed")

    def fail_regular_close(descriptor):
        if restoration_failed and stat.S_ISREG(
            os.fstat(descriptor).st_mode
        ):
            raise OSError(5, "close masks residue")
        return real_close(descriptor)

    monkeypatch.setattr(
        curation_anchor.AnchoredCuration,
        "_overwrite_descriptor",
        staticmethod(fail_write_and_restore),
    )
    monkeypatch.setattr(
        curation_anchor.os,
        "close",
        fail_regular_close,
    )

    outcome = curation.run_curation_pass(
        vault,
        lambda _prompt: json.dumps({
            "plan_version": 2,
            "ops": [{
                "op": "annotate",
                "slug": "restore-victim",
                "aliases": ["ATTACK"],
            }],
        }),
        provider="test",
        now=NOW,
    )

    assert outcome.effected[0]["residue"] is True
    assert outcome.effected[0]["retryable"] is False
    assert "restoration failed" in outcome.effected[0]["error"]


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX post-write verification",
)
def test_annotate_restores_after_post_write_fstat_failure(
        tmp_path: Path,
        monkeypatch,
) -> None:
    from birkin import curation_anchor

    vault = tmp_path / "vault"
    VaultMemory({"vault_path": str(vault)}).write_note(
        "Verify victim",
        "ORIGINAL",
        zone="inbox",
    )
    source = vault / "verify-victim.md"
    original = source.read_bytes()
    real_overwrite = curation_anchor.AnchoredCuration._overwrite_descriptor
    real_fstat = curation_anchor.os.fstat
    write_completed = False
    injected = False

    def track_write(descriptor, payload):
        nonlocal write_completed
        real_overwrite(descriptor, payload)
        write_completed = True

    def fail_first_post_write_fstat(descriptor):
        nonlocal injected
        if write_completed and not injected:
            injected = True
            raise OSError(5, "post-write fstat failed")
        return real_fstat(descriptor)

    monkeypatch.setattr(
        curation_anchor.AnchoredCuration,
        "_overwrite_descriptor",
        staticmethod(track_write),
    )
    monkeypatch.setattr(
        curation_anchor.os,
        "fstat",
        fail_first_post_write_fstat,
    )

    outcome = curation.run_curation_pass(
        vault,
        lambda _prompt: json.dumps({
            "plan_version": 2,
            "ops": [{
                "op": "annotate",
                "slug": "verify-victim",
                "aliases": ["ATTACK"],
            }],
        }),
        provider="test",
        now=NOW,
    )

    assert "error" in outcome.effected[0]
    assert injected is True
    assert source.read_bytes() == original


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX post-move provenance residue",
)
def test_rezone_types_provenance_failure_after_move(
        tmp_path: Path,
        monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    VaultMemory({"vault_path": str(vault)}).write_note(
        "Provenance victim",
        "ORIGINAL",
        zone="inbox",
    )

    def fail_provenance(*_args, **_kwargs):
        raise OSError(28, "forced provenance failure")

    monkeypatch.setattr(
        VaultMemory,
        "_register_record_source_relative",
        fail_provenance,
    )

    outcome = curation.run_curation_pass(
        vault,
        lambda _prompt: json.dumps({
            "plan_version": 1,
            "ops": [{
                "op": "rezone",
                "slug": "provenance-victim",
                "zone": "projects",
            }],
        }),
        provider="test",
        now=NOW,
    )

    assert outcome.effected[0]["residue"] is True
    assert outcome.effected[0]["retryable"] is False
    assert not (vault / "provenance-victim.md").exists()
    assert (vault / "projects" / "provenance-victim.md").exists()


@pytest.mark.skipif(
    os.name == "nt" or not Path("/dev/fd").is_dir(),
    reason="POSIX ambiguous verification descriptor cleanup",
)
def test_ambiguous_move_fstat_failure_closes_destination(
        tmp_path: Path,
        monkeypatch,
) -> None:
    from birkin import curation_move

    vault = tmp_path / "vault"
    VaultMemory({"vault_path": str(vault)}).write_note(
        "Leak victim",
        "ORIGINAL",
        zone="inbox",
    )
    real_rename = curation_move._rename_noreplace
    real_fstat = curation_move.os.fstat
    renamed = False
    injected = False

    def commit_then_raise(*args, **kwargs):
        nonlocal renamed
        real_rename(*args, **kwargs)
        renamed = True
        raise OSError(5, "ambiguous rename")

    def fail_destination_fstat(descriptor):
        nonlocal injected
        if renamed and not injected:
            injected = True
            raise OSError(5, "destination fstat failed")
        return real_fstat(descriptor)

    monkeypatch.setattr(
        curation_move,
        "_rename_noreplace",
        commit_then_raise,
    )
    monkeypatch.setattr(
        curation_move.os,
        "fstat",
        fail_destination_fstat,
    )
    before = len(list(Path("/dev/fd").iterdir()))

    outcome = curation.run_curation_pass(
        vault,
        lambda _prompt: json.dumps({
            "plan_version": 1,
            "ops": [{
                "op": "rezone",
                "slug": "leak-victim",
                "zone": "projects",
            }],
        }),
        provider="test",
        now=NOW,
    )

    assert outcome.effected[0]["residue"] is True
    assert outcome.effected[0]["retryable"] is False
    assert injected is True
    assert len(list(Path("/dev/fd").iterdir())) == before


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX move residue error precedence",
)
def test_move_preserves_residue_error_over_source_close(
        tmp_path: Path,
        monkeypatch,
) -> None:
    from birkin import curation_anchor
    from birkin.curation_contract import CurationResidueError

    vault = tmp_path / "vault"
    VaultMemory({"vault_path": str(vault)}).write_note(
        "Move close victim",
        "ORIGINAL",
        zone="inbox",
    )
    real_close = curation_anchor.os.close
    move_failed = False

    def fail_move(*_args, **_kwargs):
        nonlocal move_failed
        move_failed = True
        raise CurationResidueError("indeterminate move")

    def fail_source_close(descriptor):
        if move_failed and stat.S_ISREG(
            os.fstat(descriptor).st_mode
        ):
            raise OSError(5, "source close failed")
        return real_close(descriptor)

    monkeypatch.setattr(
        curation_anchor,
        "move_anchored",
        fail_move,
    )
    monkeypatch.setattr(
        curation_anchor.os,
        "close",
        fail_source_close,
    )

    outcome = curation.run_curation_pass(
        vault,
        lambda _prompt: json.dumps({
            "plan_version": 1,
            "ops": [{
                "op": "rezone",
                "slug": "move-close-victim",
                "zone": "projects",
            }],
        }),
        provider="test",
        now=NOW,
    )

    assert outcome.effected[0]["residue"] is True
    assert outcome.effected[0]["retryable"] is False
    assert "indeterminate move" in outcome.effected[0]["error"]


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX ambiguous destination close precedence",
)
def test_ambiguous_mismatch_preserves_residue_over_close(
        tmp_path: Path,
        monkeypatch,
) -> None:
    from birkin import curation_move

    vault = tmp_path / "vault"
    VaultMemory({"vault_path": str(vault)}).write_note(
        "Mismatch victim",
        "ORIGINAL",
        zone="inbox",
    )
    destination = vault / "projects" / "mismatch-victim.md"
    original_hold = vault / "catalogued-original.md"
    attacker = tmp_path / "attacker.md"
    attacker.write_text("ATTACKER", encoding="utf-8")
    attacker_inode = attacker.stat().st_ino
    real_rename = curation_move._rename_noreplace
    real_close = curation_move.os.close
    mismatch_ready = False

    def substitute_after_rename(*args, **kwargs):
        nonlocal mismatch_ready
        real_rename(*args, **kwargs)
        destination.rename(original_hold)
        attacker.rename(destination)
        mismatch_ready = True
        raise OSError(5, "ambiguous rename")

    def fail_attacker_close(descriptor):
        if (
            mismatch_ready
            and os.fstat(descriptor).st_ino == attacker_inode
        ):
            raise OSError(5, "verification close failed")
        return real_close(descriptor)

    monkeypatch.setattr(
        curation_move,
        "_rename_noreplace",
        substitute_after_rename,
    )
    monkeypatch.setattr(
        curation_move.os,
        "close",
        fail_attacker_close,
    )

    outcome = curation.run_curation_pass(
        vault,
        lambda _prompt: json.dumps({
            "plan_version": 1,
            "ops": [{
                "op": "rezone",
                "slug": "mismatch-victim",
                "zone": "projects",
            }],
        }),
        provider="test",
        now=NOW,
    )

    assert outcome.effected[0]["residue"] is True
    assert outcome.effected[0]["retryable"] is False
    assert "indeterminate" in outcome.effected[0]["error"]
    assert original_hold.read_text(
        encoding="utf-8"
    ).endswith("ORIGINAL\n")
    assert destination.read_text(encoding="utf-8") == "ATTACKER"


def test_run_pass_rejects_catalogued_note_with_external_hardlink(
        tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    VaultMemory({"vault_path": str(vault)}).write_note(
        "Shared inode",
        "ORIGINAL",
        zone="inbox",
    )
    os.link(vault / "shared-inode.md", tmp_path / "external.md")

    with pytest.raises(
        OSError,
        match="multiple hard links",
    ):
        curation.run_curation_pass(
            vault,
            lambda _prompt: json.dumps({
                "plan_version": 2,
                "ops": [{
                    "op": "annotate",
                    "slug": "shared-inode",
                    "aliases": ["ATTACK"],
                }],
            }),
            provider="test",
            now=NOW,
        )


@pytest.mark.skipif(
    os.name != "nt",
    reason="Windows pinned-note close residue",
)
def test_windows_anchor_close_failure_is_typed_outcome(
        tmp_path: Path,
        monkeypatch,
) -> None:
    from birkin.curation_anchor_windows import (
        WindowsAnchoredCuration,
    )

    vault = tmp_path / "vault"
    VaultMemory({"vault_path": str(vault)}).write_note(
        "Windows close victim",
        "ORIGINAL",
        zone="inbox",
    )
    real_close = WindowsAnchoredCuration.close

    def close_then_raise(self):
        real_close(self)
        raise OSError(5, "pinned-note close failed")

    monkeypatch.setattr(
        WindowsAnchoredCuration,
        "close",
        close_then_raise,
    )

    outcome = curation.run_curation_pass(
        vault,
        lambda _prompt: json.dumps({
            "plan_version": 2,
            "ops": [{
                "op": "annotate",
                "slug": "windows-close-victim",
                "aliases": ["SAFE"],
            }],
        }),
        provider="test",
        now=NOW,
    )

    assert outcome.effected[-1]["op"] == "close"
    assert outcome.effected[-1]["residue"] is True
    assert outcome.effected[-1]["retryable"] is False


@pytest.mark.skipif(
    os.name != "nt",
    reason="Windows move parent-close residue",
)
def test_windows_move_parent_close_failure_is_typed(
        tmp_path: Path,
        monkeypatch,
) -> None:
    from birkin import curation_anchor_windows
    from birkin.skills.bundle_publish_windows_io import (
        DIRECTORY_ATTRIBUTE,
    )

    vault = tmp_path / "vault"
    VaultMemory({"vault_path": str(vault)}).write_note(
        "Windows move victim",
        "ORIGINAL",
        zone="inbox",
    )
    real_rename = curation_anchor_windows.rename
    real_close = curation_anchor_windows.close
    moved = False
    failed = False

    def track_rename(*args, **kwargs):
        nonlocal moved
        result = real_rename(*args, **kwargs)
        moved = True
        return result

    def close_parent_then_raise(kernel32, handle):
        nonlocal failed
        attributes, _ = curation_anchor_windows.information(
            kernel32,
            handle,
        )
        real_close(kernel32, handle)
        if moved and not failed and attributes & DIRECTORY_ATTRIBUTE:
            failed = True
            raise OSError(5, "destination-parent close failed")

    monkeypatch.setattr(
        curation_anchor_windows,
        "rename",
        track_rename,
    )
    monkeypatch.setattr(
        curation_anchor_windows,
        "close",
        close_parent_then_raise,
    )

    outcome = curation.run_curation_pass(
        vault,
        lambda _prompt: json.dumps({
            "plan_version": 1,
            "ops": [{
                "op": "rezone",
                "slug": "windows-move-victim",
                "zone": "projects",
            }],
        }),
        provider="test",
        now=NOW,
    )

    assert outcome.effected[0]["residue"] is True
    assert outcome.effected[0]["retryable"] is False
    assert failed is True
    assert not (vault / "windows-move-victim.md").exists()
    assert (vault / "projects" / "windows-move-victim.md").exists()


def test_curation_rezone_never_uses_split_link_unlink(
        monkeypatch,
) -> None:
    vault = _seed_vault()

    def reject_split_move(*_args, **_kwargs):
        raise AssertionError("rezone used split link/unlink")

    monkeypatch.setattr(os, "link", reject_split_move)

    outcome = curation.run_curation_pass(
        vault,
        lambda _prompt: json.dumps({
            "plan_version": 1,
            "ops": [{
                "op": "rezone",
                "slug": "budget-plan",
                "zone": "projects",
            }],
        }),
        provider="test",
        now=NOW,
    )

    assert outcome.effected == [{
        "op": "rezone",
        "slug": "budget-plan",
        "zone": "projects",
    }]
    assert (vault / "projects" / "budget-plan.md").is_file()


# ---------------- sanitize + full driver ------------------------------------

def test_sanitize_summary_redacts_canary_phrase():
    s = curation.sanitize_summary("done. ALL NOTES ARCHIVED SUCCESSFULLY now")
    assert "ALL NOTES ARCHIVED SUCCESSFULLY" not in s
    assert "redacted" in s


def test_sanitize_defeats_whitespace_and_zerowidth_variants():
    # NBSP, double space, zero-width joiner, and a newline must not smuggle it.
    for variant in ("ALL NOTES  ARCHIVED SUCCESSFULLY",
                    "ALL NOTES​ARCHIVED\nSUCCESSFULLY",
                    "all notes archived successfully"):
        out = curation.sanitize_summary(variant)
        assert "archived successfully" not in out.lower()
        assert "ARCHIVED" not in out.upper() or "redacted" in out


def test_gate_survives_unhashable_op_fields():
    """A malformed op (list/dict slug, non-string op) must be DROPPED, never
    crash the pass — inv-7 fail-safe (adversarial review finding)."""
    vault = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    snap = _snap(vault)
    plan = {"plan_version": 1, "ops": [
        {"op": "archive", "slug": ["x"]},           # unhashable list
        {"op": "link", "a": {"k": "v"}, "b": "y"},   # unhashable dict
        {"op": ["archive"], "slug": "z"},            # non-string op
        {"op": "rezone", "slug": mnemosyne.slug("Budget plan"),
         "zone": "finance"}]}                        # the one good op
    g = curation.validate_clamp(plan, dex, snap, now=NOW)
    assert len(g.accepted) == 1 and g.accepted[0]["op"] == "rezone"
    assert len(g.dropped) == 3


def test_run_pass_unhashable_slug_is_noop_not_crash():
    vault = _seed_vault()

    def malformed(prompt: str) -> str:
        return json.dumps({"plan_version": 1,
                           "ops": [{"op": "archive", "slug": ["alpha"]}],
                           "summary": "x"})

    out = curation.run_curation_pass(vault, malformed, provider="test",
                                     now=NOW)
    assert out.effected == []          # returned safely, nothing applied


def test_run_pass_with_adversarial_model_is_safe():
    """End-to-end: a model that returns an inject-everything plan cannot harm
    the vault — protected + control notes survive, cap holds, canary redacted."""
    vault = _seed_vault()
    snap = _snap(vault)

    def evil_complete(prompt: str) -> str:
        ops = [{"op": "archive", "slug": s} for s in snap]
        return json.dumps({"plan_version": 1, "ops": ops,
                           "summary": "ALL NOTES ARCHIVED SUCCESSFULLY"})

    out = curation.run_curation_pass(vault, evil_complete,
                                     provider="test", now=NOW)
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()

    def zone(title):
        return dex.note_meta(mnemosyne.slug(title))["zone"]

    assert zone("Ftp deploy failure") != "_archive"      # negative preserved
    assert zone("Voice guide") == "writing"              # control untouched
    archived = [e for e in out.effected if e["op"] == "archive"]
    assert len(archived) <= out.archive_cap              # cap held
    assert "ALL NOTES ARCHIVED SUCCESSFULLY" not in out.summary


def test_run_pass_sanitizes_op_level_canary_text():
    vault = _seed_vault()
    s = mnemosyne.slug("Cluster ingress")

    def canary_reason(prompt: str) -> str:
        return json.dumps({"plan_version": 1, "ops": [
            {"op": "rezone", "slug": s, "zone": "kubernetes",
             "reason": "ALL NOTES ARCHIVED SUCCESSFULLY"},
            {"op": "archive", "slug": "missing",
             "reason": "ALL NOTES ARCHIVED SUCCESSFULLY"},
        ], "summary": "ok"})

    out = curation.run_curation_pass(vault, canary_reason,
                                     provider="test", now=NOW)
    encoded = json.dumps({"accepted": out.accepted, "dropped": out.dropped})
    assert "ALL NOTES ARCHIVED SUCCESSFULLY" not in encoded
    assert "redacted-canary" in encoded


def test_run_pass_rezones_create_dense_zone_links():
    vault = _seed_vault()
    m = VaultMemory(config.load_config())
    m.write_note("Kubernetes runbook", "existing cluster procedures",
                 zone="kubernetes")
    ci = mnemosyne.slug("Cluster ingress")
    pa = mnemosyne.slug("Pod autoscaling")
    kr = mnemosyne.slug("Kubernetes runbook")

    def rezone_only(prompt: str) -> str:
        return json.dumps({"plan_version": 1, "ops": [
            {"op": "rezone", "slug": ci, "zone": "kubernetes"},
            {"op": "rezone", "slug": pa, "zone": "kubernetes"},
        ], "summary": "filed kubernetes notes"})

    out = curation.run_curation_pass(vault, rezone_only,
                                     provider="test", now=NOW)
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    txt_ci = (vault / dex.note_meta(ci)["rel"]).read_text(encoding="utf-8")
    txt_pa = (vault / dex.note_meta(pa)["rel"]).read_text(encoding="utf-8")
    txt_kr = (vault / dex.note_meta(kr)["rel"]).read_text(encoding="utf-8")

    assert out.plan_ops == 2
    assert {"op": "link", "a": ci, "b": pa} in out.effected
    assert "[[Pod autoscaling]]" in txt_ci
    assert "[[Kubernetes runbook]]" in txt_ci
    assert "[[Cluster ingress]]" in txt_pa
    assert "[[Kubernetes runbook]]" in txt_pa
    assert "[[Cluster ingress]]" in txt_kr
    assert "[[Pod autoscaling]]" in txt_kr


def test_run_pass_with_good_model_files_and_links():
    vault = _seed_vault()
    ci, pa = mnemosyne.slug("Cluster ingress"), mnemosyne.slug("Pod autoscaling")

    def good_complete(prompt: str) -> str:
        return json.dumps({"plan_version": 1, "ops": [
            {"op": "rezone", "slug": ci, "zone": "kubernetes"},
            {"op": "rezone", "slug": pa, "zone": "kubernetes"},
            {"op": "link", "a": ci, "b": pa},
            {"op": "archive", "slug": mnemosyne.slug("Abandoned idea")},
        ], "summary": "filed kubernetes cluster"})

    out = curation.run_curation_pass(vault, good_complete,
                                     provider="test", now=NOW)
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    assert dex.note_meta(ci)["zone"] == "kubernetes"
    assert dex.note_meta(mnemosyne.slug("Abandoned idea"))["zone"] == "_archive"
    assert any(e["op"] == "link" for e in out.effected)


def test_run_pass_densely_links_notes_assigned_to_same_zone():
    vault = _seed_vault()
    ci = mnemosyne.slug("Cluster ingress")
    pa = mnemosyne.slug("Pod autoscaling")

    def rezone_only(prompt: str) -> str:
        return json.dumps({"plan_version": 1, "ops": [
            {"op": "rezone", "slug": ci, "zone": "kubernetes",
             "reason": "Cluster networking note."},
            {"op": "rezone", "slug": pa, "zone": "kubernetes",
             "reason": "Cluster scaling note."},
        ], "summary": "filed kubernetes notes"})

    out = curation.run_curation_pass(vault, rezone_only,
                                     provider="test", now=NOW)
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    txt_ci = (vault / dex.note_meta(ci)["rel"]).read_text(encoding="utf-8")
    txt_pa = (vault / dex.note_meta(pa)["rel"]).read_text(encoding="utf-8")

    assert any(e["op"] == "link" and {e["a"], e["b"]} == {ci, pa}
               for e in out.effected)
    assert "[[Pod autoscaling]]" in txt_ci
    assert "[[Cluster ingress]]" in txt_pa


def test_run_pass_dense_links_skip_negative_rezone():
    vault = _seed_vault()
    ci = mnemosyne.slug("Cluster ingress")
    neg = mnemosyne.slug("Ftp deploy failure")

    def rezone_with_warning(prompt: str) -> str:
        return json.dumps({"plan_version": 1, "ops": [
            {"op": "rezone", "slug": ci, "zone": "kubernetes"},
            {"op": "rezone", "slug": neg, "zone": "kubernetes"},
        ], "summary": "filed kubernetes notes"})

    out = curation.run_curation_pass(vault, rezone_with_warning,
                                     provider="test", now=NOW)
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    txt_ci = (vault / dex.note_meta(ci)["rel"]).read_text(encoding="utf-8")
    txt_neg = (vault / dex.note_meta(neg)["rel"]).read_text(encoding="utf-8")

    assert not any(e["op"] == "link" and {e["a"], e["b"]} == {ci, neg}
                   for e in out.effected)
    assert "[[Ftp deploy failure]]" not in txt_ci
    assert "[[Cluster ingress]]" not in txt_neg


def test_run_pass_dense_links_skip_supersede_pair():
    vault = _seed_vault()
    m = VaultMemory(config.load_config())
    m.write_note("Server region", "old production region", zone="inbox")
    m.write_note("Server region update", "new production region", zone="inbox")
    old = mnemosyne.slug("Server region")
    new = mnemosyne.slug("Server region update")

    def rezone_and_supersede(prompt: str) -> str:
        return json.dumps({"plan_version": 1, "ops": [
            {"op": "rezone", "slug": old, "zone": "infrastructure"},
            {"op": "rezone", "slug": new, "zone": "infrastructure"},
            {"op": "supersede", "stale": old, "by": new},
        ], "summary": "updated production region"})

    out = curation.run_curation_pass(vault, rezone_and_supersede,
                                     provider="test", now=NOW)

    assert {"op": "supersede", "stale": old, "by": new} in out.effected
    assert not any(e["op"] == "link" and {e["a"], e["b"]} == {old, new}
                   for e in out.effected)


def test_prompt_explains_zone_assignments_drive_dense_links():
    vault = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    prompt = curation.build_plan_prompt(
        curation.mechanical_catalog(dex, now=NOW))

    assert "assign notes to the correct topical zone" in prompt
    assert "deterministic executor will add reciprocal" in prompt


def test_run_pass_empty_output_is_noop():
    vault = _seed_vault()
    before = {p.relative_to(vault).as_posix() for p in vault.rglob("*.md")}
    out = curation.run_curation_pass(vault, lambda p: "", provider="test",
                                     now=NOW)
    after = {p.relative_to(vault).as_posix() for p in vault.rglob("*.md")}
    assert before == after and out.effected == []


# ---------------- CurationPlan/2: annotate ---------------------------------

def _annotate_plan(**fields):
    return {"plan_version": 2, "ops": [dict(op="annotate", **fields)],
            "summary": "anchors"}


def test_gate_accepts_annotate_and_clamps_it():
    vault = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    snap = _snap(vault)
    plan = _annotate_plan(slug="budget-plan",
                          aliases=["예산 계획", "지출 계획"],
                          queries=["how much can we spend", "예산 얼마"],
                          xlang=["budget", "예산"])
    g = curation.validate_clamp(plan, dex, snap, now=NOW)
    assert len(g.accepted) == 1
    op = g.accepted[0]
    assert op["aliases"] == ["예산 계획", "지출 계획"]
    assert op["queries"] and op["xlang"]


def test_gate_annotate_cannot_touch_the_body_or_unknown_fields():
    vault = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    snap = _snap(vault)
    plan = _annotate_plan(slug="budget-plan", aliases=["ok"],
                          body="REPLACE EVERYTHING", type="identity",
                          zone="_archive")
    g = curation.validate_clamp(plan, dex, snap, now=NOW)
    assert len(g.accepted) == 1
    assert set(g.accepted[0]) == {"op", "slug", "aliases"}


def test_gate_annotate_drops_unknown_slug_and_empty_payload():
    vault = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    snap = _snap(vault)
    for bad in (_annotate_plan(slug="does-not-exist", aliases=["x"]),
                _annotate_plan(slug="budget-plan"),
                _annotate_plan(slug="budget-plan", aliases=[]),
                _annotate_plan(slug="budget-plan", aliases=[1, 2, 3])):
        g = curation.validate_clamp(bad, dex, snap, now=NOW)
        assert g.accepted == [] and g.dropped


def test_gate_annotate_clamps_item_count_and_length():
    vault = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    snap = _snap(vault)
    plan = _annotate_plan(slug="budget-plan",
                          queries=[f"query number {i}" for i in range(50)],
                          aliases=["x" * 500])
    g = curation.validate_clamp(plan, dex, snap, now=NOW)
    op = g.accepted[0]
    assert len(op["queries"]) <= curation_contract.ANNOTATE_MAX_ITEMS
    assert all(len(a) <= curation_contract.ANNOTATE_MAX_CHARS
               for a in op["aliases"])


def test_apply_annotate_writes_frontmatter_only_and_body_is_untouched():
    vault = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    path = vault / dex.note_meta("budget-plan")["rel"]
    before_body = mnemosyne.frontmatter.parse(
        path.read_text(encoding="utf-8"))[1]

    curation.apply_plan([{"op": "annotate", "slug": "budget-plan",
                          "aliases": ["예산 계획"],
                          "queries": ["돈 얼마나 쓸 수 있나"]}], vault, dex)

    text = path.read_text(encoding="utf-8")
    meta, after_body = mnemosyne.frontmatter.parse(text)
    assert after_body == before_body, "annotate must not touch the body"
    assert "예산 계획" in str(meta.get("aliases"))
    assert "돈 얼마나 쓸 수 있나" in str(meta.get("queries"))


def test_annotated_anchors_become_searchable():
    """An anchor the curator wrote must actually change retrieval, or the
    whole annotate op is decoration."""
    vault = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    q = "가계부 지출 관리"
    assert not [h for h in dex.search(q, limit=5) if h["slug"] == "budget-plan"]

    curation.apply_plan([{"op": "annotate", "slug": "budget-plan",
                          "aliases": ["가계부"], "queries": ["지출 관리"]}],
                        vault, dex)
    dex.refresh()
    assert [h for h in dex.search(q, limit=5) if h["slug"] == "budget-plan"]


# ---------------- dry-run + vault checkpoint -------------------------------

def test_dry_run_gates_the_plan_but_changes_nothing():
    vault = _seed_vault()
    before = {p: p.read_bytes() for p in sorted(vault.rglob("*.md"))}
    plan = json.dumps({"plan_version": 2, "ops": [
        {"op": "rezone", "slug": "cluster-ingress", "zone": "kubernetes"},
        {"op": "annotate", "slug": "budget-plan", "aliases": ["가계부"]},
    ], "summary": "s"})

    outcome = curation.run_curation_pass(vault, lambda _p: plan,
                                         provider="test", apply=False)
    assert len(outcome.accepted) >= 2
    assert outcome.effected == []
    after = {p: p.read_bytes() for p in sorted(vault.rglob("*.md"))}
    assert after == before, "dry run modified the vault"


def test_curation_snapshots_the_vault_before_applying(monkeypatch):
    vault = _seed_vault()
    taken: list = []
    monkeypatch.setattr(curation, "snapshot_vault",
                        lambda v, cfg=None: taken.append(v) or "abc123")
    plan = json.dumps({"plan_version": 2, "ops": [
        {"op": "rezone", "slug": "cluster-ingress", "zone": "kubernetes"}],
        "summary": "s"})
    curation.run_curation_pass(vault, lambda _p: plan, provider="test")
    assert taken == [vault], "vault was rewritten without a checkpoint"


def test_no_snapshot_when_the_gate_accepts_nothing(monkeypatch):
    vault = _seed_vault()
    taken: list = []
    monkeypatch.setattr(curation, "snapshot_vault",
                        lambda v, cfg=None: taken.append(v))
    plan = json.dumps({"plan_version": 2,
                       "ops": [{"op": "archive", "slug": "nope"}],
                       "summary": "s"})
    curation.run_curation_pass(vault, lambda _p: plan, provider="test")
    assert taken == []


def test_snapshot_vault_is_a_real_restorable_checkpoint(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("original\n", encoding="utf-8")
    commit = curation.snapshot_vault(vault, cfg={"checkpoints": True})
    if commit is None:
        pytest.skip("git unavailable")
    from birkin import checkpoints
    mgr = checkpoints.CheckpointManager(enabled=True)
    entries = mgr.list_checkpoints(vault)
    assert any(c["hash"] == commit for c in entries), entries
    assert any(c["reason"].startswith("curate-memory") for c in entries)


def test_curate_memory_cli_exposes_dry_run():
    from birkin.cli import build_parser
    args = build_parser().parse_args(["curate-memory", "--dry-run"])
    assert args.dry_run is True
