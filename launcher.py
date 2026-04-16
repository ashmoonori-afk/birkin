"""Birkin one-click launcher — compiles to start.exe via PyInstaller."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# When running as PyInstaller exe, __file__ points to a temp dir.
# Use the exe's own location instead.
if getattr(sys, "frozen", False):
    SCRIPT_DIR = Path(sys.executable).resolve().parent
else:
    SCRIPT_DIR = Path(__file__).resolve().parent
VENV_DIR = SCRIPT_DIR / ".venv"
VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe"
DEPS_MARKER = VENV_DIR / ".deps_installed"
MIN_VERSION = (3, 11)
HOST = "127.0.0.1"
PORT = 8321


def find_python() -> str | None:
    """Find a suitable Python >= 3.11 on the system."""
    candidates = ["py", "python", "python3"]
    for cmd in candidates:
        try:
            result = subprocess.run(
                [cmd, "-c", "import sys; print(sys.version_info.major, sys.version_info.minor)"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split()
                major, minor = int(parts[0]), int(parts[1])
                if (major, minor) >= MIN_VERSION:
                    return cmd
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, IndexError):
            continue
    return None


def create_venv(python_cmd: str) -> None:
    """Create virtual environment if it doesn't exist."""
    if VENV_PYTHON.exists():
        return
    print("[birkin] Creating virtual environment...")
    subprocess.run([python_cmd, "-m", "venv", str(VENV_DIR)], check=True)
    print("[birkin] Virtual environment created.")


def install_deps() -> None:
    """Install dependencies if not already installed."""
    if DEPS_MARKER.exists():
        print("[birkin] Dependencies already installed.")
        return
    print("[birkin] Installing dependencies (first run, this may take a minute)...")
    subprocess.run([str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip", "--quiet"], check=True)
    result = subprocess.run([str(VENV_PYTHON), "-m", "pip", "install", "-e", ".[all]", "--quiet"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        subprocess.run([str(VENV_PYTHON), "-m", "pip", "install", "-e", ".", "--quiet"], check=True)
    DEPS_MARKER.touch()
    print("[birkin] Dependencies installed.")


def ensure_env_file() -> None:
    """Create .env from .env.example if it doesn't exist."""
    env_file = SCRIPT_DIR / ".env"
    env_example = SCRIPT_DIR / ".env.example"
    if not env_file.exists() and env_example.exists():
        import shutil
        shutil.copy2(env_example, env_file)
        print("[birkin] Created .env from .env.example")


def launch_server() -> None:
    """Launch the Birkin server."""
    url = f"http://{HOST}:{PORT}"
    print()
    print("=" * 40)
    print("  Birkin WebUI starting...")
    print(f"  {url}")
    print("=" * 40)
    print()

    subprocess.run(
        [str(VENV_PYTHON), "-m", "birkin.cli.main", "serve", "--host", HOST, "--port", str(PORT)],
        cwd=str(SCRIPT_DIR),
    )


def main() -> None:
    os.chdir(str(SCRIPT_DIR))

    print("[birkin] Birkin Launcher")
    print()

    # Step 1: Find Python
    python_cmd = find_python()
    if python_cmd is None:
        print(f"[birkin] ERROR: Python {MIN_VERSION[0]}.{MIN_VERSION[1]}+ is required.")
        print("[birkin] Download from https://www.python.org/downloads/")
        input("\nPress Enter to exit...")
        sys.exit(1)

    # Show version
    result = subprocess.run([python_cmd, "--version"], capture_output=True, text=True)
    print(f"[birkin] Using {result.stdout.strip()}")

    # Step 2: Create venv
    create_venv(python_cmd)

    # Step 3: Install deps
    install_deps()

    # Step 4: Ensure .env
    ensure_env_file()

    # Step 5: Launch
    launch_server()

    input("\nPress Enter to exit...")


if __name__ == "__main__":
    main()
