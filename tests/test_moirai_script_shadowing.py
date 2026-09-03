"""A workflow name must resolve to the file the approver thought it named.

`engine.run_script` exec()s whatever `cli.resolve_script_path` returns, and the
approval inbox shows a proposal by name only. While the user scripts directory
was searched first, planting ~/.birkin/moirai/scripts/<bundled name>.py turned
"approve the workflow you already know" into "run this instead".
"""

from __future__ import annotations

import hashlib

import pytest

from birkin.moirai import cli as moirai_cli
from birkin.moirai import trigger as T
from birkin.moirai.engine import MoiraiError

_PLANTED = "meta = {'name': 'planted'}\n\n\ndef main(m):\n    return 'pwned'\n"


def _plant(stem: str):
    path = moirai_cli.scripts_dir() / f"{stem}.py"
    path.write_text(_PLANTED, encoding="utf-8")
    return path


@pytest.mark.parametrize("name", ["hard-task", "hard_task"])
def test_a_bundled_name_resolves_to_the_bundled_file(name):
    planted = _plant("hard_task")
    resolved = moirai_cli.resolve_script_path(name)
    assert resolved.parent == moirai_cli.bundled_dir()
    assert resolved != planted


def test_the_shadowing_user_script_is_refused_by_path():
    """Named directly it is not ambiguous, it is a collision worth seeing."""
    planted = _plant("hard_task")
    with pytest.raises(MoiraiError):
        moirai_cli.resolve_script_path(str(planted))


def test_an_ordinary_user_script_still_runs():
    mine = _plant("my_own_flow")
    assert moirai_cli.resolve_script_path("my_own_flow") == mine
    assert moirai_cli.resolve_script_path(str(mine)) == mine


def test_render_shows_the_file_and_hash_that_would_run():
    proposal = T.Proposal(title="비교", why="병렬이 낫다",
                          script="cross-examine", roles=(), steps=("초안",))
    path = moirai_cli.resolve_script_path("cross-examine")
    digest = hashlib.sha256(
        path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()[:12]
    rendered = proposal.render()
    assert str(path) in rendered
    assert digest in rendered


def test_render_survives_a_script_that_does_not_resolve():
    proposal = T.Proposal(title="t", why="w", script="nope", roles=(),
                          steps=("a",))
    assert "nope" in proposal.render()
