"""Multilingual lexical recall and the compressed index cache.

Every case runs against both lexical engines Birkin ships: ``birkin.mnemosyne``
(behind ``memory_search``) and the bundled ``birkin_mnemosyne`` package.
"""

from __future__ import annotations

import json
import unicodedata
import zlib
from pathlib import Path
from types import ModuleType

import pytest

import birkin.mnemosyne
import birkin_mnemosyne.mnemosyne
from birkin import config, memory_semantic
from birkin.memory import VaultMemory, _snippet
from birkin_mnemosyne.memory_format import snippet as bundled_snippet

ENGINES = [birkin.mnemosyne, birkin_mnemosyne.mnemosyne]
ENGINE_IDS = ["birkin", "bundled"]

# "cabbage prices went up" in Korean, spelled with escapes so this file stays
# free of Hangul literals.
HANGUL_PASSAGE = "\ubc30\ucd94 \uac00\uaca9\uc774 \uc62c\ub790\ub2e4"
HANGUL_QUERY = "\uac00\uaca9"

NOTES = {
    "garage": ("car", "the car needs new brake pads\n\nsee [[tax]]"),
    "ramen": ("豚骨スープ", "豚骨スープは十二時間煮込む。細麺を使う。"),
    "shaken": ("車検", "車検の期限は来年二月。"),
    "moving": ("搬家", "下个月从上海搬到杭州。"),
    "paella": ("Paella", "arroz bomba y azafrán"),
    "lease": ("Mietvertrag", "Der Vertrag verlängert sich automatisch."),
    "yogurt": ("Йогурт", "домашний йогурт на ночь"),
}


@pytest.fixture(params=ENGINES, ids=ENGINE_IDS)
def engine(request: pytest.FixtureRequest) -> ModuleType:
    return request.param


def _vault(root: Path, copies: int = 1) -> Path:
    (root / "food").mkdir()
    for copy in range(copies):
        for position, (slug, (title, body)) in enumerate(NOTES.items()):
            folder = root / "food" if position % 2 else root
            name = slug if copy == 0 else f"{slug}-{copy}"
            (folder / f"{name}.md").write_text(
                f"---\ntitle: {title}\ntags: [a, b]\n---\n\n{body}\n" * (position + 1),
                encoding="utf-8")
    return root


def _read_index(engine: ModuleType, vault: Path) -> dict[str, object]:
    return json.loads(zlib.decompress((vault / engine.INDEX_FILE).read_bytes()))


# ---------------- tokenizer -------------------------------------------------

def test_tokenize_folds_latin_accents_and_case(engine: ModuleType) -> None:
    assert engine.tokenize("Azafrán FÜTTERN Straße") == [
        "azafran", "azafr~", "futtern", "futte~", "strasse", "stras~"]


def test_tokenize_folds_vietnamese(engine: ModuleType) -> None:
    assert engine.tokenize("Tiếng Việt") == ["tieng", "viet"]


def test_tokenize_keeps_non_latin_words_with_their_marks(engine: ModuleType) -> None:
    assert engine.tokenize("Йогурт café") == ["йогурт", "йогур~", "cafe"]


def test_tokenize_nfkc_fullwidth_and_halfwidth(engine: ModuleType) -> None:
    assert engine.tokenize("ＡＰＩ") == ["api"]
    assert "カタ" in engine.tokenize("ｶﾀｶﾅ")


def test_tokenize_stems_only_long_alphabetic_words(engine: ModuleType) -> None:
    assert engine.tokenize("cat 2024 hello world2") == ["cat", "2024", "hello", "world2"]
    note = set(engine.tokenize("Der Vertrag verlängert sich"))
    assert "verla~" in note & set(engine.tokenize("Verlängerung"))
    assert {"vertr~", "der", "sich"} <= note


def test_tokenize_japanese_and_chinese_unigrams_and_bigrams(engine: ModuleType) -> None:
    assert {"豚", "骨", "豚骨", "骨ス", "スー", "ープ"} <= set(engine.tokenize("豚骨スープ"))
    assert {"搬", "家", "搬家", "家准", "准备"} <= set(engine.tokenize("搬家准备"))


def test_tokenize_supplementary_han_and_iteration_mark(engine: ModuleType) -> None:
    assert {"𠮷", "𠮷野", "野"} <= set(engine.tokenize("𠮷野家"))
    assert "人々" in engine.tokenize("人々")
    assert not any("・" in token for token in engine.tokenize("トム・クルーズ"))


def test_tokenize_composes_decomposed_hangul(engine: ModuleType) -> None:
    decomposed = unicodedata.normalize("NFD", HANGUL_PASSAGE)
    assert decomposed != HANGUL_PASSAGE
    assert engine.tokenize(decomposed) == engine.tokenize(HANGUL_PASSAGE)


# ---------------- ranking ---------------------------------------------------

def test_bm25_rewards_matching_every_query_script(engine: ModuleType) -> None:
    postings = {"moving": {"A": 1, "B": 1}, "checklist": {"A": 3}, "手続": {"B": 1}}
    doclens = {"A": 4, "B": 4, "C": 4}

    def single(term: str, slug: str) -> float:
        return engine.bm25_scores([term], postings, doclens, 4.0, 3)[slug]

    scores = engine.bm25_scores(["moving", "checklist", "手続"], postings, doclens, 4.0, 3)

    assert scores["A"] == pytest.approx(single("moving", "A") + single("checklist", "A"))
    assert scores["B"] == pytest.approx(
        1.5 * (single("moving", "B") + single("手続", "B")))


def test_bm25_single_script_and_digits_stay_plain(engine: ModuleType) -> None:
    postings = {"2024": {"a": 1}, HANGUL_QUERY: {"a": 1}, "の期": {"a": 1, "b": 1}}
    doclens = {"a": 2, "b": 2}

    def single(term: str) -> float:
        return engine.bm25_scores([term], postings, doclens, 2.0, 2)["a"]

    with_digits = engine.bm25_scores(["2024", HANGUL_QUERY], postings, doclens, 2.0, 2)

    assert with_digits["a"] == pytest.approx(single("2024") + single(HANGUL_QUERY))


def test_bm25_ignores_an_empty_term(engine: ModuleType) -> None:
    postings = {"cat": {"a": 1}}

    assert engine.bm25_scores([""], postings, {"a": 1}, 1.0, 1) == {}
    assert engine.bm25_scores(["", "cat"], postings, {"a": 1}, 1.0, 1) == (
        engine.bm25_scores(["cat"], postings, {"a": 1}, 1.0, 1))


@pytest.mark.parametrize(("query", "expected"), [
    ("車検 期限", "shaken"),
    ("搬到杭州", "moving"),
    ("搬", "moving"),
    ("azafran", "paella"),
    ("AZAFRÁN", "paella"),
    ("Verlängerung", "lease"),
    ("йогурт", "yogurt"),
    ("ＡＲＲＯＺ", "paella"),
])
def test_search_finds_notes_in_every_script(
        engine: ModuleType, tmp_path: Path, query: str, expected: str) -> None:
    dex = engine.Mnemosyne(_vault(tmp_path))

    hits = dex.search(query)

    assert hits and hits[0]["slug"] == expected


def test_search_finds_decomposed_hangul_note(engine: ModuleType, tmp_path: Path) -> None:
    # Given a note whose Hangul is stored decomposed, as macOS tools write it.
    (tmp_path / "market.md").write_text(
        unicodedata.normalize("NFD", f"---\ntitle: market\n---\n\n{HANGUL_PASSAGE}\n"),
        encoding="utf-8")
    (tmp_path / "other.md").write_text("---\ntitle: other\n---\n\nplain text\n",
                                       encoding="utf-8")

    # When it is searched with a precomposed query.
    hits = engine.Mnemosyne(tmp_path).search(HANGUL_QUERY)

    # Then the note is found.
    assert [hit["slug"] for hit in hits] == ["market"]


def test_search_breaks_score_ties_by_recency(engine: ModuleType, tmp_path: Path) -> None:
    for name, updated in (("older", "2026-01-01"), ("newer", "2026-06-01"),
                          ("oldest", "2025-01-01")):
        (tmp_path / f"{name}.md").write_text(
            f"---\ntitle: note\ncreated: 2025-01-01T00:00:00+00:00\n"
            f"updated: {updated}\n---\n\n搬家 checklist\n", encoding="utf-8")

    hits = engine.Mnemosyne(tmp_path).search("搬家")

    assert [hit["slug"] for hit in hits] == ["newer", "older", "oldest"]


def test_related_does_not_query_with_stems(engine: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "hub.md").write_text(
        "---\ntitle: hub\n---\n\nkubernetes kubernetes cluster operations\n",
        encoding="utf-8")
    (tmp_path / "spoke.md").write_text(
        "---\ntitle: spoke\n---\n\nkubernetes cluster upgrade\n", encoding="utf-8")
    dex = engine.Mnemosyne(tmp_path)

    assert [hit["slug"] for hit in dex.related("hub")] == ["spoke"]


# ---------------- compressed index cache ------------------------------------

def test_index_roundtrip_is_lossless(engine: ModuleType, tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    first = engine.Mnemosyne(vault)
    first.rebuild()

    reloaded = engine.Mnemosyne(vault)

    assert reloaded.entries() == first.entries()
    assert reloaded.search("豚骨")[0]["slug"] == "ramen"
    assert reloaded.search("搬到杭州")[0]["rel"] == "food/moving.md"


def test_index_file_is_compressed_json(engine: ModuleType, tmp_path: Path) -> None:
    vault = _vault(tmp_path, copies=10)
    dex = engine.Mnemosyne(vault)
    dex.rebuild()

    blob = (vault / engine.INDEX_FILE).read_bytes()
    stored = _read_index(engine, vault)

    assert stored == {"version": engine.INDEX_VERSION, "notes": dex.entries()}
    plain = json.dumps(stored, separators=(",", ":"))
    assert len(blob) < 0.3 * len(plain.encode("utf-8"))


def test_unchanged_notes_are_not_reparsed_on_load(
        engine: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _vault(tmp_path)
    engine.Mnemosyne(vault).rebuild()

    def refuse(path: Path, rel: str) -> None:
        raise AssertionError(f"re-parsed {rel}")

    monkeypatch.setattr(engine, "_note_entry", refuse)

    assert engine.Mnemosyne(vault).search("豚骨")[0]["slug"] == "ramen"


@pytest.mark.parametrize("damage", [
    lambda blob, version: b"\x78\x01garbage",
    lambda blob, version: blob[: len(blob) // 2],
    lambda blob, version: b"",
    lambda blob, version: b"{not json",
    lambda blob, version: zlib.compress(b"{not json"),
    lambda blob, version: zlib.compress(b"[1, 2]"),
    lambda blob, version: zlib.compress(b"\xed\x9f"),
    lambda blob, version: b"\xff\xfe\x00plain bytes that are not UTF-8",
    lambda blob, version: zlib.compress(json.dumps(
        {"version": version, "notes": {"ramen": 7, "shaken": {"terms": [1]},
                                       "moving": {"terms": {"搬": "x"}}}}).encode()),
], ids=["garbage", "truncated", "empty", "plain-not-json", "not-json", "json-list",
        "not-utf8", "plain-not-utf8", "malformed-entries"])
def test_corrupt_cache_is_rebuilt(engine: ModuleType, tmp_path: Path, damage) -> None:
    vault = _vault(tmp_path)
    engine.Mnemosyne(vault).rebuild()
    path = vault / engine.INDEX_FILE
    path.write_bytes(damage(path.read_bytes(), engine.INDEX_VERSION))

    dex = engine.Mnemosyne(vault)

    assert dex.search("豚骨")[0]["slug"] == "ramen"
    assert dex.search("車検")[0]["slug"] == "shaken"
    assert dex.search("搬")[0]["slug"] == "moving"
    assert set(_read_index(engine, vault)["notes"]) == set(NOTES)


def test_index_from_older_tokenizer_is_rebuilt(engine: ModuleType, tmp_path: Path) -> None:
    # Given a cache one version behind whose fingerprint matches the file, so
    # only the version check can force the re-parse.
    note = tmp_path / "shaken.md"
    note.write_text("---\ntitle: 車検\n---\n\n車検の期限", encoding="utf-8")
    stat = note.stat()
    stale = {"version": engine.INDEX_VERSION - 1, "notes": {"shaken": {
        "title": "車検", "rel": "shaken.md", "zone": "", "type": "topic",
        "tags": [], "links": [], "created": "", "updated": "",
        "confidence": 0.5, "polarity": "positive", "expires_at": None,
        "summary": "", "mtime": stat.st_mtime, "size": stat.st_size,
        "doclen": 0, "terms": {}}}}
    (tmp_path / engine.INDEX_FILE).write_bytes(zlib.compress(json.dumps(stale).encode()))

    # When a fresh engine opens it.
    hits = engine.Mnemosyne(tmp_path).search("車検")

    # Then the note was re-indexed with the current tokenizer.
    assert [hit["slug"] for hit in hits] == ["shaken"]


def test_legacy_plain_json_cache_is_replaced(engine: ModuleType, tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    legacy = vault / engine.LEGACY_INDEX_FILE
    legacy.write_text('{"version": 1, "notes": {}}', encoding="utf-8")

    engine.Mnemosyne(vault).rebuild()

    assert not legacy.exists()
    assert (vault / engine.INDEX_FILE).exists()
    assert engine.INDEX_FILE != engine.LEGACY_INDEX_FILE


# ---------------- snippets ---------------------------------------------------

@pytest.fixture(params=[(birkin.mnemosyne, _snippet),
                        (birkin_mnemosyne.mnemosyne, bundled_snippet)], ids=ENGINE_IDS)
def snippet_of(request: pytest.FixtureRequest):
    module, snippet = request.param
    return lambda text, query: snippet(text, module.tokenize(query), width=80)


def _buried(passage: str) -> str:
    return ("filler words here " * 30) + passage + (" tail" * 10)


def test_snippet_finds_accented_and_stemmed_passages(snippet_of) -> None:
    assert "azafrán" in snippet_of(_buried("arroz bomba y azafrán"), "AZAFRAN")
    assert "verlängert" in snippet_of(
        _buried("Der Vertrag verlängert sich automatisch"), "Verlängerung")


def test_snippet_stem_matches_only_stemmable_words(snippet_of) -> None:
    early = "note verla 123 and verla99 here"
    passage = "Der Vertrag verlängert sich automatisch"
    text = early + (" filler words here" * 30) + " " + passage + (" tail" * 10)

    assert "verlängert" in snippet_of(text, "Verlängerung")


def test_snippet_finds_decomposed_hangul(snippet_of) -> None:
    passage = unicodedata.normalize("NFD", HANGUL_PASSAGE)

    assert passage in snippet_of(_buried(passage), HANGUL_QUERY)


def test_snippet_without_a_match_keeps_the_head(snippet_of) -> None:
    assert snippet_of("plain opening line. " * 20, "absent") == ("plain opening line. " * 20).strip()[:80]


# ---------------- birkin.mnemosyne ranking adaptations ----------------------

def test_birkin_tokenize_drops_the_possessive_clitic() -> None:
    assert birkin.mnemosyne.tokenize("Nana's gift") == ["nana", "gift"]
    assert birkin.mnemosyne.tokenize("Nana\u2019s gift") == ["nana", "gift"]
    assert birkin.mnemosyne.tokenize("\ud558\uc900's class")[-1] == "class"
    assert birkin.mnemosyne.tokenize("it'smart 's") == ["it", "smart", "s"]


def test_birkin_query_stems_need_a_lone_word_next_to_cjk_or_hangul_terms() -> None:
    postings = {"migra~": {"exact": 1, "inflected": 1}, "migration": {"exact": 1},
                "plan": {"exact": 1}, "顧客": {"gold": 1}}
    doclens = {"exact": 3, "inflected": 3, "gold": 3, "other": 3}

    def score(terms: list[str]) -> dict[str, float]:
        return birkin.mnemosyne.bm25_scores(terms, postings, doclens, 3.0, 4)

    latin_only = score(["migration", "migra~", "plan"])
    anchor = score(["migration", "migra~", "顧客"])
    english_with_one_cjk_word = score(["migration", "migra~", "plan", "顧客"])

    assert set(latin_only) == {"exact", "inflected"}
    assert set(anchor) == {"exact", "inflected", "gold"}
    assert set(english_with_one_cjk_word) == {"exact", "gold"}
    assert english_with_one_cjk_word["exact"] == pytest.approx(
        score(["migration", "plan"])["exact"])


def test_birkin_cache_entry_missing_a_field_is_reparsed(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    birkin.mnemosyne.Mnemosyne(vault).rebuild()
    path = vault / birkin.mnemosyne.INDEX_FILE
    stored = json.loads(zlib.decompress(path.read_bytes()))
    complete = set(stored["notes"]["ramen"])
    del stored["notes"]["ramen"]["record_source"]
    path.write_bytes(zlib.compress(json.dumps(stored).encode("utf-8")))

    entries = birkin.mnemosyne.Mnemosyne(vault).entries()

    assert set(entries["ramen"]) == complete == birkin.mnemosyne._ENTRY_KEYS


def test_birkin_document_length_leaves_stems_out(tmp_path: Path) -> None:
    (tmp_path / "ops.md").write_text(
        "---\ntitle: ops\n---\n\nkubernetes cluster\n", encoding="utf-8")

    entry = birkin.mnemosyne.Mnemosyne(tmp_path).note_meta("ops")

    assert entry is not None
    assert entry["terms"] == {"ops": 1, "kubernetes": 1, "kuber~": 1, "cluster": 1,
                              "clust~": 1}
    assert entry["doclen"] == 3


# ---------------- Birkin surfaces on top of the engine ----------------------

def test_vault_memory_search_finds_accented_note_and_passage() -> None:
    mem = VaultMemory(config.load_config())
    mem.write_note("Paella", ("filler words here " * 30) + "arroz bomba y azafrán",
                   source="test")
    mem.write_note("Garage", "the car needs new brake pads", source="test")

    hits = mem.search("AZAFRAN")

    assert [hit["title"] for hit in hits] == ["paella"]
    assert "azafrán" in hits[0]["snippet"]


def test_entity_signal_ignores_truncation_stems() -> None:
    entries = {"kuberflow": {"title": "Kuberflow pipelines", "tags": [], "links": []}}

    assert memory_semantic.entity_scores("kubernetes", entries) == {"kuberflow": 0.0}
