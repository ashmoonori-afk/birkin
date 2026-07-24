"""CJK-aware display width: the load-bearing primitive for every alignment."""

from __future__ import annotations

from birkin.ui import cell_width, fit, pad


def test_ascii_is_one_cell_each():
    assert cell_width("hello") == 5
    assert cell_width("") == 0


def test_hangul_is_two_cells_each():
    assert cell_width("한글") == 4
    assert cell_width("배포 알림") == 4 + 1 + 4     # space is 1


def test_mixed_and_cjk_punctuation():
    assert cell_width("k8s 배포") == 3 + 1 + 4
    assert cell_width("日本語") == 6                # Wide
    assert cell_width("ｆｕｌｌ") == 8               # Fullwidth


def test_combining_marks_are_zero_width():
    # 'e' + combining acute = one cell.
    assert cell_width("é") == 1
    assert cell_width("​") == 0               # zero-width space


def test_ambiguous_defaults_to_narrow_but_can_widen():
    # Middle dot U+00B7 is East_Asian_Width = Ambiguous.
    assert cell_width("·") == 1
    assert cell_width("·", ambiguous_wide=True) == 2
    # Box-drawing is Ambiguous too — only ASCII is guaranteed width 1.
    assert cell_width("─") == 1
    assert cell_width("─", ambiguous_wide=True) == 2


def test_fit_leaves_short_strings_alone():
    assert fit("hello", 10) == "hello"
    assert fit("한글", 10) == "한글"


def test_fit_truncates_by_display_width_without_splitting_wide():
    # "배포 알림" is 9 cells; fit to 6 -> keep "배포" (4) + "…" (1) = 5 <= 6.
    out = fit("배포 알림 시스템", 6)
    assert cell_width(out) <= 6
    assert out.endswith("…")
    assert "배" in out and "포" in out


def test_fit_never_splits_a_wide_glyph():
    # Budget of 3 with a 1-cell marker leaves 2 -> exactly one Hangul syllable.
    out = fit("가나다", 3)
    assert out == "가…"
    assert cell_width(out) <= 3


def test_pad_aligns_mixed_width_columns():
    rows = ["배포", "k8s", "한글날"]
    padded = [pad(r, 8) for r in rows]
    assert all(cell_width(p) == 8 for p in padded), \
        "every cell must be the same display width"
    assert pad("x", 4, align="right") == "   x"


def test_pad_fits_when_over_width():
    assert cell_width(pad("배포 알림 시스템", 6)) == 6
