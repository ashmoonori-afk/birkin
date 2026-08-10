"""FTS5 session index: ranking, incremental refresh, Korean, fallback."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

import pytest

from birkin import config, sessions_index
from birkin.tools import sessions


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    yield tmp_path


def _write(stem: str, *turns: str, metadata=None) -> None:
    msgs = []
    for i, t in enumerate(turns):
        msgs.append({"role": "user" if i % 2 == 0 else "assistant",
                     "content": [{"type": "text", "text": t}]})
    payload = {"metadata": metadata, "messages": msgs} if metadata else msgs
    (config.sessions_dir() / f"{stem}.json").write_text(
        json.dumps(payload), encoding="utf-8")


# -- shadow text -----------------------------------------------------------

def test_bigram_shadow_is_in_order_and_overlapping():
    assert sessions_index.bigram_shadow("구역 설계") == "구역 설계"
    assert sessions_index.bigram_shadow("메모리") == "메모 모리"
    assert sessions_index.bigram_shadow("가") == "가"
    assert sessions_index.bigram_shadow("hello") == ""


def test_query_builder_quotes_ascii_and_phrases_cjk():
    assert sessions_index.build_query("kubernetes") == '"kubernetes"'
    assert '"메모 모리"' in sessions_index.build_query("메모리")
    assert sessions_index.build_query("!!!") == ""


# -- search ----------------------------------------------------------------

def test_ranked_search_finds_the_right_session():
    _write("s1", "let's use kubernetes for deploys", "agreed")
    _write("s2", "buy milk", "ok")
    hits = sessions.search_sessions("kubernetes deploys")
    assert hits and hits[0]["session"] == "s1"
    assert "kubernetes" in hits[0]["snippet"]


def test_ranking_puts_the_denser_match_first():
    _write("noise", "we mentioned redis once in passing")
    _write("signal", "redis redis redis", "redis is the topic, all redis")
    hits = sessions.search_sessions("redis")
    assert [h["session"] for h in hits][0] == "signal"


def test_two_character_korean_query_matches_substring():
    _write("kr", "메모리 팰리스 구역 설계를 논의했다", "네 정리했습니다")
    _write("other", "커피 마시고 산책했다", "좋네요")
    hits = sessions.search_sessions("구역 설계")
    assert hits and hits[0]["session"] == "kr"


def test_korean_substring_inside_a_longer_run():
    # "팰리스" appears mid-run; bigram phrases are what make this work.
    _write("kr", "메모리팰리스구역설계", "확인")
    hits = sessions.search_sessions("팰리스")
    assert [h["session"] for h in hits] == ["kr"]


def test_snippet_never_leaks_shadow_bigrams():
    _write("kr", "메모리 팰리스 구역 설계를 논의했다")
    hit = sessions.search_sessions("구역")[0]
    assert "메모 모리" not in hit["snippet"]
    assert "구역" in hit["snippet"]


def test_no_match_returns_empty():
    _write("s1", "kubernetes")
    assert sessions.search_sessions("zzzznothing") == []


def test_index_search_returns_metadata_snippet_and_score():
    _write("meta", "redis deployment notes",
           metadata={"source": "telegram", "model": "gpt-5.6-sol"})
    timestamp = datetime(2026, 8, 2, 12, tzinfo=timezone.utc).timestamp()
    path = config.sessions_dir() / "meta.json"
    os.utime(path, (timestamp, timestamp))

    hits = sessions_index.search("redis")

    assert hits and set(hits[0]) == {
        "session", "date", "channel", "model", "snippet", "score"}
    assert hits[0]["session"] == "meta"
    assert hits[0]["date"].startswith("2026-08-02T12:00:00")
    assert hits[0]["channel"] == "telegram"
    assert hits[0]["model"] == "gpt-5.6-sol"
    assert "redis" in hits[0]["snippet"]
    assert isinstance(hits[0]["score"], float)


def test_search_covers_more_than_the_old_400_file_cap():
    for i in range(420):
        _write(f"bulk{i}", "filler text")
    _write("needle", "the octopus fixture is called moonfish")
    # The scan path only ever looked at the 400 newest files.
    hits = sessions.search_sessions("moonfish")
    assert [h["session"] for h in hits] == ["needle"]


# -- incremental refresh ---------------------------------------------------

def test_refresh_picks_up_new_edited_and_deleted_files():
    _write("a", "alpha content")
    assert [h["session"] for h in sessions.search_sessions("alpha")] == ["a"]

    _write("b", "beta content")                       # new file
    assert [h["session"] for h in sessions.search_sessions("beta")] == ["b"]

    _write("a", "gamma content")                      # edited in place
    assert sessions.search_sessions("alpha") == []
    assert [h["session"] for h in sessions.search_sessions("gamma")] == ["a"]

    (config.sessions_dir() / "b.json").unlink()       # deleted
    assert sessions.search_sessions("beta") == []


def test_refresh_only_reindexes_changed_files():
    _write("a", "alpha")
    _write("b", "beta")
    con = sessions_index._connect()
    assert sessions_index.refresh(con) == 2
    assert sessions_index.refresh(con) == 0           # fingerprints unchanged
    con.close()


def test_refresh_reports_progress_for_every_discovered_file():
    _write("a", "alpha")
    _write("b", "beta")
    progress = []
    con = sessions_index._connect()
    sessions_index.refresh(con, progress_cb=lambda done, total: progress.append(
        (done, total)))
    con.close()
    assert progress == [(1, 2), (2, 2)]


def test_schema_version_rebuilds_an_old_index():
    con = sqlite3.connect(sessions_index._path())
    con.executescript(
        "CREATE TABLE files (stem TEXT PRIMARY KEY, mtime REAL, size INTEGER);"
        "CREATE VIRTUAL TABLE session_fts USING fts5(stem UNINDEXED, body);"
        "PRAGMA user_version = 1;")
    con.close()
    _write("fresh", "schema migration needle")

    assert [h["session"] for h in sessions_index.search("needle")] == ["fresh"]
    con = sqlite3.connect(sessions_index._path())
    assert con.execute("PRAGMA user_version").fetchone()[0] \
        == sessions_index._SCHEMA_VERSION
    columns = {row[1] for row in con.execute("PRAGMA table_info(session_fts)")}
    con.close()
    assert {"date", "channel", "model"} <= columns


# -- degradation -----------------------------------------------------------

def test_corrupt_index_is_discarded_and_recall_survives():
    _write("s1", "kubernetes deploys")
    assert sessions.search_sessions("kubernetes")     # builds the index
    sessions_index._path().write_bytes(b"this is not a database")

    # The corrupt cache is thrown away and this query is served by the scan.
    assert [h["session"] for h in sessions.search_sessions("kubernetes")] == ["s1"]
    assert not sessions_index._path().exists()

    # The next query rebuilds the index from the JSON files and ranks again.
    assert [h["session"] for h in sessions.search_sessions("kubernetes")] == ["s1"]
    assert sessions_index._path().exists()


def test_falls_back_to_the_scan_when_the_index_cannot_serve(monkeypatch):
    _write("s1", "kubernetes deploys")
    monkeypatch.setattr(sessions_index, "search",
                        lambda query, limit=5, **filters: None)
    hits = sessions.search_sessions("kubernetes")
    assert [h["session"] for h in hits] == ["s1"]      # scan path still works


def test_fts5_unavailable_degrades_instead_of_raising(monkeypatch):
    _write("s1", "kubernetes deploys")

    def _boom(*a, **k):
        raise sqlite3.OperationalError("no such module: fts5")

    monkeypatch.setattr(sessions_index, "_connect", _boom)
    assert sessions_index.search("kubernetes") is None
    assert [h["session"] for h in sessions.search_sessions("kubernetes")] == ["s1"]


def test_malformed_transcript_is_skipped_not_fatal():
    (config.sessions_dir() / "bad.json").write_text("{not json", encoding="utf-8")
    _write("good", "kubernetes deploys")
    assert [h["session"] for h in sessions.search_sessions("kubernetes")] == ["good"]
