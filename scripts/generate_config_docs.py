"""Generate bilingual configuration references from the canonical schema."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from birkin import config
from birkin.config_model import load_config_schema

START = "<!-- config-schema:start -->"
END = "<!-- config-schema:end -->"


def _rows(
    schema: Mapping[str, Any],
    *,
    prefix: str = "",
) -> list[tuple[str, Mapping[str, Any]]]:
    out: list[tuple[str, Mapping[str, Any]]] = []
    props = schema.get("properties")
    if not isinstance(props, Mapping):
        return out
    for key, value in props.items():
        if not isinstance(value, Mapping):
            continue
        path = f"{prefix}.{key}".strip(".")
        out.append((path, value))
        out.extend(_rows(value, prefix=path))
    return out


def _type_label(schema: Mapping[str, Any]) -> str:
    value = schema.get("type", "any")
    return " / ".join(value) if isinstance(value, list) else str(value)


def render_reference(schema: Mapping[str, Any], locale: str) -> str:
    korean = locale == "ko"
    title = "# Birkin 설정 참조" if korean else "# Birkin configuration reference"
    intro = (
        "`config.json`은 희소 override 파일입니다. 생략된 값은 아래 기본값을 "
        "사용하며 알 수 없는 확장 키는 보존합니다."
        if korean else
        "`config.json` is a sparse override file. Omitted values use the "
        "defaults below, and unknown extension keys are preserved."
    )
    headers = (
        "| 경로 | 타입 | 기본값 | 설명 |\n|---|---|---|---|"
        if korean else
        "| Path | Type | Default | Description |\n|---|---|---|---|"
    )
    lines = [
        title,
        "",
        f"Schema version: {schema['x-birkin-version']}",
        "",
        intro,
        "",
        headers,
    ]
    for path, item in _rows(schema):
        if item.get("deprecated"):
            replacement = item.get("x-replaced-by", "")
            description = (
                f"폐기됨: {replacement} 사용" if korean
                else f"Deprecated: use {replacement}"
            ) if replacement else ("폐기됨" if korean else "Deprecated")
        else:
            description = item.get(
                "x-description-ko" if korean else "description", ""
            )
        escaped_description = str(description).replace("|", "\\|")
        default = json.dumps(item.get("default"), ensure_ascii=False)
        lines.append(
            f"| `{path}` | `{_type_label(item)}` | `{default}` | "
            f"{escaped_description} |"
        )
    return "\n".join(lines) + "\n"


def render_example(schema: Mapping[str, Any]) -> str:
    defaults = {
        key: value.get("default")
        for key, value in schema["properties"].items()
        if isinstance(value, Mapping) and "default" in value
    }
    return "```json\n" + json.dumps(
        defaults, ensure_ascii=False, indent=2
    ) + "\n```"


def replace_generated_block(text: str, generated: str) -> str:
    before, separator, rest = text.partition(START)
    if not separator:
        raise ValueError("README is missing config schema start marker")
    _old, separator, after = rest.partition(END)
    if not separator:
        raise ValueError("README is missing config schema end marker")
    return f"{before}{START}\n{generated}\n{END}{after}"


def _write_or_check(path: Path, expected: str, check: bool) -> bool:
    current = path.read_text(encoding="utf-8") if path.is_file() else ""
    if current == expected:
        return True
    if check:
        return False
    path.write_text(expected, encoding="utf-8")
    return True


def generate(root: Path, *, check: bool = False) -> int:
    schema = load_config_schema(config.DEFAULT_CONFIG)
    outputs = {
        root / "docs/config-reference.md": render_reference(schema, "en"),
        root / "docs/config-reference.ko.md": render_reference(schema, "ko"),
    }
    ok = all(_write_or_check(path, content, check)
             for path, content in outputs.items())
    example = render_example(schema)
    for name in ("README.md", "README.ko.md"):
        path = root / name
        text = path.read_text(encoding="utf-8")
        expected = replace_generated_block(text, example)
        ok = _write_or_check(path, expected, check) and ok
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    return generate(Path(__file__).resolve().parent.parent, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
