"""The Birkin distribution embeds its Mnemosyne runtime."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM_URL = "git+" + "https://github.com/ashmoonori-afk/birkin-mnemosyne"


def _build_wheel(output: Path) -> Path:
    _ = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(output)],
        cwd=ROOT,
        check=True,
    )
    wheels = tuple(output.glob("birkin-*.whl"))
    assert len(wheels) == 1
    return wheels[0]


@pytest.fixture(scope="module")
def birkin_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _build_wheel(tmp_path_factory.mktemp("birkin-wheel"))


def test_wheel_build_succeeds_without_uv_or_repository_dist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a clean-checkout PATH with Python but no uv build frontend.
    monkeypatch.setenv("PATH", str(Path(sys.executable).resolve().parent))
    assert shutil.which("uv") is None

    # When the packaging helper builds a wheel.
    wheel = _build_wheel(tmp_path)

    # Then the artifact is isolated from the repository dist directory.
    assert wheel.parent == tmp_path


def test_wheel_contains_mnemosyne_runtime_and_attribution(
    birkin_wheel: Path,
) -> None:
    # Given a wheel built from the repository.
    expected_modules = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "birkin_mnemosyne").glob("*.py")
    }

    # When its archive members are inspected.
    with zipfile.ZipFile(birkin_wheel) as archive:
        members = set(archive.namelist())

    # Then the runtime package and its upstream legal files are present.
    assert expected_modules <= members
    assert any(name.endswith("licenses/LICENSES/birkin-mnemosyne-LICENSE") for name in members)
    assert any(name.endswith("licenses/LICENSES/birkin-mnemosyne-NOTICE") for name in members)


def test_wheel_installs_and_searches_without_git(
    birkin_wheel: Path,
    tmp_path: Path,
) -> None:
    # Given a clean environment whose PATH has Python but no Git executable.
    environment = tmp_path / "venv"
    _ = subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    python_home = Path(sys.executable).resolve().parent
    env = {**os.environ, "PATH": os.pathsep.join((str(scripts), str(python_home)))}
    assert shutil.which("git", path=env["PATH"]) is None
    program = """
from pathlib import Path
from tempfile import TemporaryDirectory

import birkin
import birkin_mnemosyne
from birkin_mnemosyne import Mnemosyne

with TemporaryDirectory() as directory:
    vault = Path(directory)
    (vault / "memory.md").write_text("# Deployment memory\\nKubernetes ingress DNS", encoding="utf-8")
    index = Mnemosyne(vault)
    index.refresh()
    hits = index.search("ingress dns")
    assert hits and hits[0]["slug"] == "memory", hits
print(birkin.__version__, birkin_mnemosyne.__version__, hits[0]["slug"])
"""

    # When only the local Birkin wheel is installed and the runtime is searched.
    _ = subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", str(birkin_wheel)],
        env=env,
        check=True,
    )
    result = subprocess.run(
        [str(python), "-c", program],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    # Then both packages import and Mnemosyne returns the indexed note.
    assert result.stdout.strip().endswith("0.3.0 memory")


def test_source_metadata_has_no_upstream_direct_reference() -> None:
    # Given all machine-consumed packaging metadata.
    sources = (ROOT / "pyproject.toml", ROOT / "uv.lock")

    # When the removed direct-reference URL is searched.
    offenders = [path.name for path in sources if UPSTREAM_URL in path.read_text(encoding="utf-8")]

    # Then no source checkout remains necessary.
    assert offenders == []
