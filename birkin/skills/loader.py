"""Skill loader — scan directories for skills and load their tool implementations."""

from __future__ import annotations

import ast
import importlib
import inspect
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from birkin.skills.schema import Skill, parse_skill_md
from birkin.tools.base import Tool

logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")

_DEFAULT_SKILLS_DIR = Path("skills")


class SkillLoader:
    """Scans a skills directory and loads Skill definitions with their tools."""

    def __init__(self, skills_dir: Optional[Path] = None) -> None:
        self._skills_dir = skills_dir or _DEFAULT_SKILLS_DIR

    @property
    def skills_dir(self) -> Path:
        return self._skills_dir

    def discover(self) -> list[Skill]:
        """Scan the skills directory and return all valid skills.

        Each subdirectory containing a SKILL.md is treated as a skill.
        """
        if not self._skills_dir.is_dir():
            logger.info("Skills directory not found: %s", self._skills_dir)
            return []

        skills: list[Skill] = []
        for entry in sorted(self._skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name.startswith((".", "_")):
                continue

            skill = parse_skill_md(entry)
            if skill is not None:
                skills.append(skill)
                logger.info("Discovered skill: %s (%s)", skill.name, entry)

        return skills

    # Dangerous imports/calls that skills should never use
    _BLOCKED_IMPORTS = frozenset(
        {
            "subprocess",
            "ctypes",
            "socket",
            "http.server",
            "multiprocessing",
            "shutil",
        }
    )
    _BLOCKED_CALLS = frozenset(
        {
            "eval",
            "exec",
            "compile",
            "__import__",
            "os.popen",
            "os.system",
            "os.exec",
            "os.spawn",
        }
    )

    def validate_skill_code(self, skill_dir: Path) -> tuple[bool, list[str]]:
        """Static analysis of skill Python files before loading.

        Returns (is_safe, list_of_violations).
        """
        violations: list[str] = []
        for py_file in skill_dir.glob("**/*.py"):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError:
                violations.append(f"{py_file.name}: syntax error")
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in self._BLOCKED_IMPORTS:
                            violations.append(f"{py_file.name}: blocked import '{alias.name}'")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.module in self._BLOCKED_IMPORTS:
                        violations.append(f"{py_file.name}: blocked import '{node.module}'")
                if isinstance(node, ast.Call):
                    name = self._get_call_name(node)
                    if name in self._BLOCKED_CALLS:
                        violations.append(f"{py_file.name}: blocked call '{name}'")

        return (len(violations) == 0, violations)

    @staticmethod
    def _get_call_name(node: ast.Call) -> str:
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            return f"{node.func.value.id}.{node.func.attr}"
        return ""

    def install_from_git(self, git_url: str) -> Skill:
        """Clone a skill repo into skills directory and load it.

        Args:
            git_url: Git repository URL (e.g. https://github.com/user/skill-name.git).

        Returns:
            The parsed Skill from the cloned repository.

        Raises:
            ValueError: If the target directory already exists or SKILL.md is missing.
            RuntimeError: If the git clone command fails.
        """
        # Extract repo name from URL (last path segment, strip .git suffix)
        repo_name = git_url.rstrip("/").rsplit("/", maxsplit=1)[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]

        if not repo_name or not _SAFE_NAME_RE.match(repo_name):
            raise ValueError(f"Invalid repository name extracted from URL: {repo_name!r}")

        target_dir = self._skills_dir / repo_name
        if target_dir.exists():
            raise ValueError(f"Skill directory already exists: {target_dir}")

        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", git_url, str(target_dir)],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"git clone failed: {exc.stderr.strip()}") from exc
        except subprocess.TimeoutExpired as exc:
            # Clean up partial clone if timeout
            if target_dir.exists():
                shutil.rmtree(target_dir)
            raise RuntimeError("git clone timed out after 60 seconds") from exc

        # Verify SKILL.md exists in cloned directory
        if not (target_dir / "SKILL.md").is_file():
            shutil.rmtree(target_dir)
            raise ValueError(f"Cloned repository does not contain SKILL.md: {git_url}")

        # Validate code safety before loading
        is_safe, violations = self.validate_skill_code(target_dir)
        if not is_safe:
            shutil.rmtree(target_dir)
            raise ValueError(f"Skill blocked — security violations: {violations}")

        skill = parse_skill_md(target_dir)
        if skill is None:
            shutil.rmtree(target_dir)
            raise ValueError(f"Failed to parse SKILL.md from cloned repository: {git_url}")

        logger.info("Installed skill %s from %s", skill.name, git_url)
        return skill

    def uninstall(self, skill_name: str) -> bool:
        """Remove an installed skill by name.

        Args:
            skill_name: Name of the skill directory to remove.

        Returns:
            True if the skill was removed, False if it was not found.

        Raises:
            ValueError: If the name contains path traversal characters.
        """
        # Block path traversal attempts
        if ".." in skill_name or "/" in skill_name or "\\" in skill_name:
            raise ValueError(f"Invalid skill name (path traversal blocked): {skill_name!r}")

        if not _SAFE_NAME_RE.match(skill_name):
            raise ValueError(f"Invalid skill name: {skill_name!r}")

        target_dir = self._skills_dir / skill_name
        if not target_dir.is_dir():
            return False

        shutil.rmtree(target_dir)
        logger.info("Uninstalled skill: %s", skill_name)
        return True

    @staticmethod
    def load_tools(skill: Skill) -> list[Tool]:
        """Load Tool subclasses from a skill's tool.py module.

        Args:
            skill: A loaded Skill with a path to its directory.

        Returns:
            List of instantiated Tool objects from the skill.
        """
        tool_path = skill.tool_module_path
        if tool_path is None:
            return []

        try:
            spec = importlib.util.spec_from_file_location(
                f"birkin.skills.{skill.name}.tool",
                tool_path,
            )
            if not spec or not spec.loader:
                logger.warning("Could not create module spec for %s", tool_path)
                return []

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            tools: list[Tool] = []
            for name, obj in inspect.getmembers(module):
                if inspect.isclass(obj) and issubclass(obj, Tool) and obj is not Tool:
                    try:
                        instance = obj()
                        tools.append(instance)
                        logger.info("Loaded skill tool: %s/%s", skill.name, instance.spec.name)
                    except (TypeError, ValueError, RuntimeError) as exc:
                        logger.error("Failed to instantiate tool %s from %s: %s", name, tool_path, exc)

            return tools
        except (ImportError, OSError, RuntimeError) as exc:
            logger.error("Failed to load tool module from %s: %s", tool_path, exc)
            return []
