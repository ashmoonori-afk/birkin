from __future__ import annotations

from pathlib import Path

import pytest

from birkin.rolefiles import (
    PROFILE_ORDER,
    ProfileBudgetExceeded,
    ProfileEdit,
    ProfileStore,
)


def store(tmp_path: Path, **limits: int) -> ProfileStore:
    return ProfileStore(tmp_path, limits)


def test_bootstrap_creates_exactly_five_profile_files(tmp_path: Path) -> None:
    s = store(tmp_path)
    s.bootstrap()

    files = sorted(path.name for path in (tmp_path / "profile").glob("*.md"))
    assert files == [f"{name}.md" for name in sorted(PROFILE_ORDER)]
    for name in PROFILE_ORDER:
        text = (tmp_path / "profile" / f"{name}.md").read_text(encoding="utf-8")
        assert text.startswith("---\ndescription: ")
        assert "---\n# " in text
        assert text.endswith("## Guidance\n")


def test_snapshot_missing_profile_directory_is_empty_and_creates_nothing(tmp_path: Path) -> None:
    s = store(tmp_path)

    snapshot = s.snapshot()

    assert snapshot.documents == {}
    assert not (tmp_path / "profile").exists()


def test_add_replace_remove_and_duplicate_noop(tmp_path: Path) -> None:
    s = store(tmp_path)
    first = s.apply(ProfileEdit("preferences", "add", content="Use concise replies"))
    second = s.apply(ProfileEdit("preferences", "add", content="Use concise replies"))
    assert second.documents["preferences"].entries == ("Use concise replies",)
    assert second.revision == first.revision

    replaced = s.apply(ProfileEdit(
        "preferences", "replace", old_text="Use concise replies", content="Use direct replies"
    ))
    assert replaced.documents["preferences"].entries == ("Use direct replies",)

    removed = s.apply(ProfileEdit("preferences", "remove", old_text="Use direct replies"))
    assert removed.documents["preferences"].entries == ()


def test_over_budget_add_is_structured_and_preserves_bytes(tmp_path: Path) -> None:
    s = store(tmp_path, preferences=18)
    s.apply(ProfileEdit("preferences", "add", content="short"))
    path = tmp_path / "profile" / "preferences.md"
    before = path.read_bytes()
    revision = s.snapshot().documents["preferences"].revision

    with pytest.raises(ProfileBudgetExceeded) as excinfo:
        s.apply(ProfileEdit("preferences", "add", content="too many chars"))

    error = excinfo.value
    assert error.used == len("- short\n")
    assert error.limit == 18
    assert error.required_reduction > 0
    assert error.revision == revision
    assert error.entries == ((1, "short"),)
    assert path.read_bytes() == before


def test_lowered_limit_allows_replace_remove_but_refuses_add(tmp_path: Path) -> None:
    s = store(tmp_path, preferences=100)
    s.apply(ProfileEdit("preferences", "add", content="a fairly long existing preference"))
    low = store(tmp_path, preferences=5)

    with pytest.raises(ProfileBudgetExceeded):
        low.apply(ProfileEdit("preferences", "add", content="new"))

    replaced = low.apply(ProfileEdit(
        "preferences", "replace",
        old_text="a fairly long existing preference",
        content="still above limit",
    ))
    assert replaced.documents["preferences"].entries == ("still above limit",)
    removed = low.apply(ProfileEdit("preferences", "remove", old_text="still above limit"))
    assert removed.documents["preferences"].entries == ()


def test_identical_content_yields_identical_revision(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    sa = store(a)
    sb = store(b)
    edit = ProfileEdit("workflow", "add", content="Run tests once before reporting")
    ra = sa.apply(edit).revision
    rb = sb.apply(edit).revision
    assert ra == rb
    assert sa.snapshot().documents["workflow"].revision == sb.snapshot().documents["workflow"].revision
