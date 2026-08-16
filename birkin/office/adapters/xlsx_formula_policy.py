"""Closed, non-evaluating grammar for safe XLSX formula mutations."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SAFE_FUNCTIONS = frozenset(
    {
        "ABS",
        "AND",
        "AVERAGE",
        "CEILING",
        "CONCAT",
        "COUNT",
        "COUNTA",
        "EXACT",
        "FLOOR",
        "IF",
        "LEFT",
        "LEN",
        "LOWER",
        "MAX",
        "MID",
        "MIN",
        "MOD",
        "NOT",
        "OR",
        "POWER",
        "PRODUCT",
        "RIGHT",
        "ROUND",
        "ROUNDDOWN",
        "ROUNDUP",
        "SQRT",
        "SUM",
        "TRIM",
        "UPPER",
    }
)
_TOKEN = re.compile(
    r"""(?P<space>\s+)
    |(?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)
    |(?P<string>"(?:[^"]|"")*")
    |(?P<cell>\$?[A-Za-z]{1,3}\$?[1-9][0-9]*)
    |(?P<identifier>[A-Za-z_][A-Za-z0-9_.]*)
    |(?P<operator><>|<=|>=|[+\-*/^&=<>%(),:])""",
    re.VERBOSE,
)
_BINARY_PRECEDENCE = {
    ":": 70,
    "^": 60,
    "*": 50,
    "/": 50,
    "+": 40,
    "-": 40,
    "&": 30,
    "=": 20,
    "<>": 20,
    "<": 20,
    ">": 20,
    "<=": 20,
    ">=": 20,
}


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str


def _tokens(formula: str) -> list[_Token] | None:
    result: list[_Token] = []
    position = 0
    while position < len(formula):
        match = _TOKEN.match(formula, position)
        if match is None:
            return None
        position = match.end()
        kind = match.lastgroup
        if kind is not None and kind != "space":
            result.append(_Token(kind, match.group()))
    result.append(_Token("end", ""))
    return result


class _Parser:
    def __init__(self, tokens: list[_Token]) -> None:
        self.tokens: list[_Token] = tokens
        self.index: int = 0

    @property
    def current(self) -> _Token:
        return self.tokens[self.index]

    def _take(self, value: str | None = None) -> _Token:
        token = self.current
        if value is not None and token.value != value:
            raise ValueError
        self.index += 1
        return token

    def parse(self) -> None:
        self._expression(0)
        if self.current.kind != "end":
            raise ValueError

    def _expression(self, minimum: int) -> None:
        if self.current.value in {"+", "-"}:
            _ = self._take()
            self._expression(65)
        else:
            self._primary()
        while self.current.value == "%":
            _ = self._take("%")
        while (precedence := _BINARY_PRECEDENCE.get(self.current.value, -1)) >= minimum:
            operator = self._take().value
            self._expression(precedence if operator == "^" else precedence + 1)

    def _primary(self) -> None:
        token = self.current
        if token.kind in {"number", "string", "cell"}:
            _ = self._take()
            return
        if token.value == "(":
            _ = self._take("(")
            self._expression(0)
            _ = self._take(")")
            return
        if token.kind != "identifier":
            raise ValueError
        name = self._take().value.upper()
        if name in {"TRUE", "FALSE"} and self.current.value != "(":
            return
        if name not in _SAFE_FUNCTIONS:
            raise ValueError
        _ = self._take("(")
        if self.current.value == ")":
            raise ValueError
        self._expression(0)
        while self.current.value == ",":
            _ = self._take(",")
            self._expression(0)
        _ = self._take(")")


def is_safe_formula(formula: str) -> bool:
    """Return whether formula belongs to the closed mutation-safe subset."""
    tokens = _tokens(formula)
    if tokens is None:
        return False
    try:
        _Parser(tokens).parse()
    except (ValueError, RecursionError):
        return False
    return True
