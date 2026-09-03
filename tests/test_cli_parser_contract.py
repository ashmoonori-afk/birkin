"""Machine-consumed characterization of the shipped argparse contract."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import FunctionType
from typing import Final, Protocol, TypeAlias, TypedDict, runtime_checkable

import pytest

from birkin.cli import build_parser


CONTRACT: Final = Path(__file__).with_name("fixtures") / "cli_parser_contract.json"
ACTION_FIELDS: Final = frozenset(
    {"option_strings", "dest", "nargs", "choices", "default", "required"}
)
UNREQUIRABLE_NARGS: Final = frozenset(
    {argparse.REMAINDER, argparse.ZERO_OR_MORE, argparse.OPTIONAL}
)
JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)


@runtime_checkable
class ObjectIterable(Protocol):
    def __iter__(self) -> Iterator[object]: ...


@runtime_checkable
class ObjectMapping(Protocol):
    def items(self) -> Iterable[tuple[object, object]]: ...


@runtime_checkable
class ActionView(Protocol):
    option_strings: object
    dest: object
    nargs: object
    choices: object
    default: object
    required: object


@dataclass(frozen=True, slots=True)
class ActionContract:
    option_strings: tuple[str, ...]
    dest: str
    nargs: JsonValue
    choices: JsonValue
    default: JsonValue
    required: bool


class NamespaceCase(TypedDict):
    argv: list[str]
    namespace: dict[str, JsonValue]


class HelpCase(TypedDict):
    path: list[str]
    actions: list[ActionContract]


def _object_iterable(value: object) -> ObjectIterable | None:
    return value if isinstance(value, ObjectIterable) else None


def _object_items(value: object) -> ObjectMapping | None:
    return value if isinstance(value, ObjectMapping) else None


def _object_list(value: object, label: str) -> list[object]:
    iterable = _object_iterable(value)
    if iterable is None or not isinstance(value, list):
        raise AssertionError(f"{label} must be a list")
    return list(iterable)


def _string_mapping(mapping: ObjectMapping, label: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in mapping.items():
        if not isinstance(key, str):
            raise AssertionError(f"{label} must have string keys")
        result[key] = item
    return result


def _object_mapping(value: object, label: str) -> dict[str, object]:
    mapping = _object_items(value)
    if mapping is None or not isinstance(value, dict):
        raise AssertionError(f"{label} must be an object")
    return _string_mapping(mapping, label)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise AssertionError(f"{label} must be a string")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise AssertionError(f"{label} must be a boolean")
    return value


def _string_list(value: object, label: str) -> list[str]:
    items = _object_list(value, label)
    if not all(isinstance(item, str) for item in items):
        raise AssertionError(f"{label} must contain only strings")
    return [item for item in items if isinstance(item, str)]


def _json_value(value: object, label: str) -> JsonValue:
    iterable = _object_iterable(value)
    mapping = _object_items(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list) and iterable is not None:
        return [_json_value(item, f"{label}[]") for item in iterable]
    if isinstance(value, dict) and mapping is not None:
        return {
            key: _json_value(item, f"{label}.{key}")
            for key, item in _string_mapping(mapping, label).items()
        }
    raise AssertionError(f"{label} contains a non-JSON value")


def _namespace_case(value: object, index: int) -> NamespaceCase:
    label = f"cases[{index}]"
    case = _object_mapping(value, label)
    return {
        "argv": _string_list(case.get("argv"), f"{label}.argv"),
        "namespace": {
            key: _json_value(item, f"{label}.namespace.{key}")
            for key, item in _object_mapping(
                case.get("namespace"), f"{label}.namespace"
            ).items()
        },
    }


def _action_contract(value: object, label: str) -> ActionContract:
    action = _object_mapping(value, label)
    if action.keys() != ACTION_FIELDS:
        raise AssertionError(f"{label} must contain only structural action fields")
    return ActionContract(
        option_strings=tuple(
            _string_list(action.get("option_strings"), f"{label}.option_strings")
        ),
        dest=_string(action.get("dest"), f"{label}.dest"),
        nargs=_json_value(action.get("nargs"), f"{label}.nargs"),
        choices=_json_value(action.get("choices"), f"{label}.choices"),
        default=_json_value(action.get("default"), f"{label}.default"),
        required=_boolean(action.get("required"), f"{label}.required"),
    )


def _help_case(value: object, index: int) -> HelpCase:
    label = f"helps[{index}]"
    case = _object_mapping(value, label)
    return {
        "path": _string_list(case.get("path"), f"{label}.path"),
        "actions": [
            _action_contract(action, f"{label}.actions[{action_index}]")
            for action_index, action in enumerate(
                _object_list(case.get("actions"), f"{label}.actions")
            )
        ],
    }


def _serialized(value: object) -> JsonValue:
    type_name = type(value).__qualname__
    representation = repr(value)
    iterable = _object_iterable(value)
    mapping = _object_items(value)
    if isinstance(value, (FunctionType, type)):
        return {"type": "callable", "value": f"{value.__module__}.{value.__qualname__}"}
    if callable(value):
        return {"type": "callable", "value": type_name}
    if isinstance(value, Path):
        return {"type": "Path", "value": str(value)}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list) and iterable is not None:
        return [_serialized(item) for item in iterable]
    if isinstance(value, tuple) and iterable is not None:
        return {"type": "tuple", "value": [_serialized(item) for item in iterable]}
    if isinstance(value, dict) and mapping is not None:
        return {
            key: _serialized(item)
            for key, item in _string_mapping(mapping, "serialized mapping").items()
        }
    return {"type": type_name, "value": representation}


def _decode_json(text: str, decode: Callable[[str], object] = json.loads) -> object:
    return decode(text)


def _document() -> tuple[list[NamespaceCase], list[HelpCase]]:
    raw_document = _decode_json(CONTRACT.read_text(encoding="utf-8"))
    root = _object_mapping(raw_document, "contract")
    schema = root.get("schema")
    if not isinstance(schema, int) or schema != 3:
        raise AssertionError("contract.schema must be 3")
    cases = [
        _namespace_case(case, index)
        for index, case in enumerate(_object_list(root.get("cases"), "contract.cases"))
    ]
    helps = [
        _help_case(case, index)
        for index, case in enumerate(_object_list(root.get("helps"), "contract.helps"))
    ]
    return cases, helps


def _parser_actions(parser: object) -> list[object]:
    if not isinstance(parser, argparse.ArgumentParser):
        raise AssertionError("parser must be an ArgumentParser")
    raw_attributes: object = vars(parser)
    attributes = _object_mapping(raw_attributes, "parser attributes")
    return _object_list(attributes.get("_actions"), "parser actions")


def _parser_choices(value: object) -> dict[str, argparse.ArgumentParser] | None:
    mapping = _object_items(value)
    if mapping is None or not isinstance(value, dict):
        return None
    choices = _string_mapping(mapping, "parser choices")
    result: dict[str, argparse.ArgumentParser] = {}
    for command, parser in choices.items():
        if not isinstance(parser, argparse.ArgumentParser):
            return None
        result[command] = parser
    return result


def _action_view(value: object) -> ActionView:
    if not isinstance(value, ActionView):
        raise AssertionError("parser action must expose the structural contract")
    return value


def _parser_at(path: list[str]) -> argparse.ArgumentParser:
    parser = build_parser()
    for command in path:
        matches: list[argparse.ArgumentParser] = []
        for raw_action in _parser_actions(parser):
            choices = _parser_choices(_action_view(raw_action).choices)
            if choices is not None and command in choices:
                matches.append(choices[command])
        if len(matches) != 1:
            raise AssertionError(f"command path is ambiguous or missing: {command}")
        parser = matches[0]
    return parser


def _required(action: ActionView, option_strings: tuple[str, ...], index: int) -> bool:
    """Report `required` without characterizing the running interpreter.

    CPython changed the positional `required` inference in
    `ArgumentParser._get_positional_kwargs`: 3.10 reports a positional with
    nargs REMAINDER ("...") as required=True, and one with nargs "*" as
    required=True unless an explicit default was given, while later versions
    exempt both. The flag carries no contract for these nargs -- argparse never
    demands a value for them -- so pin it instead of copying argparse.
    """
    if not option_strings and action.nargs in UNREQUIRABLE_NARGS:
        return False
    return _boolean(action.required, f"actions[{index}].required")


def _actions(parser: argparse.ArgumentParser) -> list[ActionContract]:
    result: list[ActionContract] = []
    for index, raw_action in enumerate(_parser_actions(parser)):
        action = _action_view(raw_action)
        parser_choices = _parser_choices(action.choices)
        option_strings = tuple(
            _string_list(action.option_strings, f"actions[{index}].option_strings")
        )
        result.append(
            ActionContract(
                option_strings=option_strings,
                dest=_string(action.dest, f"actions[{index}].dest"),
                nargs=_serialized(action.nargs),
                choices=(
                    list(parser_choices)
                    if parser_choices is not None
                    else _serialized(action.choices)
                ),
                default=_serialized(action.default),
                required=_required(action, option_strings, index),
            )
        )
    return result


_NAMESPACE_CASES, _HELP_CASES = _document()


@pytest.mark.parametrize("case", _NAMESPACE_CASES)
def test_parser_namespace_contract(case: NamespaceCase) -> None:
    namespace = build_parser().parse_args(case["argv"])
    raw_namespace: object = vars(namespace)
    values = _object_mapping(raw_namespace, "parsed namespace")

    assert {key: _serialized(values[key]) for key in sorted(values)} == case[
        "namespace"
    ]


@pytest.mark.parametrize("case", _HELP_CASES)
def test_parser_action_contract(case: HelpCase) -> None:
    assert _actions(_parser_at(case["path"])) == case["actions"]


@pytest.mark.parametrize("case", _HELP_CASES)
def test_shipped_help_contract(
    case: HelpCase, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as raised:
        _ = build_parser().parse_args([*case["path"], "--help"])

    captured = capsys.readouterr()
    assert raised.value.code == 0
    assert captured.out
    assert captured.err == ""
