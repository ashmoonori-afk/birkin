"""A skill can come from somewhere other than GitHub.

hub.py installs from GitHub, through quarantine and a security scan, and says
so deliberately: "one source (GitHub) and one auth method... hermes carries ten
source adapters, a tap registry and an index cache; none of that is needed to
install a skill you can already name."

That reasoning holds for the tap registry and the index cache, and this module
does not port them. It does not hold for the *identifier*: a skill sitting in a
directory on this disk, or behind a plain https URL, could not be installed at
all -- not because installing it is unsafe, but because parse_identifier only
understood ``owner/repo``. The quarantine, the scan and the audit log are the
safety boundary, and they are identical whichever way the bytes arrived.

So: one small protocol, three implementations, and the same boundary behind all
of them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from birkin.skills import hub, sources

SKILL_MD = """---
name: tidy-desk
description: Put things back where they came from.
---

# tidy-desk

Steps go here.
"""


@pytest.fixture()
def local_skill(tmp_path) -> Path:
    d = tmp_path / "tidy-desk"
    d.mkdir()
    (d / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (d / "references").mkdir()
    (d / "references" / "notes.md").write_text("notes", encoding="utf-8")
    return d


class TestRouting:
    def test_owner_repo_still_goes_to_github(self) -> None:
        source = sources.source_for("someone/their-skills")
        assert source.source_id() == "github"

    def test_a_local_directory_is_a_local_source(self, local_skill) -> None:
        assert sources.source_for(str(local_skill)).source_id() == "local"

    def test_an_https_url_is_a_url_source(self) -> None:
        assert sources.source_for(
            "https://example.com/skills/tidy-desk/SKILL.md").source_id() == "url"

    def test_a_path_that_does_not_exist_is_not_silently_a_local_source(self) -> None:
        """Otherwise a typo'd owner/repo becomes a confusing local miss."""
        assert sources.source_for("someone/nope").source_id() == "github"

    def test_every_source_answers_the_same_protocol(self, local_skill) -> None:
        for identifier in ("someone/their-skills", str(local_skill),
                           "https://example.com/x/SKILL.md"):
            source = sources.source_for(identifier)
            assert callable(source.search) and callable(source.fetch)
            assert isinstance(source.source_id(), str)


class TestLocalSource:
    def test_fetch_copies_the_skill_and_its_support_files(
            self, local_skill, tmp_path) -> None:
        dest = tmp_path / "quarantine"
        manifest = sources.LocalSource().fetch(str(local_skill), dest)
        assert (dest / "SKILL.md").read_text(encoding="utf-8") == SKILL_MD
        assert (dest / "references" / "notes.md").exists()
        assert manifest["name"] == "tidy-desk"

    def test_a_directory_without_a_skill_md_is_refused(self, tmp_path) -> None:
        empty = tmp_path / "not-a-skill"
        empty.mkdir()
        with pytest.raises(hub.HubError):
            sources.LocalSource().fetch(str(empty), tmp_path / "q")

    def test_search_matches_name_and_description(self, local_skill) -> None:
        found = sources.LocalSource().search("desk", root=local_skill.parent)
        assert [m.name for m in found] == ["tidy-desk"]
        assert found[0].source_id == "local"

    def test_search_matches_the_description_text_too(self, local_skill) -> None:
        assert sources.LocalSource().search(
            "back where", root=local_skill.parent)[0].name == "tidy-desk"

    def test_search_that_matches_nothing_returns_nothing(self, local_skill) -> None:
        assert sources.LocalSource().search("quantum",
                                            root=local_skill.parent) == []

    def test_a_traversing_name_never_escapes_the_skills_tree(
            self, tmp_path) -> None:
        """The path boundary hub.py already owns must cover this source too."""
        evil = tmp_path / "evil"
        evil.mkdir()
        (evil / "SKILL.md").write_text(
            "---\nname: ../../escaped\ndescription: no\n---\n", encoding="utf-8")
        with pytest.raises(hub.HubError):
            sources.LocalSource().fetch(str(evil), tmp_path / "q")


class TestUrlSource:
    def test_fetch_writes_the_downloaded_skill(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(hub, "_get",
                            lambda url, raw=False: SKILL_MD.encode("utf-8"))
        dest = tmp_path / "q"
        manifest = sources.UrlSource().fetch(
            "https://example.com/tidy-desk/SKILL.md", dest)
        assert (dest / "SKILL.md").read_text(encoding="utf-8") == SKILL_MD
        assert manifest["name"] == "tidy-desk"

    def test_a_plain_http_url_is_refused(self, tmp_path) -> None:
        """A skill is executable text; it does not arrive over cleartext."""
        with pytest.raises(hub.HubError):
            sources.UrlSource().fetch("http://example.com/x/SKILL.md",
                                      tmp_path / "q")

    def test_a_url_source_cannot_be_searched(self) -> None:
        """One URL is one skill -- there is no index behind it to query."""
        assert sources.UrlSource().search("anything") == []


class TestGitHubSourceKeepsWorking:
    def test_it_reports_its_id(self) -> None:
        assert sources.GitHubSource().source_id() == "github"

    def test_fetch_delegates_to_the_existing_bundle_fetcher(
            self, monkeypatch, tmp_path) -> None:
        seen: dict = {}

        def fake_bundle(identifier, dest):
            seen["identifier"] = identifier
            return {"name": "tidy-desk", "files": 1}

        monkeypatch.setattr(hub, "fetch_bundle", fake_bundle)
        manifest = sources.GitHubSource().fetch("someone/their-skills",
                                                tmp_path / "q")
        assert seen["identifier"] == "someone/their-skills"
        assert manifest["name"] == "tidy-desk"


class TestInstallRoutesThroughTheSource:
    def test_a_local_directory_can_be_installed(self, local_skill, tmp_path,
                                                monkeypatch) -> None:
        monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
        ok, report = hub.install(str(local_skill), confirm=lambda *a, **k: True)
        assert ok, report
        # An install lands under the path resolve_install_path owns, not
        # directly in the skills dir -- assert through that accessor rather
        # than re-deriving the layout here.
        assert (hub.resolve_install_path("tidy-desk") / "SKILL.md").is_file()

    def test_the_install_is_recorded_with_its_source(self, local_skill, tmp_path,
                                                     monkeypatch) -> None:
        monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
        hub.install(str(local_skill), confirm=lambda *a, **k: True)
        entry = hub.load_lock()["tidy-desk"]
        assert entry["source"] == "local"
