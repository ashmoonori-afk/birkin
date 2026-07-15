from pathlib import Path

from birkin import config
from birkin.skills import build_manager, frontmatter
from birkin.skills.manager import SkillManager, _write_skill


def _mgr():
    return build_manager(config.load_config())


def test_bundled_skills_discovered():
    mgr = _mgr()
    assert len(mgr.skills) >= 10  # the repo ships a sizable catalog
    assert "web-research" in mgr.skills


def test_index_non_empty():
    assert "web-research" in _mgr().index()


def test_get_case_insensitive():
    mgr = _mgr()
    assert mgr.get("WEB-RESEARCH") is not None


def test_route_picks_relevant_skill():
    mgr = _mgr()
    routed = mgr.route("find recent arxiv papers on transformer attention", limit=3)
    names = [s.name for s in routed]
    assert "arxiv" in names


def test_route_empty_query_returns_nothing():
    assert _mgr().route("", limit=3) == []


def test_route_keeps_two_character_korean_terms(tmp_path):
    skill_dir = tmp_path / "paper-research"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: paper-research\ndescription: 논문 조사\n---\n\n절차\n",
        encoding="utf-8",
    )
    mgr = SkillManager([(tmp_path, "user")])
    assert [skill.name for skill in mgr.route("논문 찾아줘")] == [
        "paper-research"
    ]


def test_route_prefers_metadata_match_over_generic_body_matches(tmp_path):
    target = tmp_path / "invoice-helper"
    target.mkdir()
    (target / "SKILL.md").write_text(
        "---\nname: invoice-helper\ndescription: reconcile invoices\n---\n\nbody\n",
        encoding="utf-8",
    )
    for index in range(4):
        generic = tmp_path / f"generic-{index}"
        generic.mkdir()
        (generic / "SKILL.md").write_text(
            f"---\nname: generic-{index}\ndescription: generic helper\n---\n\n"
            "please carefully inspect reconcile the records and report details\n",
            encoding="utf-8",
        )
    mgr = SkillManager([(tmp_path, "user")])
    routed = mgr.route(
        "please carefully reconcile invoices and report the details", limit=3)
    assert "invoice-helper" in [skill.name for skill in routed]


def test_route_prefers_specific_metadata_term_in_verbose_query(tmp_path):
    for index in range(4):
        generic = tmp_path / f"a-generic-{index}"
        generic.mkdir()
        (generic / "SKILL.md").write_text(
            f"---\nname: a-generic-{index}\n"
            "description: please inspect helper\n---\n\nbody\n",
            encoding="utf-8",
        )
    target = tmp_path / "z-sparkle"
    target.mkdir()
    (target / "SKILL.md").write_text(
        "---\nname: z-sparkle\ndescription: sparklewidget helper\n---\n\n"
        "SPECIFIC-SKILL-BODY\n",
        encoding="utf-8",
    )
    mgr = SkillManager([(tmp_path, "user")])
    routed = mgr.route("Please inspect SparkleWidget now", limit=3)
    assert routed[0].name == "z-sparkle"


def test_route_does_not_fill_metadata_results_with_generic_body_matches(tmp_path):
    target = tmp_path / "specific"
    target.mkdir()
    (target / "SKILL.md").write_text(
        "---\nname: specific\ndescription: qazalpha helper\n---\n\nbody\n",
        encoding="utf-8",
    )
    generic = tmp_path / "generic"
    generic.mkdir()
    (generic / "SKILL.md").write_text(
        "---\nname: generic\ndescription: unrelated helper\n---\n\n"
        "Use this procedure again after an updated request.\n",
        encoding="utf-8",
    )
    mgr = SkillManager([(tmp_path, "user")])
    assert [skill.name for skill in mgr.route("qazalpha again updated")] == [
        "specific"
    ]


def test_route_does_not_substring_match_ascii_tokens(tmp_path):
    target = tmp_path / "sparkle"
    target.mkdir()
    (target / "SKILL.md").write_text(
        "---\nname: sparkle\ndescription: sparklewidget helper\n---\n\nbody\n",
        encoding="utf-8",
    )
    unrelated = tmp_path / "knowledge"
    unrelated.mkdir()
    (unrelated / "SKILL.md").write_text(
        "---\nname: knowledge\ndescription: knowledge helper\n---\n\nbody\n",
        encoding="utf-8",
    )
    mgr = SkillManager([(tmp_path, "user")])
    assert [skill.name for skill in mgr.route("sparklewidget now")] == [
        "sparkle"
    ]


def test_route_matches_unicode_terms(tmp_path):
    skill_dir = tmp_path / "korean-blog"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: korean-blog\ndescription: 블로그 조사 자동화\n---\n\n"
        "한국어 블로그 조사 절차\n",
        encoding="utf-8",
    )
    mgr = SkillManager([(tmp_path, "user")])
    assert [skill.name for skill in mgr.route("블로그 조사해줘")] == [
        "korean-blog"
    ]


def test_top_level_platforms_gate_skill(tmp_path, monkeypatch):
    skill_dir = tmp_path / "linux-only"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: linux-only\ndescription: linux helper\n"
        "platforms: [linux]\n---\n\nbody\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("birkin.skills.loader._current_platform", lambda: "windows")
    skill = SkillManager([(tmp_path, "user")]).get("linux-only")
    assert skill is not None and skill.eligible is False


def test_bom_prefixed_platform_gate_still_applies(tmp_path, monkeypatch):
    skill_dir = tmp_path / "bom-linux-only"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "\ufeff---\nname: bom-linux-only\ndescription: linux helper\n"
        "platforms: [linux]\n---\n\nbody\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("birkin.skills.loader._current_platform", lambda: "windows")
    skill = SkillManager([(tmp_path, "user")]).get("bom-linux-only")
    assert skill is not None and skill.eligible is False


def test_render_skill_includes_bundled_script():
    mgr = _mgr()
    arxiv = mgr.get("arxiv")
    assert arxiv is not None
    rendered = mgr.render_skill(arxiv)
    assert "Bundled files" in rendered
    assert "scripts/search_arxiv.py" in rendered


def test_render_skill_plain_when_no_bundle():
    mgr = _mgr()
    sk = mgr.get("web-research")
    rendered = mgr.render_skill(sk)
    assert rendered.startswith("# Skill: web-research")
    assert str(sk.directory) in rendered


def test_render_skill_resolves_relative_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    skill_dir = tmp_path / "relative-skills" / "helper"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: helper\ndescription: helper skill\n---\n\nbody\n",
        encoding="utf-8",
    )
    mgr = SkillManager([(Path("relative-skills"), "user")])
    skill = mgr.get("helper")
    assert skill is not None
    assert f"Skill directory: `{skill_dir}`" in mgr.render_skill(skill)


def test_write_skill_serializes_quotes_newlines_and_tags():
    description = 'Use "quoted": text\nwithout injecting metadata'
    tags = ["alpha, beta", "scope: research", "bracket]tag", 'quote"tag',
            "#hash"]
    path = _write_skill("quoted", description, "body", tags)
    meta, _body = frontmatter.extract_meta(path.read_text(encoding="utf-8"))
    assert meta["description"] == description
    assert meta["metadata"]["birkin"]["tags"] == tags
    assert "injected" not in meta


def test_skill_frontmatter_accepts_utf8_bom():
    meta, body = frontmatter.extract_meta(
        "\ufeff---\nname: bom-skill\ndescription: windows file\n---\n\nbody\n")
    assert meta["name"] == "bom-skill"
    assert body.strip() == "body"


def test_create_proposal_refuses_existing_canonical_slug(tmp_path, monkeypatch):
    import pytest
    from birkin.skills.manager import SkillProposalError, apply_skill_proposal

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    _write_skill("existing-skill", "original", "ORIGINAL", [])
    with pytest.raises(SkillProposalError, match="already exists"):
        apply_skill_proposal({
            "action": "create", "name": "Existing Skill",
            "description": "replacement", "body": "REPLACED",
        })


def test_create_proposal_refuses_directory_slug_collision(tmp_path, monkeypatch):
    import pytest
    from birkin.skills.manager import SkillProposalError, apply_skill_proposal

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    skill_dir = config.user_skills_dir() / "same-skill"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        "---\nname: Friendly Name\ndescription: original\n---\n\nORIGINAL\n",
        encoding="utf-8",
    )
    with pytest.raises(SkillProposalError, match="already exists"):
        apply_skill_proposal({
            "action": "create", "name": "same skill",
            "description": "replacement", "body": "REPLACED",
        })
    assert "ORIGINAL" in skill_path.read_text(encoding="utf-8")


def test_concurrent_same_slug_create_has_one_winner(tmp_path, monkeypatch):
    import threading
    from birkin.skills.manager import SkillProposalError, apply_skill_proposal

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    gate = threading.Barrier(3)
    outcomes = []

    def create(body):
        gate.wait()
        try:
            outcomes.append(apply_skill_proposal({
                "action": "create", "name": "same skill",
                "description": "helper", "body": body,
            }))
        except SkillProposalError as exc:
            outcomes.append(str(exc))

    workers = [threading.Thread(target=create, args=(body,))
               for body in ("FIRST", "SECOND")]
    for worker in workers:
        worker.start()
    gate.wait()
    for worker in workers:
        worker.join()

    assert sum(outcome.startswith("Created skill") for outcome in outcomes) == 1
    assert sum("already exists" in outcome for outcome in outcomes) == 1


def test_concurrent_bundled_skill_improvements_keep_both_notes(
        tmp_path, monkeypatch):
    import threading
    from birkin.skills.manager import apply_skill_proposal

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    gate = threading.Barrier(3)

    def improve(note):
        gate.wait()
        apply_skill_proposal({
            "action": "improve", "target": "web-research",
            "addition": note,
        })

    workers = [threading.Thread(target=improve, args=(note,))
               for note in ("FIRST-CONCURRENT-NOTE", "SECOND-CONCURRENT-NOTE")]
    for worker in workers:
        worker.start()
    gate.wait()
    for worker in workers:
        worker.join()

    text = (config.user_skills_dir() / "web-research" / "SKILL.md").read_text(
        encoding="utf-8")
    assert "FIRST-CONCURRENT-NOTE" in text
    assert "SECOND-CONCURRENT-NOTE" in text
