"""Tests for skill loader code validation (sandboxing)."""

from __future__ import annotations

from pathlib import Path

from birkin.skills.loader import SkillLoader


def _write_skill(tmp_path: Path, code: str) -> Path:
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "tool.py").write_text(code, encoding="utf-8")
    return skill_dir


class TestValidateSkillCode:
    def test_blocks_subprocess_import(self, tmp_path):
        d = _write_skill(tmp_path, "import subprocess\nsubprocess.run(['ls'])")
        loader = SkillLoader()
        is_safe, violations = loader.validate_skill_code(d)
        assert not is_safe
        assert any("subprocess" in v for v in violations)

    def test_blocks_eval_call(self, tmp_path):
        d = _write_skill(tmp_path, "result = eval('1+1')")
        loader = SkillLoader()
        is_safe, violations = loader.validate_skill_code(d)
        assert not is_safe
        assert any("eval" in v for v in violations)

    def test_blocks_exec_call(self, tmp_path):
        d = _write_skill(tmp_path, "exec('print(1)')")
        loader = SkillLoader()
        is_safe, violations = loader.validate_skill_code(d)
        assert not is_safe
        assert any("exec" in v for v in violations)

    def test_blocks_os_system(self, tmp_path):
        d = _write_skill(tmp_path, "import os\nos.system('whoami')")
        loader = SkillLoader()
        is_safe, violations = loader.validate_skill_code(d)
        assert not is_safe
        assert any("os.system" in v for v in violations)

    def test_clean_skill_passes(self, tmp_path):
        d = _write_skill(tmp_path, "def hello():\n    return 'hi'")
        loader = SkillLoader()
        is_safe, violations = loader.validate_skill_code(d)
        assert is_safe
        assert violations == []

    def test_syntax_error_flagged(self, tmp_path):
        d = _write_skill(tmp_path, "def broken(:\n  pass")
        loader = SkillLoader()
        is_safe, violations = loader.validate_skill_code(d)
        assert not is_safe
        assert any("syntax error" in v for v in violations)
