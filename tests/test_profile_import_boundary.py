from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path


def test_only_profile_review_imports_birkin_mnemosyne_profiles():
    root = Path(__file__).resolve().parents[1] / "birkin"
    offenders = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            mod = ""
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name.startswith("birkin_mnemosyne"):
                    offenders.append((path.name, name))
    assert offenders == [("profile_review.py", "birkin_mnemosyne")]


def test_importing_profile_stack_does_not_load_mnemosyne_index_module():
    repo = Path(__file__).resolve().parents[1]
    upstream = repo.parent / "mnemosyne"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(repo), str(upstream), env.get("PYTHONPATH", "")])
    code = (
        "import sys\n"
        "import birkin.profile_actions\n"
        "import birkin.profile_review\n"
        "assert 'birkin_mnemosyne.mnemosyne' not in sys.modules, sys.modules.keys()\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, env=env)
