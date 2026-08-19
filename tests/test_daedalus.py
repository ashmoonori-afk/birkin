"""RED-first tests for birkin.daedalus (evidence-linked project document worker).

Contract source: .omo/plans/daedalus-worker.md section 3. The module
birkin/daedalus.py does not exist yet; this file MUST fail on import.

Offline, deterministic, tmp_path-only. ASCII-only strings.
"""

import json

import pytest

from birkin import worker_hooks
from birkin.daedalus import (
    PROFILE,
    DaedalusError,
    add_note,
    create,
    load,
    refresh,
    render,
    scan,
    verify_evidence,
)

SLUG = "proj"


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


def _make_project(root, *, readme=True):
    """Deterministic fixture tree: pyproject + script, package, tests, README,
    plus a removable top-level module (legacy.py) for deprecation tests."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        '[project]\n'
        'name = "demo"\n'
        'description = "a demo project"\n'
        '\n'
        '[project.scripts]\n'
        'demo-cli = "demo.cli:main"\n',
        encoding="ascii",
    )
    pkg = root / "demo"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="ascii")
    (root / "legacy.py").write_text("VALUE = 1\n", encoding="ascii")
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_alpha.py").write_text(
        "def test_alpha():\n    assert True\n", encoding="ascii"
    )
    (tests / "test_beta.py").write_text(
        "def test_beta():\n    assert True\n", encoding="ascii"
    )
    if readme:
        (root / "README.md").write_text(
            "# Demo Project\n\nHello there.\n", encoding="ascii"
        )
    return root


@pytest.fixture
def proj(tmp_path):
    return _make_project(tmp_path / "proj")


@pytest.fixture
def cfg(tmp_path):
    return {"daedalus_dir": str(tmp_path / "dae")}


def _tok(token):
    """cas-N -> N as int."""
    assert token.startswith("cas-"), token
    return int(token.split("-", 1)[1])


def _dir_snapshot(d):
    if not d.exists():
        return {}
    return {p.name: p.read_bytes() for p in sorted(d.iterdir()) if p.is_file()}


def _evidence_paths(node):
    return [e["path"] for e in node["evidence"]]


def _run_cli(argv):
    """Drive birkin.cli main with argv; normalize SystemExit/None to an int."""
    from birkin import cli

    try:
        rc = cli.main(argv)
    except SystemExit as exc:
        rc = exc.code
    if rc is None:
        return 0
    return int(rc)


@pytest.fixture
def cli_cfg(tmp_path, monkeypatch):
    """Point the CLI at a tmp daedalus_dir via config.load_config."""
    import birkin.config as config

    base = dict(getattr(config, "DEFAULT_CONFIG", {}))
    base["daedalus_dir"] = str(tmp_path / "dae")
    base["daedalus_max_files"] = 2000
    monkeypatch.setattr(config, "load_config", lambda *a, **k: dict(base))
    return base


# ---------------------------------------------------------------------------
# group 1: scan
# ---------------------------------------------------------------------------


def test_scan_facts_from_fixture_tree(proj):
    nodes = scan(proj, max_files=2000)
    assert nodes, "scan returned no nodes for a populated tree"

    for n in nodes:
        assert n["owner"] == "agent"
        assert n["id"].startswith("a-")
        assert n["kind"] in ("fact", "inference", "question", "deprecated-anchor")
        assert 0.0 <= n["confidence"] <= 1.0
        for path in _evidence_paths(n):
            assert "\\" not in path, "evidence paths must be posix relative"

    facts = [n for n in nodes if n["kind"] == "fact"]
    assert facts
    for n in facts:
        assert n["confidence"] == 1.0

    # project name fact with pyproject evidence
    assert any(
        "demo" in n["text"] and "pyproject.toml" in _evidence_paths(n)
        for n in facts
    )
    # entry-point fact per [project.scripts] script
    assert any("demo-cli" in n["text"] for n in facts)
    # top-level package fact
    assert any(
        any(p.split("/")[0] == "demo" for p in _evidence_paths(n)) for n in facts
    )
    # top-level module fact (legacy.py)
    assert any("legacy.py" in _evidence_paths(n) for n in facts)
    # test suite fact: tests/ evidence, count of test_*.py is 2
    assert any(
        "2" in n["text"]
        and any(p.split("/")[0] == "tests" for p in _evidence_paths(n))
        for n in facts
    )
    # README first heading fact
    assert any(
        "Demo Project" in n["text"] and "README.md" in _evidence_paths(n)
        for n in facts
    )
    # inferences must never masquerade as facts
    for n in nodes:
        if n["kind"] == "inference":
            assert 0.6 <= n["confidence"] <= 0.8


def test_scan_missing_readme_yields_question(tmp_path):
    root = _make_project(tmp_path / "noreadme", readme=False)
    nodes = scan(root, max_files=2000)
    questions = [n for n in nodes if n["kind"] == "question"]
    assert any("README" in n["text"] for n in questions)
    q = next(n for n in questions if "README" in n["text"])
    assert q["confidence"] == 0.5


def test_scan_is_deterministic(proj):
    first = scan(proj, max_files=2000)
    second = scan(proj, max_files=2000)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# ---------------------------------------------------------------------------
# group 2: create
# ---------------------------------------------------------------------------


def test_create_writes_json_and_md(proj, cfg, tmp_path):
    doc = create(SLUG, proj, cfg=cfg)
    assert doc["slug"] == SLUG
    assert doc["token"] == "cas-0"
    dae = tmp_path / "dae"
    names = [p.name for p in dae.iterdir()]
    assert any(n.endswith(".json") for n in names)
    assert any(n.endswith(".md") for n in names)
    assert load(SLUG, cfg=cfg) is not None


def test_create_twice_raises_mentioning_refresh(proj, cfg):
    create(SLUG, proj, cfg=cfg)
    with pytest.raises(DaedalusError) as exc:
        create(SLUG, proj, cfg=cfg)
    assert "refresh" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# group 3: refresh CAS
# ---------------------------------------------------------------------------


def test_refresh_wrong_token_raises_and_leaves_state_untouched(proj, cfg, tmp_path):
    doc = create(SLUG, proj, cfg=cfg)
    before = _dir_snapshot(tmp_path / "dae")
    with pytest.raises(DaedalusError) as exc:
        refresh(SLUG, proj, expected_token="cas-999", cfg=cfg)
    assert "cas-999" in str(exc.value)
    after = _dir_snapshot(tmp_path / "dae")
    assert after == before, "failed refresh must not change persisted state"
    reloaded = load(SLUG, cfg=cfg)
    assert reloaded["token"] == doc["token"] == "cas-0"


# ---------------------------------------------------------------------------
# group 4: refresh preservation
# ---------------------------------------------------------------------------


def test_refresh_preserves_human_notes_and_deprecates_anchor(proj, cfg):
    doc = create(SLUG, proj, cfg=cfg)
    legacy = next(
        n for n in doc["nodes"] if "legacy.py" in _evidence_paths(n)
    )
    doc = add_note(
        SLUG, "keep an eye on the legacy module", refs=(legacy["id"],), cfg=cfg
    )
    humans_before = [n for n in doc["nodes"] if n["owner"] == "human"]
    assert humans_before
    snap = json.dumps(humans_before, sort_keys=True)

    (proj / "legacy.py").unlink()
    doc2 = refresh(SLUG, proj, expected_token=doc["token"], cfg=cfg)

    humans_after = [n for n in doc2["nodes"] if n["owner"] == "human"]
    assert json.dumps(humans_after, sort_keys=True) == snap

    anchor = next(n for n in doc2["nodes"] if n["id"] == legacy["id"])
    assert anchor["kind"] == "deprecated-anchor"
    assert anchor["confidence"] == 0.0
    assert anchor["text"] == legacy["text"]
    assert anchor["evidence"] == legacy["evidence"]

    assert _tok(doc2["token"]) == _tok(doc["token"]) + 1


# ---------------------------------------------------------------------------
# group 5: add_note
# ---------------------------------------------------------------------------


def test_add_note_unknown_ref_raises(proj, cfg):
    create(SLUG, proj, cfg=cfg)
    with pytest.raises(DaedalusError):
        add_note(SLUG, "bogus ref", refs=("a-9999",), cfg=cfg)


def test_add_note_valid_ref_appends_and_bumps_token(proj, cfg):
    doc = create(SLUG, proj, cfg=cfg)
    target = doc["nodes"][0]["id"]
    doc2 = add_note(SLUG, "a human observation", refs=(target,), cfg=cfg)
    note = next(n for n in doc2["nodes"] if n["id"] == "h-1")
    assert note["owner"] == "human"
    assert note["kind"] == "fact"
    assert note["confidence"] == 1.0
    assert target in note["refs"]
    assert _tok(doc2["token"]) == _tok(doc["token"]) + 1


# ---------------------------------------------------------------------------
# group 6: render
# ---------------------------------------------------------------------------


def test_render_frontmatter_and_verdict(proj, cfg):
    doc = create(SLUG, proj, cfg=cfg)
    text = render(doc)
    lines = text.splitlines()
    assert lines[0] == "---"
    assert "daedalus: %s" % SLUG in text
    assert "token: cas-0" in text

    title_idx = next(
        i for i, ln in enumerate(lines) if ln.startswith("# ")
    )
    after_title = [ln for ln in lines[title_idx + 1 :] if ln.strip()]
    assert after_title[0].startswith("VERDICT:")


def test_render_ascii_and_omits_empty_sections(proj, cfg):
    doc = create(SLUG, proj, cfg=cfg)
    text = render(doc)
    assert text.isascii()
    # fresh doc has no human notes and no deprecated anchors
    assert "## Notes (human)" not in text
    assert "## Deprecated anchors" not in text
    # facts exist, so the Facts section must be present
    assert "## Facts" in text


def test_render_evidence_footer_matches_verify_evidence(proj, cfg):
    doc = create(SLUG, proj, cfg=cfg)
    resolved, total = verify_evidence(doc, proj)
    assert total >= 1
    assert 0 <= resolved <= total
    text = render(doc)
    assert "evidence resolved: %d/%d" % (resolved, total) in text


# ---------------------------------------------------------------------------
# group 7: PROFILE shape
# ---------------------------------------------------------------------------


def test_profile_shape():
    assert PROFILE["name"] == "daedalus"
    for key in ("name", "role", "style", "deny_tools"):
        assert key in PROFILE
    assert isinstance(PROFILE["role"], str) and PROFILE["role"].isascii()
    assert isinstance(PROFILE["style"], str) and PROFILE["style"].isascii()
    deny = PROFILE["deny_tools"]
    assert deny, "deny_tools must not be empty"
    assert set(deny) <= {"run_shell", "spawn_subagent"}


# ---------------------------------------------------------------------------
# group 8: worker_hooks registration
# ---------------------------------------------------------------------------


def test_daedalus_registered_in_workers():
    assert "daedalus" in worker_hooks.WORKERS
    assert "daedalus" in worker_hooks.NO_MODEL_WORKERS


# ---------------------------------------------------------------------------
# group 9: CLI
# ---------------------------------------------------------------------------


def test_cli_create_and_show_prints_verdict(proj, cli_cfg, capsys):
    rc = _run_cli(["daedalus", "create", SLUG, "--root", str(proj)])
    assert rc == 0, capsys.readouterr().err
    capsys.readouterr()

    rc = _run_cli(["daedalus", "show", SLUG])
    out = capsys.readouterr().out
    assert rc == 0
    assert "VERDICT" in out
    assert out.isascii()


def test_cli_refresh_bad_token_exits_1(proj, cli_cfg, capsys):
    rc = _run_cli(["daedalus", "create", SLUG, "--root", str(proj)])
    assert rc == 0, capsys.readouterr().err
    capsys.readouterr()

    rc = _run_cli(
        [
            "daedalus",
            "refresh",
            SLUG,
            "--expected-token",
            "cas-999",
            "--root",
            str(proj),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert "token" in captured.err.lower()


def test_cli_profile_prints_json(cli_cfg, capsys):
    rc = _run_cli(["daedalus", "profile"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["name"] == "daedalus"
