"""_snippet: multi-term best-window extraction (token-diet D2, product form).

The old snippet took ONE term and 100 chars around its first occurrence;
agents then fell back to full-note reads (the real token cost). The upgraded
snippet finds the window densest in DISTINCT query terms, so the search
result itself answers more queries.
"""

from birkin.memory import VaultMemory, _snippet

FILLER = "lorem ipsum dolor sit amet consectetur adipiscing elit sed do. " * 8


def test_multi_term_window_beats_first_occurrence():
    # "alpha" appears alone early; alpha+beta appear together much later.
    text = ("alpha appears here first. " + FILLER
            + " alpha and beta finally meet in this passage. " + FILLER)
    s = _snippet(text, ["alpha", "beta"], width=120)
    assert "beta" in s.lower()          # old first-term logic would miss beta
    assert "alpha" in s.lower()


def test_no_match_falls_back_to_head():
    text = "The quick brown fox jumps over the lazy dog. " + FILLER
    s = _snippet(text, ["zzznope"], width=80)
    assert s.startswith("The quick brown fox")
    assert len(s) <= 90


def test_width_is_respected():
    text = FILLER + " target term here " + FILLER
    s = _snippet(text, ["target"], width=100)
    assert len(s) <= 130                 # width + ellipsis/trim tolerance
    assert "target" in s.lower()


def test_single_string_term_still_accepted():
    # tolerant signature: a bare string behaves like a one-term list
    text = FILLER + " needle in the middle " + FILLER
    s = _snippet(text, "needle", width=80)
    assert "needle" in s.lower()


def test_search_snippet_covers_multiword_query(tmp_path):
    mem = VaultMemory({"vault_path": str(tmp_path)})
    mem.write_note("deploy pipeline",
                   FILLER + " the rsync deploy failed twice on the staging "
                   "server before the fix. " + FILLER)
    hits = mem.search("rsync staging", limit=3)
    assert hits, "note should be found"
    snip = hits[0]["snippet"].lower()
    assert "rsync" in snip and "staging" in snip
