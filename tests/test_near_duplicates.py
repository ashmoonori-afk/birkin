"""Write-time near-duplicate guard (adopted from TDAI's mechanical candidate
recall — docs/tdai-comparison.md 차용 A).

memory_write_note stays non-blocking; it just gains an advisory when the new
note is nearly identical (>=0.60 token cosine) or clearly related (>=0.35)
to an existing note. Final judgment stays with the nightly curator.
"""

from birkin.memory import VaultMemory

BODY = ("the rsync deploy to the staging server failed twice before the fix "
        "was applied and verified by the release checklist yesterday evening ")
OTHER = ("gardening notes: tomato seedlings need eight hours of light and "
         "weekly fertilizer during early summer growth phases in the garden ")


def _mem(tmp_path):
    return VaultMemory({"vault_path": str(tmp_path)})


def test_twin_note_is_flagged_as_near_duplicate(tmp_path):
    mem = _mem(tmp_path)
    mem.write_note("deploy failure", BODY * 3)
    hits = mem.near_duplicates("deploy failure copy", BODY * 3)
    assert hits and hits[0][0] == "deploy-failure"
    assert hits[0][1] >= 0.60


def test_unrelated_note_is_not_flagged(tmp_path):
    mem = _mem(tmp_path)
    mem.write_note("deploy failure", BODY * 3)
    hits = mem.near_duplicates("tomato care", OTHER * 3)
    assert all(sim < 0.35 for _slug, sim in hits)


def test_updating_the_same_note_is_not_flagged_against_itself(tmp_path):
    mem = _mem(tmp_path)
    mem.write_note("deploy failure", BODY * 3)
    hits = mem.near_duplicates("deploy failure", BODY * 3)
    assert all(slug != "deploy-failure" for slug, _sim in hits)


def test_write_tool_appends_advisory(tmp_path):
    mem = _mem(tmp_path)
    mem.write_note("deploy failure", BODY * 3)
    tools = {t.name: t for t in mem.tools()}
    res = tools["memory_write_note"].fn(
        {"title": "deploy failure again", "body": BODY * 3}, None)
    text = res.content if hasattr(res, "content") else str(res)
    assert "deploy-failure" in text           # advisory names the neighbor
    assert "Wrote note" in text               # …and the write still happened
