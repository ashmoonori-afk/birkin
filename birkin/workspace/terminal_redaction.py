"""Ephemeral sensitive cmd assignment values and streaming literal masking."""

from __future__ import annotations

import re
from typing import final

from .contracts import ProtocolError, REDACTION_MARKER
from .redaction import SENSITIVE_KEYS

_NAME = re.compile(rb"[A-Za-z_][A-Za-z0-9_.-]{0,127}")
_EMBEDDED_SET = re.compile(
    rb'(?i)(?<![A-Za-z0-9_])set[ \t]+(?:/[A-Za-z]+[ \t]+)?"?([A-Za-z_][A-Za-z0-9_.-]{0,127})='
)
_UNQUOTED_SET = re.compile(
    rb"(?i)[ \t]*set[ \t]+([A-Za-z_][A-Za-z0-9_.-]{0,127})=([^\r\n]*)(?:\r\n|\n)?"
)
_QUOTED_SET = re.compile(
    rb'(?i)[ \t]*set[ \t]+"([A-Za-z_][A-Za-z0-9_.-]{0,127})=([^"%!\r\n]*)"(?:\r\n|\n)?'
)
_SEPARATORS = re.compile(r"[._-]+")
_POSITIONAL_EXPANSION_NAMES = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789*"
_DYNAMIC_OPAQUE = b"\0"
_MAX_VALUES = 64
_MAX_BYTES = 65_536
_MASK = REDACTION_MARKER.encode("ascii")


def _sensitive_name(name: bytes) -> bool:
    try:
        tokens = tuple(part for part in _SEPARATORS.split(name.decode("ascii").casefold()) if part)
    except UnicodeDecodeError:
        return False
    for family in SENSITIVE_KEYS:
        expected = tuple(_SEPARATORS.split(family.casefold()))
        width = len(expected)
        if any(tokens[index : index + width] == expected for index in range(len(tokens) - width + 1)):
            return True
    return False


def _looks_sensitive(value: bytes) -> bool:
    return any(_sensitive_name(match.group()) for match in _NAME.finditer(value))


def _contains_sensitive_set(value: bytes) -> bool:
    return any(_sensitive_name(match.group(1)) for match in _EMBEDDED_SET.finditer(value))


def _cmd_detection_view(value: bytes) -> bytes:
    normalized = bytearray()
    index = 0
    while index < len(value):
        if value[index] == ord("^") and index + 1 < len(value):
            normalized.append(value[index + 1])
            index += 2
        else:
            normalized.append(value[index])
            index += 1
    return bytes(normalized)


def _dynamic_detection_view(value: bytes) -> tuple[bytes, bool]:
    output = bytearray()
    index = 0
    found = False
    line_end = min(
        (end for end in (value.find(b"\r"), value.find(b"\n")) if end >= 0),
        default=len(value),
    )
    while index < len(value):
        byte = value[index]
        if byte in (ord("\r"), ord("\n")):
            output.append(byte)
            index += 1
            line_end = min(
                (
                    end
                    for end in (value.find(b"\r", index), value.find(b"\n", index))
                    if end >= 0
                ),
                default=len(value),
            )
            continue
        if (
            byte == ord("%")
            and index + 1 < line_end
            and value[index + 1] in _POSITIONAL_EXPANSION_NAMES
        ):
            output.extend(_DYNAMIC_OPAQUE)
            index += 2
            found = True
            continue
        if byte in (ord("%"), ord("!")):
            delimiter = bytes((byte,))
            segment_end = min(
                (
                    end
                    for end in (
                        value.find(b"&", index + 1, line_end),
                        value.find(b"|", index + 1, line_end),
                    )
                    if end >= 0
                ),
                default=line_end,
            )
            closing = value.find(delimiter, index + 1, segment_end)
            if closing > index + 1:
                output.extend(_DYNAMIC_OPAQUE)
                index = closing + 1
                found = True
                continue
        output.append(byte)
        index += 1
    return bytes(output), found


def _unsupported() -> ProtocolError:
    return ProtocolError("sensitive terminal assignment uses unsupported cmd syntax")


def _exact_sensitive_assignment(data: bytes) -> tuple[bytes, ...] | None:
    for pattern, controls in (
        (_QUOTED_SET, b'"%!\r\n'),
        (_UNQUOTED_SET, b'&|<>^%!()"\r\n'),
    ):
        match = pattern.fullmatch(data)
        if match is None or not _sensitive_name(match.group(1)):
            continue
        value = match.group(2)
        if any(byte in value for byte in controls):
            raise _unsupported()
        return (value,) if value else ()
    return None


def parse_sensitive_assignments(data: bytes) -> tuple[bytes, ...]:
    """Accept one exact sensitive assignment or reject any embedded candidate."""
    dynamic_view, has_dynamic = _dynamic_detection_view(data)
    if not has_dynamic:
        exact = _exact_sensitive_assignment(data)
        if exact is not None:
            return exact
    detection = _cmd_detection_view(dynamic_view)
    if _contains_sensitive_set(detection):
        raise _unsupported()
    lowered = detection.lstrip(b" \t").lower()
    assignment_like = b"=" in detection and (        lowered.startswith((b"export ", b"$env:", b"for "))
        or b"$env:" in lowered
    )
    if assignment_like and _looks_sensitive(detection):
        raise _unsupported()
    return ()


@final
class SensitiveValueRegistry:
    """Own bounded value-only secret bytes until terminal teardown."""

    def __init__(self, *, max_values: int = _MAX_VALUES, max_bytes: int = _MAX_BYTES) -> None:
        self._max_values = max_values
        self._max_bytes = max_bytes
        self._values: list[bytearray] = []

    @property
    def value_count(self) -> int:
        return len(self._values)

    @property
    def patterns(self) -> tuple[bytearray, ...]:
        return tuple(self._values)

    def register(self, values: tuple[bytes, ...]) -> None:
        additions: list[bytes] = []
        for value in values:
            if value and not any(value == stored for stored in (*self._values, *additions)):
                additions.append(value)
        if len(self._values) + len(additions) > self._max_values or sum(map(len, self._values)) + sum(map(len, additions)) > self._max_bytes:
            raise ProtocolError("terminal sensitive-value registry limit exceeded")
        self._values.extend(bytearray(value) for value in additions)

    def clear(self) -> None:
        for value in self._values:
            value[:] = b"\0" * len(value)
        self._values = []


@final
class StreamingLiteralMasker:
    """Mask registered exact literals across arbitrary byte chunks."""

    def __init__(self, registry: SensitiveValueRegistry) -> None:
        self._registry = registry
        self._carry = bytearray()

    def feed(self, data: bytes, *, final: bool = False) -> bytes:
        combined = bytes(self._carry) + data
        values = self._registry.patterns
        maximum = max((len(value) for value in values), default=1)
        safe_limit = len(combined) if final else max(0, len(combined) - maximum + 1)
        output = bytearray()
        index = 0
        while index < safe_limit:
            matches = tuple(value for value in values if combined.startswith(value, index))
            if matches:
                chosen = max(matches, key=len)
                output.extend(_MASK)
                index += len(chosen)
            else:
                output.append(combined[index])
                index += 1
        self._carry[:] = combined[index:]
        if final:
            while self._carry:
                tail = bytes(self._carry)
                matches = tuple(value for value in values if tail.startswith(value))
                if matches:
                    chosen = max(matches, key=len)
                    output.extend(_MASK)
                    del self._carry[: len(chosen)]
                else:
                    output.append(self._carry.pop(0))
        return bytes(output)

    def clear(self) -> None:
        self._carry[:] = b"\0" * len(self._carry)
        self._carry.clear()
