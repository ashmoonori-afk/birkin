from __future__ import annotations

from unittest.mock import patch

import pytest

from birkin.workspace.contracts import ProtocolError
from birkin.workspace.terminal_redaction import (
    SensitiveValueRegistry,
    StreamingLiteralMasker,
    parse_sensitive_assignments,
)


def _caret_variants(value: bytes) -> tuple[bytes, ...]:
    return tuple(
        value[:index] + b"^" + value[index:] for index in range(len(value) + 1)
    )


CARET_COMMANDS = tuple(
    variant + b" PASSWORD=secret\r\n"
    for variant in _caret_variants(b"set")
) + tuple(
    b"set " + variant + b"=secret\r\n"
    for key in (b"PASSWORD", b"TOKEN", b"SECRET")
    for variant in _caret_variants(key)
)
POSITIONAL_NAMES = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789*"
_NEXT_EXPANSIONS = (b"%PATH%", b"!NEXT!", b"%1")
_STATIC_ASSIGNMENT = b"set PASSWORD=STATIC_SECRET"
POSITIONAL_MIX_COMMANDS = tuple(
    b" & ".join(parts) + b"\r\n"
    for name in POSITIONAL_NAMES
    for following in _NEXT_EXPANSIONS
    for parts in (
        (_STATIC_ASSIGNMENT, b"%" + bytes((name,)) + following),
        (b"%" + bytes((name,)), _STATIC_ASSIGNMENT, following),
        (b"%" + bytes((name,)) + following, _STATIC_ASSIGNMENT),
    )
)
DYNAMIC_ONLY_COMMANDS = (
    b"echo %PATH%\r\n",
    b"%x%PASSWORD=DYNAMIC_VISIBLE\r\n",
    b"s%x%PASSWORD=DYNAMIC_VISIBLE\r\n",
    b"!x!TOKEN=DYNAMIC_VISIBLE\r\n",
    b"set %x%secret\r\n",
    b"s%xet PASSWORD=DYNAMIC_VISIBLE\r\n",
    b"set PASS%xWORD=DYNAMIC_VISIBLE\r\n",
    b"se!x!t TOKEN=DYNAMIC_VISIBLE\r\n",
    b"echo %0%PATH% !NEXT! %*\r\n",
    b"echo %_unclosed !unclosed\r\n",
)
@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (b"set PASSWORD=alpha\r\n", (b"alpha",)),
        (b"  SeT my_db_PaSsWoRd=bravo charlie\n", (b"bravo charlie",)),
        (b'set "API-KEY=delta & echo"\r\n', (b"delta & echo",)),
        (b"set PASSWORD=\r\n", ()),
        (b"set MONKEY=VISIBLE\r\n", ()),
        (b"set arbitrary=VISIBLE\r\n", ()),
        (b"echo prefix & set arbitrary=VISIBLE\r\n", ()),
    ],
)
def test_sensitive_cmd_assignments_parse_only_supported_grammar(
    command: bytes,
    expected: tuple[bytes, ...],
) -> None:
    # Given a complete cmd input containing supported assignments
    # When the boundary parser examines it
    values = parse_sensitive_assignments(command)
    # Then only exact sensitive-family values are returned
    assert values == expected


@pytest.mark.parametrize(
    "command",
    [
        b"set PASSWORD=secret&echo chained\r\n",
        b"set PASSWORD=secret^value\r\n",
        b"set PASSWORD=(secret)\r\n",
        b'set PASSWORD="secret"\r\n',
        b'set "PASSWORD=secret" trailing\r\n',
        b"set /p PASSWORD=secret\r\n",
        b"set PASSWORD=secret | more\r\n",
        b"export PASSWORD=secret\n",
        b"$env:PASSWORD=secret\r\n",
        b'powershell -c "$env:PASSWORD=secret"\r\n',
        b"for PASSWORD=secret\r\n",
        b"set AUTHORIZATION=echo-token\r\nset cookie=second\r\n",
        b"echo prefix & set PASSWORD=secret\r\n",
        b"echo prefix && set PASSWORD=secret\r\n",
        b"echo prefix || set PASSWORD=secret\r\n",
        b"echo prefix\r\nset PASSWORD=secret\r\n",
        b"cmd /c set PASSWORD=secret\r\n",
        b"call set PASSWORD=secret\r\n",
        b'echo prefix & set "PASSWORD=secret"\r\n',
        b'CmD /c SeT "MY_DB_PASSWORD=secret"\r\n',
        b"set harmless=ok & set PASSWORD=secret\r\n",
        b"set harmless=ok && set TOKEN=secret && set other=ok\r\n",
        b"set PASSWORD=secret & set harmless=ok\r\n",
        b'set "harmless=ok" || set "MY_DB_PASSWORD=secret"\r\n',
        b"set one=ok\r\nset two=ok\r\ncall set AUTHORIZATION=secret\r\n",
    ],
)
def test_sensitive_cmd_assignments_fail_closed_before_process_write(
    command: bytes,
) -> None:
    # Given sensitive cmd syntax outside the supported literal grammar
    # When it crosses the input boundary, Then it is rejected
    with pytest.raises(ProtocolError, match="sensitive terminal assignment"):
        _ = parse_sensitive_assignments(command)


@pytest.mark.parametrize(
    "command",
    CARET_COMMANDS
    + (
        b's^et "PASS^WORD=secret"\r\n',
        b"  Se^T\tPaSs^WoRd=secret\r\n",
        b"echo ok && se^t TOKEN=secret\r\n",
    ),
)
def test_obfuscated_sensitive_assignment_is_rejected(command: bytes) -> None:
    # Given a caret-escaped or dynamically constructed cmd assignment
    # When detection canonicalizes without evaluating it, Then it fails closed
    with pytest.raises(ProtocolError, match="sensitive terminal assignment"):
        _ = parse_sensitive_assignments(command)


@pytest.mark.parametrize("command", DYNAMIC_ONLY_COMMANDS)
def test_dynamic_expansion_input_is_admitted_without_guessed_values(
    command: bytes,
) -> None:
    assert parse_sensitive_assignments(command) == ()


@pytest.mark.parametrize(
    "command",
    [
        b"echo %PATH% & set PASSWORD=STATIC_SECRET\r\n",
        b"set PASSWORD=STATIC_SECRET & echo %PATH%\r\n",
        b"echo %LEFT% && set TOKEN=STATIC_SECRET && echo !RIGHT!\r\n",
        b"echo !LEFT!\r\nse^t SECRET=STATIC_SECRET\r\n",
        b"se^t PASSWORD=STATIC_SECRET & echo %PATH%\r\n",
        b"echo %LEFT% || s^et TOKEN=STATIC_SECRET || echo %RIGHT%\r\n",
    ],
)
def test_dynamic_segments_do_not_bypass_static_sensitive_scan(command: bytes) -> None:
    with pytest.raises(ProtocolError, match="sensitive terminal assignment"):
        _ = parse_sensitive_assignments(command)


def test_positional_expansion_consumes_exactly_two_source_bytes() -> None:
    detection_views: list[bytes] = []

    def capture(value: bytes) -> bool:
        detection_views.append(value)
        return False

    with patch(
        "birkin.workspace.terminal_redaction._contains_sensitive_set",
        side_effect=capture,
    ):
        for command in POSITIONAL_MIX_COMMANDS:
            assert parse_sensitive_assignments(command) == ()
    assert len(detection_views) == len(POSITIONAL_MIX_COMMANDS)
    assert all(_STATIC_ASSIGNMENT in view for view in detection_views)


@pytest.mark.parametrize(
    "command",
    [
        b"echo %0 & set PASSWORD=STATIC_SECRET & echo %PATH%\r\n",
        b"echo %x & se^t TOKEN=STATIC_SECRET & echo !NEXT!\r\n",
        b"echo %*%PATH% & set SECRET=STATIC_SECRET\r\n",
        b"echo %_unclosed & set PASSWORD=STATIC_SECRET\r\n",
        b"echo !unclosed & se^t TOKEN=STATIC_SECRET\r\n",
        b"echo %0%PATH%!NEXT!%1 & set PASSWORD=STATIC_SECRET\r\n",
    ],
)
def test_adjacent_or_malformed_expansions_do_not_swallow_static_text(
    command: bytes,
) -> None:
    with pytest.raises(ProtocolError, match="sensitive terminal assignment"):
        _ = parse_sensitive_assignments(command)


def test_registry_is_bounded_deduplicated_and_zeroized() -> None:
    # Given a registry at its exact value count limit
    registry = SensitiveValueRegistry(max_values=2, max_bytes=8)
    registry.register((b"one", b"one", b"two"))
    # When another distinct value exceeds the bound
    with pytest.raises(ProtocolError, match="registry"):
        registry.register((b"three",))
    # Then duplicates did not consume capacity and teardown overwrites storage
    owned = registry.patterns
    registry.clear()
    assert owned and all(not any(value) for value in owned)
    assert registry.value_count == 0


@pytest.mark.parametrize("split", range(1, 10))
def test_streaming_masker_masks_every_occurrence_at_every_chunk_boundary(
    split: int,
) -> None:
    # Given a registered literal repeated around VT, CRLF, and CJK
    registry = SensitiveValueRegistry()
    registry.register((b"topsecret",))
    source = b"\x1b[31mtopsecret\x1b[0m\r\n\xed\x95\x9c-topsecret-prompt"
    masker = StreamingLiteralMasker(registry)
    # When the stream is split at each boundary
    output = masker.feed(source[:split]) + masker.feed(source[split:], final=True)
    # Then every occurrence is masked and unrelated bytes remain exact
    assert output == b"\x1b[31m[REDACTED]\x1b[0m\r\n\xed\x95\x9c-[REDACTED]-prompt"


@pytest.mark.parametrize(
    ("values", "source", "expected"),
    [
        ((b"abc", b"abcdef"), b"zabcdefabc", b"z[REDACTED][REDACTED]"),
        ((b"secret", b"secret"), b"secret-secret", b"[REDACTED]-[REDACTED]"),
        ((b"aba", b"bab"), b"ababa", b"[REDACTED]ba"),
        ((b"VISIBLE",), b"set arbitrary=VISIBLE\r\nVISIBLE", b"set arbitrary=[REDACTED]\r\n[REDACTED]"),
    ],
)
def test_streaming_masker_uses_leftmost_longest_and_later_occurrences(
    values: tuple[bytes, ...],
    source: bytes,
    expected: bytes,
) -> None:
    # Given overlapping, duplicate, or later literal occurrences
    registry = SensitiveValueRegistry()
    registry.register(values)
    # When a complete stream is masked, Then leftmost-longest wins deterministically
    assert StreamingLiteralMasker(registry).feed(source, final=True) == expected
