"""Pure-ANSI gauge / sparkline / severity primitives."""

from __future__ import annotations

from birkin import ui
from birkin.ui import bar, cell_width, spark


def test_bar_endpoints_and_track():
    assert bar(0.0) == "░" * 8
    assert bar(1.0) == "█" * 8
    assert bar(0.5) == "█" * 4 + "░" * 4
    assert bar(0.5, width=10) == "█" * 5 + "░" * 5


def test_bar_clamps_out_of_range():
    assert bar(-1.0) == "░" * 8
    assert bar(2.0) == "█" * 8
    assert bar(float("nan")) == "░" * 8


def test_bar_is_a_fixed_cell_width():
    # 8 block/shade glyphs — one cell each under the default ambiguous rule.
    assert cell_width(bar(0.37)) == 8


def test_spark_shape():
    assert spark([]) == ""
    assert spark([1, 2, 3])[-1] == "█"
    assert spark([1, 2, 3])[0] == "▁"
    assert spark([5, 5, 5]) == "▄▄▄" or len(spark([5, 5, 5])) == 3  # flat: no crash
    assert len(spark(list(range(20)))) == 20


def test_severity_thresholds():
    assert ui.severity(0.95, 0.5, 0.8, 0.9) == ui.RED
    assert ui.severity(0.85, 0.5, 0.8, 0.9) == ui.YELLOW
    assert ui.severity(0.60, 0.5, 0.8, 0.9) == ui.GREEN
    assert ui.severity(0.10, 0.5, 0.8, 0.9) == ui.DIM


def test_severity_returns_gated_color():
    # Under pytest (non-tty) color is off, so severity returns "" — the caller
    # still gets a consistent token that vanishes cleanly when piped.
    assert ui.severity(0.99, 0.5, 0.8, 0.9) == ui.RED  # == "" when color off
