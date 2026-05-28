from birkin import config
from birkin.skills import build_manager


def _mgr():
    return build_manager(config.load_config())


def test_bundled_skills_discovered():
    mgr = _mgr()
    assert len(mgr.skills) >= 10  # the repo ships a sizable catalog
    assert "web-research" in mgr.skills


def test_index_non_empty():
    assert "web-research" in _mgr().index()


def test_get_case_insensitive():
    mgr = _mgr()
    assert mgr.get("WEB-RESEARCH") is not None


def test_route_picks_relevant_skill():
    mgr = _mgr()
    routed = mgr.route("find recent arxiv papers on transformer attention", limit=3)
    names = [s.name for s in routed]
    assert "arxiv" in names


def test_route_empty_query_returns_nothing():
    assert _mgr().route("", limit=3) == []


def test_render_skill_includes_bundled_script():
    mgr = _mgr()
    arxiv = mgr.get("arxiv")
    assert arxiv is not None
    rendered = mgr.render_skill(arxiv)
    assert "Bundled files" in rendered
    assert "scripts/search_arxiv.py" in rendered


def test_render_skill_plain_when_no_bundle():
    mgr = _mgr()
    sk = mgr.get("web-research")
    rendered = mgr.render_skill(sk)
    assert rendered.startswith("# Skill: web-research")
