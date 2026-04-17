"""Tests for skill install/uninstall CLI and SkillLoader methods."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from birkin.skills.loader import SkillLoader

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_SKILL_MD = (
    "---\n"
    "name: my-skill\n"
    "description: A community skill\n"
    'version: "1.0.0"\n'
    "triggers:\n"
    "  - greet\n"
    "tools: []\n"
    "---\n\n"
    "## Instructions\n\nSay hello.\n"
)


@pytest.fixture
def skills_root(tmp_path: Path) -> Path:
    """Empty skills root directory."""
    root = tmp_path / "skills"
    root.mkdir()
    return root


@pytest.fixture
def loader(skills_root: Path) -> SkillLoader:
    return SkillLoader(skills_root)


# ---------------------------------------------------------------------------
# install_from_git
# ---------------------------------------------------------------------------


class TestInstallFromGit:
    def test_install_success(self, loader: SkillLoader, skills_root: Path) -> None:
        """Mock subprocess.run, create fake cloned dir with SKILL.md, verify skill loaded."""
        git_url = "https://github.com/user/my-skill.git"

        def fake_clone(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            # Simulate git clone by creating the target directory with SKILL.md
            target = Path(cmd[-1])
            target.mkdir(parents=True, exist_ok=True)
            (target / "SKILL.md").write_text(VALID_SKILL_MD, encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("birkin.skills.loader.subprocess.run", side_effect=fake_clone):
            skill = loader.install_from_git(git_url)

        assert skill.name == "my-skill"
        assert skill.spec.version == "1.0.0"
        assert (skills_root / "my-skill" / "SKILL.md").is_file()

    def test_install_strips_git_suffix(self, loader: SkillLoader, skills_root: Path) -> None:
        """URL ending with .git should have suffix stripped for directory name."""
        git_url = "https://github.com/user/cool-skill.git"

        def fake_clone(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            target = Path(cmd[-1])
            target.mkdir(parents=True, exist_ok=True)
            (target / "SKILL.md").write_text(
                VALID_SKILL_MD.replace("my-skill", "cool-skill"),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("birkin.skills.loader.subprocess.run", side_effect=fake_clone):
            skill = loader.install_from_git(git_url)

        assert skill.name == "cool-skill"
        assert (skills_root / "cool-skill").is_dir()

    def test_install_no_skill_md(self, loader: SkillLoader, skills_root: Path) -> None:
        """Cloned repo without SKILL.md should be cleaned up and raise ValueError."""
        git_url = "https://github.com/user/bad-repo.git"

        def fake_clone(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            target = Path(cmd[-1])
            target.mkdir(parents=True, exist_ok=True)
            (target / "README.md").write_text("No skill here", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("birkin.skills.loader.subprocess.run", side_effect=fake_clone):
            with pytest.raises(ValueError, match="does not contain SKILL.md"):
                loader.install_from_git(git_url)

        # Directory should be cleaned up
        assert not (skills_root / "bad-repo").exists()

    def test_install_already_exists(self, loader: SkillLoader, skills_root: Path) -> None:
        """Target dir already exists should raise ValueError without cloning."""
        existing = skills_root / "my-skill"
        existing.mkdir()

        with pytest.raises(ValueError, match="already exists"):
            loader.install_from_git("https://github.com/user/my-skill.git")

    def test_install_clone_failure(self, loader: SkillLoader) -> None:
        """git clone failure should raise RuntimeError."""
        with patch(
            "birkin.skills.loader.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "git", stderr="fatal: not found"),
        ):
            with pytest.raises(RuntimeError, match="git clone failed"):
                loader.install_from_git("https://github.com/user/no-exist.git")

    def test_install_url_without_git_suffix(self, loader: SkillLoader, skills_root: Path) -> None:
        """URL without .git suffix should also work."""
        git_url = "https://github.com/user/plain-skill"

        def fake_clone(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            target = Path(cmd[-1])
            target.mkdir(parents=True, exist_ok=True)
            (target / "SKILL.md").write_text(
                VALID_SKILL_MD.replace("my-skill", "plain-skill"),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("birkin.skills.loader.subprocess.run", side_effect=fake_clone):
            skill = loader.install_from_git(git_url)

        assert skill.name == "plain-skill"


# ---------------------------------------------------------------------------
# uninstall
# ---------------------------------------------------------------------------


class TestUninstall:
    def test_uninstall_removes_directory(self, loader: SkillLoader, skills_root: Path) -> None:
        """Create a skill dir, uninstall it, verify it's gone."""
        skill_dir = skills_root / "removable-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(VALID_SKILL_MD, encoding="utf-8")

        result = loader.uninstall("removable-skill")
        assert result is True
        assert not skill_dir.exists()

    def test_uninstall_not_found(self, loader: SkillLoader) -> None:
        """Uninstalling a non-existent skill returns False."""
        result = loader.uninstall("nonexistent-skill")
        assert result is False

    def test_uninstall_path_traversal_dotdot(self, loader: SkillLoader) -> None:
        """Path traversal with '..' should be rejected."""
        with pytest.raises(ValueError, match="path traversal"):
            loader.uninstall("../evil")

    def test_uninstall_path_traversal_slash(self, loader: SkillLoader) -> None:
        """Path traversal with '/' should be rejected."""
        with pytest.raises(ValueError, match="path traversal"):
            loader.uninstall("foo/bar")

    def test_uninstall_path_traversal_backslash(self, loader: SkillLoader) -> None:
        """Path traversal with backslash should be rejected."""
        with pytest.raises(ValueError, match="path traversal"):
            loader.uninstall("foo\\bar")

    def test_uninstall_invalid_name(self, loader: SkillLoader) -> None:
        """Names with special characters should be rejected."""
        with pytest.raises(ValueError, match="Invalid skill name"):
            loader.uninstall("skill name with spaces")


# ---------------------------------------------------------------------------
# skill list (discover)
# ---------------------------------------------------------------------------


class TestSkillList:
    def test_discover_finds_installed_skills(self, skills_root: Path) -> None:
        """Create skill dirs with SKILL.md, verify discover() finds them."""
        for name in ("alpha-skill", "beta-skill"):
            d = skills_root / name
            d.mkdir()
            (d / "SKILL.md").write_text(
                VALID_SKILL_MD.replace("my-skill", name),
                encoding="utf-8",
            )

        loader = SkillLoader(skills_root)
        skills = loader.discover()
        names = [s.name for s in skills]
        assert "alpha-skill" in names
        assert "beta-skill" in names

    def test_discover_ignores_non_skill_dirs(self, skills_root: Path) -> None:
        """Directories without SKILL.md should be skipped."""
        (skills_root / "not-a-skill").mkdir()
        (skills_root / "not-a-skill" / "README.md").write_text("nope", encoding="utf-8")

        d = skills_root / "real-skill"
        d.mkdir()
        (d / "SKILL.md").write_text(
            VALID_SKILL_MD.replace("my-skill", "real-skill"),
            encoding="utf-8",
        )

        loader = SkillLoader(skills_root)
        skills = loader.discover()
        names = [s.name for s in skills]
        assert "real-skill" in names
        assert "not-a-skill" not in names

    def test_discover_empty_dir(self, tmp_path: Path) -> None:
        """Empty or nonexistent skills dir returns empty list."""
        loader = SkillLoader(tmp_path / "nonexistent")
        assert loader.discover() == []
