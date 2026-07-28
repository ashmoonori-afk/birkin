"""Your conversation history should be files you own, not birkin's JSON."""

from __future__ import annotations

import json

import pytest

from birkin import config, sessions_export


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    yield tmp_path


def _save(stem: str, messages) -> None:
    d = config.sessions_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stem}.json").write_text(
        json.dumps(messages, ensure_ascii=False), encoding="utf-8")


CONVO = [
    {"role": "user", "content": [{"type": "text", "text": "배포 어떻게 해?"}]},
    {"role": "assistant", "content": [{"type": "text", "text": "이렇게 합니다."}]},
]


def test_export_writes_obsidian_shaped_markdown():
    _save("20260725-101500", CONVO)
    p = sessions_export.export("20260725-101500")
    text = p.read_text(encoding="utf-8")
    assert p.suffix == ".md"
    assert text.startswith("---\n") and "type: session" in text
    assert "created: 2026-07-25" in text      # date recovered from the stem
    assert "배포 어떻게 해?" in text and "이렇게 합니다." in text
    assert "## You" in text and "## birkin" in text


def test_export_to_vault_lands_in_the_journal_zone():
    _save("20260725-101500", CONVO)
    p = sessions_export.export("20260725-101500", to_vault=True)
    vault = config.vault_dir(config.load_config())
    assert p.parent == vault / sessions_export.EXPORT_ZONE


def test_exported_note_is_indexed_like_any_other():
    from birkin import mnemosyne
    _save("20260725-101500", CONVO)
    sessions_export.export("20260725-101500", to_vault=True)
    dex = mnemosyne.Mnemosyne(config.vault_dir(config.load_config()))
    dex.refresh()
    assert [h for h in dex.search("배포", limit=5)]


def test_secrets_are_masked_in_the_export():
    _save("s", [{"role": "user", "content": [
        {"type": "text",
         "text": "key sk-ant-api03-AAAABBBBCCCCDDDDEEEEFFFF1234 입니다"}]}])
    text = sessions_export.export("s").read_text(encoding="utf-8")
    assert "sk-ant-api03-AAAABBBBCCCCDDDDEEEEFFFF1234" not in text
    assert "[redacted]" in text


def test_tool_blocks_are_noted_not_dumped():
    _save("s", [{"role": "assistant", "content": [
        {"type": "tool_use", "name": "read_file", "input": {"path": "x"}},
        {"type": "tool_result", "content": "A" * 5000},
        {"type": "text", "text": "done"}]}])
    text = sessions_export.export("s").read_text(encoding="utf-8")
    assert "(tool: read_file)" in text and "A" * 100 not in text


def test_missing_and_malformed_sessions_are_refused():
    with pytest.raises(FileNotFoundError):
        sessions_export.export("nope")
    _save("bad", {"not": "a conversation"})
    with pytest.raises(ValueError):
        sessions_export.export("bad")


def test_auto_transcripts_are_hidden_from_the_list():
    _save("mine", CONVO)
    _save("auto__telegram__42__20260725", CONVO)
    stems = [f.stem for f in sessions_export.list_sessions()]
    assert stems == ["mine"]
    assert len(sessions_export.list_sessions(include_auto=True)) == 2


def test_cli_lists_and_exports(capsys):
    import argparse

    from birkin.cli import _cmd_sessions, build_parser
    _save("20260725-101500", CONVO)

    args = build_parser().parse_args(["sessions", "export", "20260725-101500",
                                      "--vault"])
    assert args.func.__name__ == "_cmd_sessions"
    assert _cmd_sessions(args) == 0
    assert "wrote" in capsys.readouterr().out

    assert _cmd_sessions(argparse.Namespace(action="")) == 0
    assert "20260725-101500" in capsys.readouterr().out
