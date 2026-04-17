"""Tests for Docker deployment configuration."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestDockerfileExists:
    """Verify Dockerfile is present and well-formed."""

    def test_dockerfile_exists(self) -> None:
        dockerfile = _PROJECT_ROOT / "Dockerfile"
        assert dockerfile.is_file(), "Dockerfile not found at project root"

    def test_dockerfile_contains_required_directives(self) -> None:
        content = (_PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
        assert "FROM" in content, "Dockerfile must have a FROM directive"
        assert "EXPOSE 8321" in content, "Dockerfile must expose port 8321"
        assert "CMD" in content, "Dockerfile must have a CMD directive"

    def test_dockerfile_installs_project(self) -> None:
        content = (_PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
        assert "pip install" in content, "Dockerfile must install the project via pip"


class TestDockerComposeValid:
    """Verify docker-compose.yml parses and has expected structure."""

    def test_docker_compose_exists(self) -> None:
        compose_file = _PROJECT_ROOT / "docker-compose.yml"
        assert compose_file.is_file(), "docker-compose.yml not found at project root"

    def test_docker_compose_parses(self) -> None:
        compose_file = _PROJECT_ROOT / "docker-compose.yml"
        data = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_docker_compose_has_birkin_service(self) -> None:
        compose_file = _PROJECT_ROOT / "docker-compose.yml"
        data = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
        assert "services" in data
        assert "birkin" in data["services"]

    def test_docker_compose_port_mapping(self) -> None:
        compose_file = _PROJECT_ROOT / "docker-compose.yml"
        data = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
        birkin = data["services"]["birkin"]
        assert "ports" in birkin
        assert "8321:8321" in birkin["ports"]

    def test_docker_compose_volumes(self) -> None:
        compose_file = _PROJECT_ROOT / "docker-compose.yml"
        data = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
        assert "volumes" in data, "Top-level volumes key expected"
        assert "birkin-data" in data["volumes"]

    def test_docker_compose_env_vars(self) -> None:
        compose_file = _PROJECT_ROOT / "docker-compose.yml"
        data = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
        env_list = data["services"]["birkin"]["environment"]
        env_str = " ".join(env_list)
        assert "BIRKIN_DB_PATH" in env_str
        assert "BIRKIN_TRACES_DIR" in env_str
        assert "BIRKIN_CONFIG_PATH" in env_str


class TestEnvVarConfigPaths:
    """Verify that config, deps, and storage modules read env vars."""

    def test_config_path_from_env(self) -> None:
        with mock.patch.dict(os.environ, {"BIRKIN_CONFIG_PATH": "/tmp/custom_config.json"}):
            import importlib

            import birkin.gateway.config as config_mod

            importlib.reload(config_mod)
            assert config_mod._CONFIG_PATH == Path("/tmp/custom_config.json")

        # Restore default
        import importlib

        import birkin.gateway.config as config_mod

        importlib.reload(config_mod)

    def test_config_path_default(self) -> None:
        env = os.environ.copy()
        env.pop("BIRKIN_CONFIG_PATH", None)
        with mock.patch.dict(os.environ, env, clear=True):
            import importlib

            import birkin.gateway.config as config_mod

            importlib.reload(config_mod)
            assert config_mod._CONFIG_PATH == Path("birkin_config.json")

    def test_db_path_from_env(self) -> None:
        from birkin.gateway.deps import reset_session_store

        reset_session_store()
        with mock.patch.dict(os.environ, {"BIRKIN_DB_PATH": ":memory:"}):
            from birkin.gateway.deps import get_session_store

            store = get_session_store()
            assert store._db_path == Path(":memory:")
        reset_session_store()

    def test_traces_dir_from_env(self) -> None:
        with mock.patch.dict(os.environ, {"BIRKIN_TRACES_DIR": "/tmp/custom_traces"}):
            import importlib

            import birkin.observability.storage as storage_mod

            importlib.reload(storage_mod)
            assert storage_mod._DEFAULT_DIR == Path("/tmp/custom_traces")

        # Restore default
        import importlib

        import birkin.observability.storage as storage_mod

        importlib.reload(storage_mod)

    def test_traces_dir_default(self) -> None:
        env = os.environ.copy()
        env.pop("BIRKIN_TRACES_DIR", None)
        with mock.patch.dict(os.environ, env, clear=True):
            import importlib

            import birkin.observability.storage as storage_mod

            importlib.reload(storage_mod)
            assert storage_mod._DEFAULT_DIR == Path("traces")
