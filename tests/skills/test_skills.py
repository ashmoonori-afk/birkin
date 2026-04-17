"""Tests for birkin.skills — schema, loader, registry, example skills."""

from __future__ import annotations

from pathlib import Path

import pytest

from birkin.skills.loader import SkillLoader
from birkin.skills.registry import SkillRegistry
from birkin.skills.schema import SkillSpec, parse_skill_md
from birkin.tools.base import ToolContext

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def skill_dir(tmp_path: Path) -> Path:
    """Create a minimal skill directory."""
    d = tmp_path / "test-skill"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\n"
        "name: test-skill\n"
        "description: A test skill\n"
        "triggers:\n"
        "  - test\n"
        "  - demo\n"
        "tools:\n"
        "  - test_tool\n"
        "---\n\n"
        "## Instructions\n\nDo the thing.\n",
        encoding="utf-8",
    )
    return d


@pytest.fixture
def skill_with_tool(tmp_path: Path) -> Path:
    """Create a skill directory with a tool.py."""
    d = tmp_path / "echo-skill"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\n"
        "name: echo-skill\n"
        "description: Echo skill for testing\n"
        "tools:\n"
        "  - skill_echo\n"
        "---\n\n"
        "Echo instructions.\n",
        encoding="utf-8",
    )
    (d / "tool.py").write_text(
        "from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolSpec, ToolParameter\n\n"
        "class SkillEchoTool(Tool):\n"
        "    @property\n"
        "    def spec(self):\n"
        "        return ToolSpec(\n"
        "            name='skill_echo',\n"
        "            description='Echo tool from skill',\n"
        "            parameters=[ToolParameter(name='msg', type='string', description='Message')],\n"
        "            toolset='skills',\n"
        "        )\n\n"
        "    async def execute(self, args, context):\n"
        "        return ToolOutput(success=True, output=args.get('msg', ''))\n",
        encoding="utf-8",
    )
    return d


@pytest.fixture
def skills_root(skill_dir: Path, skill_with_tool: Path, tmp_path: Path) -> Path:
    """Create a skills root with multiple skill subdirs."""
    root = tmp_path / "skills"
    root.mkdir()
    # Move skill dirs under root
    import shutil

    shutil.copytree(skill_dir, root / skill_dir.name)
    shutil.copytree(skill_with_tool, root / skill_with_tool.name)
    return root


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestSkillSpec:
    def test_basic(self) -> None:
        spec = SkillSpec(name="x", description="X skill")
        assert spec.name == "x"
        assert spec.version == "0.3.0"
        assert spec.triggers == []
        assert spec.enabled is True

    def test_with_triggers(self) -> None:
        spec = SkillSpec(name="y", description="Y", triggers=["hello", "world"])
        assert len(spec.triggers) == 2

    def test_frozen(self) -> None:
        spec = SkillSpec(name="z", description="Z")
        with pytest.raises(Exception):
            spec.name = "changed"


class TestParseSkillMd:
    def test_valid_skill(self, skill_dir: Path) -> None:
        skill = parse_skill_md(skill_dir)
        assert skill is not None
        assert skill.name == "test-skill"
        assert skill.spec.description == "A test skill"
        assert "test" in skill.spec.triggers
        assert "Do the thing" in skill.instructions

    def test_missing_skill_md(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty-skill"
        empty.mkdir()
        assert parse_skill_md(empty) is None

    def test_invalid_frontmatter(self, tmp_path: Path) -> None:
        d = tmp_path / "bad-skill"
        d.mkdir()
        (d / "SKILL.md").write_text("No frontmatter here", encoding="utf-8")
        assert parse_skill_md(d) is None

    def test_invalid_schema(self, tmp_path: Path) -> None:
        d = tmp_path / "bad-schema"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nfoo: bar\n---\nBody\n",
            encoding="utf-8",
        )
        assert parse_skill_md(d) is None


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------


class TestSkillLoader:
    def test_discover(self, skills_root: Path) -> None:
        loader = SkillLoader(skills_root)
        skills = loader.discover()
        names = [s.name for s in skills]
        assert "test-skill" in names
        assert "echo-skill" in names

    def test_discover_empty(self, tmp_path: Path) -> None:
        loader = SkillLoader(tmp_path / "nonexistent")
        assert loader.discover() == []

    def test_load_tools(self, skill_with_tool: Path) -> None:
        skill = parse_skill_md(skill_with_tool)
        assert skill is not None
        tools = SkillLoader.load_tools(skill)
        assert len(tools) == 1
        assert tools[0].spec.name == "skill_echo"

    def test_load_tools_no_tool_py(self, skill_dir: Path) -> None:
        skill = parse_skill_md(skill_dir)
        assert skill is not None
        tools = SkillLoader.load_tools(skill)
        assert tools == []


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestSkillRegistry:
    def test_load_all(self, skills_root: Path) -> None:
        reg = SkillRegistry(skills_dir=skills_root)
        reg.load_all()
        assert len(reg) == 2

    def test_enable_disable(self, skills_root: Path) -> None:
        reg = SkillRegistry(skills_dir=skills_root)
        reg.load_all()

        assert reg.disable("echo-skill") is True
        assert reg.get_skill("echo-skill").enabled is False

        assert reg.enable("echo-skill") is True
        assert reg.get_skill("echo-skill").enabled is True

        assert reg.disable("nonexistent") is False

    def test_get_enabled_tools(self, skills_root: Path) -> None:
        reg = SkillRegistry(skills_dir=skills_root)
        reg.load_all()

        tools = reg.get_enabled_tools()
        assert len(tools) == 1  # only echo-skill has tool.py
        assert tools[0].spec.name == "skill_echo"

        # Disable echo-skill
        reg.disable("echo-skill")
        assert len(reg.get_enabled_tools()) == 0

    def test_match_triggers(self, skills_root: Path) -> None:
        reg = SkillRegistry(skills_dir=skills_root)
        reg.load_all()

        matches = reg.match_triggers("can you test this?")
        assert any(m.name == "test-skill" for m in matches)

        matches = reg.match_triggers("unrelated query")
        assert len(matches) == 0

    def test_to_summary(self, skills_root: Path) -> None:
        reg = SkillRegistry(skills_dir=skills_root)
        reg.load_all()

        summaries = reg.to_summary()
        assert len(summaries) == 2
        names = [s["name"] for s in summaries]
        assert "test-skill" in names
        assert "echo-skill" in names


# ---------------------------------------------------------------------------
# Example skills (integration)
# ---------------------------------------------------------------------------


class TestExampleSkills:
    """Test the bundled example skills in skills/ directory."""

    def test_code_review_discovery(self) -> None:
        reg = SkillRegistry(skills_dir=Path("skills"))
        reg.load_all()
        skill = reg.get_skill("code-review")
        if skill is None:
            pytest.skip("skills/ directory not available in test environment")
        assert skill.spec.description is not None
        assert "review" in skill.spec.triggers[0].lower()

    def test_web_summarizer_discovery(self) -> None:
        reg = SkillRegistry(skills_dir=Path("skills"))
        reg.load_all()
        skill = reg.get_skill("web-summarizer")
        if skill is None:
            pytest.skip("skills/ directory not available in test environment")
        assert "summarize" in skill.spec.triggers

    @pytest.mark.asyncio
    async def test_review_code_tool(self) -> None:
        reg = SkillRegistry(skills_dir=Path("skills"))
        reg.load_all()
        tools = reg.get_skill_tools("code-review")
        if not tools:
            pytest.skip("code-review skill tools not available")

        tool = tools[0]
        result = await tool.execute(
            {"code": "password='secret123'\neval(user_input)"},
            ToolContext(),
        )
        assert result.success is True
        assert "CRITICAL" in result.output or "HIGH" in result.output

    @pytest.mark.asyncio
    async def test_summarize_text_tool(self) -> None:
        reg = SkillRegistry(skills_dir=Path("skills"))
        reg.load_all()
        tools = reg.get_skill_tools("web-summarizer")
        if not tools:
            pytest.skip("web-summarizer skill tools not available")

        tool = tools[0]
        text = (
            "Python is a programming language. It is widely used for web development. "
            "Python has excellent library support. Many data scientists prefer Python. "
            "The language is known for its readable syntax and ease of learning."
        )
        result = await tool.execute({"text": text}, ToolContext())
        assert result.success is True
        assert "Summary" in result.output
