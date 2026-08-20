from birkin import config
from birkin.skills import build_manager, sync


def _write_user_skill(name: str, body: str) -> None:
    d = config.user_skills_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(body, encoding="utf-8")


def test_gating_hides_ineligible_skill():
    _write_user_skill("gated", """---
name: gated-skill
description: "needs a missing command"
prerequisites:
  commands: [no-such-cmd-zzz]
---
body
""")
    mgr = build_manager(config.load_config())
    # discovered (get works) but not eligible -> excluded from index & route
    assert mgr.get("gated-skill") is not None
    assert mgr.get("gated-skill").eligible is False
    assert "gated-skill" not in mgr.index()
    assert all(s.name != "gated-skill"
               for s in mgr.route("needs a missing command", limit=5))


def test_eligible_skill_without_prereqs():
    _write_user_skill("plain", """---
name: plain-skill
description: "no prereqs"
---
body
""")
    mgr = build_manager(config.load_config())
    assert mgr.get("plain-skill").eligible is True
    assert "plain-skill" in mgr.index()


def test_hot_reload_picks_up_new_skill():
    mgr = build_manager(config.load_config())
    assert mgr.get("freshly-added") is None
    _write_user_skill("fresh", """---
name: freshly-added
description: "added at runtime"
---
body
""")
    assert mgr.reload_if_changed(debounce=0.0) is True
    assert mgr.get("freshly-added") is not None


def test_sync_mirrors_skill_with_bundled_script(tmp_path):
    # build a fake upstream skill tree
    src = tmp_path / "upstream"
    skill_dir = src / "research" / "demo"
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        '---\nname: demo\ndescription: "d"\n---\nbody\n', encoding="utf-8")
    (skill_dir / "scripts" / "run.py").write_text("print('hi')\n", encoding="utf-8")

    synced = sync.sync_skills(src)
    assert "research/demo" in synced
    mirror = config.user_skills_dir() / "mirrors" / "research" / "demo"
    assert (mirror / "SKILL.md").is_file()
    assert (mirror / "scripts" / "run.py").is_file()          # bundled preserved
    assert "Mirrored by" in (mirror / "SKILL.md").read_text(encoding="utf-8")  # attribution

    # idempotent: second run skips the existing mirror
    assert sync.sync_skills(src) == []


def test_workspace_prompt_files_composed(tmp_path, monkeypatch, capsys):
    from birkin import prompts
    monkeypatch.chdir(tmp_path)
    soul = tmp_path / "SOUL.md"
    soul.write_text("Be kind and concise.", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Use workspace guidance.", encoding="utf-8")
    (tmp_path / "TOOLS.md").write_text("Use workspace tools.", encoding="utf-8")

    block = prompts.workspace_prompt_block()
    captured = capsys.readouterr()

    assert "## AGENTS.md\nUse workspace guidance." in block
    assert "## TOOLS.md\nUse workspace tools." in block
    assert "## SOUL.md" not in block
    assert "Be kind and concise." not in block
    assert "workspace SOUL.md is deprecated" in captured.err
    assert soul.read_text(encoding="utf-8") == "Be kind and concise."

    sysp = prompts.build_system_prompt(skills_index="- x: y")
    assert "## AGENTS.md\nUse workspace guidance." in sysp
    assert "## TOOLS.md\nUse workspace tools." in sysp
    assert "## SOUL.md" not in sysp
