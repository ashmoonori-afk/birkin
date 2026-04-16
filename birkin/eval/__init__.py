"""Birkin evaluation framework — compare providers and detect regressions."""

from birkin.eval.dataset import EvalCase, EvalDataset
from birkin.eval.runner import EvalReport, EvalResult, EvalRunner
from birkin.eval.storage import EvalStorage

__all__ = [
    "EvalCase",
    "EvalDataset",
    "EvalReport",
    "EvalResult",
    "EvalRunner",
    "EvalStorage",
]
