"""Tests for birkin_constants module."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

import birkin_constants
from birkin_constants import get_default_birkin_root, is_container


class TestGetDefaultBirkinRoot:
    """Tests for get_default_birkin_root() — Docker/custom deployment awareness."""

    def test_no_birkin_home_returns_native(self, tmp_path, monkeypatch):
        """When BIRKIN_HOME is not set, returns ~/.birkin."""
        monkeypatch.delenv("BIRKIN_HOME", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert get_default_birkin_root() == tmp_path / ".birkin"

    def test_birkin_home_is_native(self, tmp_path, monkeypatch):
        """When BIRKIN_HOME = ~/.birkin, returns ~/.birkin."""
        native = tmp_path / ".birkin"
        native.mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("BIRKIN_HOME", str(native))
        assert get_default_birkin_root() == native

    def test_birkin_home_is_profile(self, tmp_path, monkeypatch):
        """When BIRKIN_HOME is a profile under ~/.birkin, returns ~/.birkin."""
        native = tmp_path / ".birkin"
        profile = native / "profiles" / "coder"
        profile.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("BIRKIN_HOME", str(profile))
        assert get_default_birkin_root() == native

    def test_birkin_home_is_docker(self, tmp_path, monkeypatch):
        """When BIRKIN_HOME points outside ~/.birkin (Docker), returns BIRKIN_HOME."""
        docker_home = tmp_path / "opt" / "data"
        docker_home.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("BIRKIN_HOME", str(docker_home))
        assert get_default_birkin_root() == docker_home

    def test_birkin_home_is_custom_path(self, tmp_path, monkeypatch):
        """Any BIRKIN_HOME outside ~/.birkin is treated as the root."""
        custom = tmp_path / "my-birkin-data"
        custom.mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("BIRKIN_HOME", str(custom))
        assert get_default_birkin_root() == custom

    def test_docker_profile_active(self, tmp_path, monkeypatch):
        """When a Docker profile is active (BIRKIN_HOME=<root>/profiles/<name>),
        returns the Docker root, not the profile dir."""
        docker_root = tmp_path / "opt" / "data"
        profile = docker_root / "profiles" / "coder"
        profile.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("BIRKIN_HOME", str(profile))
        assert get_default_birkin_root() == docker_root


class TestIsContainer:
    """Tests for is_container() — Docker/Podman detection."""

    def _reset_cache(self, monkeypatch):
        """Reset the cached detection result before each test."""
        monkeypatch.setattr(birkin_constants, "_container_detected", None)

    def test_detects_dockerenv(self, monkeypatch, tmp_path):
        """/.dockerenv triggers container detection."""
        self._reset_cache(monkeypatch)
        monkeypatch.setattr(os.path, "exists", lambda p: p == "/.dockerenv")
        assert is_container() is True

    def test_detects_containerenv(self, monkeypatch, tmp_path):
        """/run/.containerenv triggers container detection (Podman)."""
        self._reset_cache(monkeypatch)
        monkeypatch.setattr(os.path, "exists", lambda p: p == "/run/.containerenv")
        assert is_container() is True

    def test_detects_cgroup_docker(self, monkeypatch, tmp_path):
        """/proc/1/cgroup containing 'docker' triggers detection."""
        import builtins
        self._reset_cache(monkeypatch)
        monkeypatch.setattr(os.path, "exists", lambda p: False)
        cgroup_file = tmp_path / "cgroup"
        cgroup_file.write_text("12:memory:/docker/abc123\n")
        _real_open = builtins.open
        monkeypatch.setattr("builtins.open", lambda p, *a, **kw: _real_open(str(cgroup_file), *a, **kw) if p == "/proc/1/cgroup" else _real_open(p, *a, **kw))
        assert is_container() is True

    def test_negative_case(self, monkeypatch, tmp_path):
        """Returns False on a regular Linux host."""
        import builtins
        self._reset_cache(monkeypatch)
        monkeypatch.setattr(os.path, "exists", lambda p: False)
        cgroup_file = tmp_path / "cgroup"
        cgroup_file.write_text("12:memory:/\n")
        _real_open = builtins.open
        monkeypatch.setattr("builtins.open", lambda p, *a, **kw: _real_open(str(cgroup_file), *a, **kw) if p == "/proc/1/cgroup" else _real_open(p, *a, **kw))
        assert is_container() is False

    def test_caches_result(self, monkeypatch):
        """Second call uses cached value without re-probing."""
        monkeypatch.setattr(birkin_constants, "_container_detected", True)
        assert is_container() is True
        # Even if we make os.path.exists return False, cached value wins
        monkeypatch.setattr(os.path, "exists", lambda p: False)
        assert is_container() is True
