from __future__ import annotations

import hashlib
import json

import pytest

from birkin import moirai
from birkin.moirai import cli as moirai_cli
from birkin.tools import web


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))


@pytest.fixture
def script():
    return moirai.load_script(moirai_cli.resolve_script_path("deep-research"))


AXES = {"axes": [
    {"id": "a", "name": "정의", "question": "무엇인가", "queries": ["alpha"]},
    {"id": "b", "name": "검증", "question": "맞는가", "queries": ["beta"]},
]}


def _web(monkeypatch, *, two=True):
    packets = {
        "https://one.example/a": "Alpha causes 2 documented outcomes.",
        "https://two.example/b": "Alpha causes 2 documented outcomes independently.",
        "https://counter.example/c": "No counterexample was found.",
    }
    calls = {"search": 0, "fetch": 0}

    def search(query, count, ctx):
        del count, ctx
        calls["search"] += 1
        urls = ["https://one.example/a"]
        if two:
            urls.append("https://two.example/b")
        if query.startswith("반증"):
            urls = ["https://counter.example/c"]
        return {"query": query, "status": "ok",
                "results": [{"title": url, "url": url, "snippet": "discovery"}
                            for url in urls]}

    def fetch(url, ctx):
        del ctx
        calls["fetch"] += 1
        text = packets[url]
        return {"requested_url": url, "final_url": url, "status": "ok",
                "retrieved_at": "2026-09-06T00:00:00+00:00",
                "published_at": None, "modified_at": None,
                "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "text": text, "truncated": False, "error": None, "attempts": 1}

    monkeypatch.setattr(web, "research_search", search, raising=False)
    monkeypatch.setattr(web, "research_fetch", fetch, raising=False)
    return calls


def _spawn(*, finding_count=1, numeric=False, verdict="supported"):
    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        del binding, opts, cfg, timeout
        if "서로 겹치지 않는 조사 축" in prompt:
            return json.dumps(AXES, ensure_ascii=False)
        if "계획 완전성 검토" in prompt:
            return json.dumps({"complete": True, "missing_questions": [],
                               "reason": "covered"}, ensure_ascii=False)
        if "최종 감사 원장" in prompt:
            return json.dumps({"complete": True, "missing_questions": [],
                               "reason": "covered after audits"}, ensure_ascii=False)
        if "위 source_id만" in prompt:
            supports = [{"source_id": "S1",
                         "excerpt": "Alpha causes 2 documented outcomes."}]
            if numeric:
                supports.append({"source_id": "S2",
                                 "excerpt": "Alpha causes 2 documented outcomes independently."})
            return json.dumps({"findings": [
                {"claim_id": f"C{i}", "claim": "Alpha causes 2 documented outcomes" if numeric
                 else "Alpha가 문서에 있다", "supports": supports}
                for i in range(finding_count)]}, ensure_ascii=False)
        if "검증된 직접 사실 원장" in prompt:
            assert "원장에 없는 ID나 도구 문구를 만들지 마세요" in prompt
            return json.dumps({"inferences": [], "unanswered_questions": []},
                              ensure_ascii=False)
        if "지원과 반증을 구분" in prompt:
            audit_supports = [{"source_id": "S1", "excerpt":
                               "Alpha causes 2 documented outcomes."}]
            if numeric:
                audit_supports.append({"source_id": "S2", "excerpt":
                                       "Alpha causes 2 documented outcomes independently."})
            return json.dumps({"verdict": verdict, "reason": "독립 감사",
                               "supports": audit_supports},
                              ensure_ascii=False)
        raise AssertionError(prompt[:100])
    return spawn


def test_question_and_fetched_source_are_required(script, monkeypatch):
    assert moirai.run_script(script, cfg={}, args={},
                             spawn=_spawn())["result"]["completion"] == "failed"
    monkeypatch.setattr(web, "research_search",
                        lambda query, count, ctx: {"status": "empty", "results": []},
                        raising=False)
    out = moirai.run_script(script, cfg={}, args={"question": "q"},
                            spawn=_spawn())["result"]
    assert out["completion"] == "failed"
    assert "출처" in out["reasons"][0]


def test_real_fetch_packets_produce_deterministic_citations(script, monkeypatch):
    _web(monkeypatch)
    out = moirai.run_script(script, cfg={}, args={"question": "q"},
                            spawn=_spawn(numeric=True))["result"]
    assert out["completion"] == "complete"
    assert all(item["status"] == "cross_verified"
               for item in out["claim_ledger"])
    assert "[S1](https://one.example/a)" in out["answer"]
    assert "text" not in out["source_ledger"][0]
    assert out["source_ledger"][0]["content_sha256"]


def test_search_snippet_or_invented_excerpt_cannot_support_claim(
    script, monkeypatch,
):
    _web(monkeypatch)

    def bad_spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        del binding, opts, cfg, timeout
        if "서로 겹치지 않는 조사 축" in prompt:
            return json.dumps(AXES)
        return json.dumps({"findings": [{"claim_id": "C1", "claim": "invented",
                                        "supports": [{"source_id": "S1",
                                                      "excerpt": "discovery"}]}]})

    out = moirai.run_script(script, cfg={}, args={"question": "q"},
                            spawn=bad_spawn)["result"]
    assert out["completion"] == "partial"
    assert out["source_ledger"]
    assert out["claim_ledger"]
    assert all(item["status"] == "unresolved" for item in out["claim_ledger"])


def test_high_risk_claim_needs_independent_sources_and_auditor(
    script, monkeypatch,
):
    _web(monkeypatch, two=False)
    out = moirai.run_script(script, cfg={}, args={"question": "q"},
                            spawn=_spawn(numeric=True))["result"]
    assert out["completion"] == "partial"
    assert all(item["status"] == "unresolved" for item in out["claim_ledger"])


def test_unicode_code_point_is_identifier_not_quantity():
    from birkin.moirai.patterns.deep_research import _is_high_risk

    assert not _is_high_risk("U+0345 is COMBINING GREEK YPOGEGRAMMENI")
    assert _is_high_risk("U+0345 occurs in 12 cases")


def test_expansion_uses_searched_lead_urls_without_following_page_links(
    script, monkeypatch,
):
    parent = "https://unicode.example/chapter"
    child = "https://unicode.example/reports/tr39"
    unsafe = "https://127.0.0.1/reports/tr39"
    fetched = []

    def search(query, count, ctx):
        del count, ctx
        results = {
            "unicode": [{"title": "unicode chapter", "url": parent, "snippet": ""}],
            "UTS 39 confusable skeleton": [
                {"title": "UTS 39 unsafe mirror", "url": unsafe, "snippet": ""},
                {"title": "UTS 39 confusable skeleton", "url": child, "snippet": ""},
            ],
        }.get(query, [])
        return {"query": query, "status": "ok", "results": results}

    def fetch(url, ctx):
        del ctx
        fetched.append(url)
        if url == unsafe:
            return {"status": "invalid_response", "text": ""}
        text = ("Parent overview." if url == parent else
                "A confusable skeleton is used for detection.")
        links = ([
            {"url": unsafe, "text": "UTS 39 confusable skeleton mirror"},
            {"url": child, "text": "UTS 39 confusable skeleton"},
            {"url": parent, "text": "UTS 39 confusable skeleton"},
            {"url": "https://unicode.example/privacy", "text": "privacy policy"},
            {"url": "javascript:alert(1)", "text": "UTS 39 confusable skeleton"},
        ] if url == parent else [])
        return {"requested_url": url, "final_url": url, "status": "ok",
                "retrieved_at": "2026-09-06T00:00:00+00:00",
                "published_at": None, "modified_at": None,
                "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "text": text, "links": links, "truncated": False,
                "error": None, "attempts": 1}

    monkeypatch.setattr(web, "research_search", search)
    monkeypatch.setattr(web, "research_fetch", fetch)

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        del binding, opts, cfg, timeout
        if "서로 겹치지 않는 조사 축" in prompt:
            return json.dumps({"axes": [{"id": "a", "name": "security",
                                          "question": "confusable skeleton",
                                          "queries": ["unicode"]}]})
        if "계획 완전성 검토" in prompt or "최종 감사 원장" in prompt:
            return json.dumps({"complete": True, "missing_questions": [],
                               "reason": "covered"})
        if "확장 리드" in prompt:
            return json.dumps({"findings": [{
                "claim_id": "C2",
                "claim": "A confusable skeleton is used for detection.",
                "supports": [{"source_id": "S2", "excerpt":
                              "A confusable skeleton is used for detection."}],
            }], "leads": []})
        if "위 source_id만" in prompt:
            return json.dumps({"findings": [{
                "claim_id": "C1", "claim": "Parent overview exists",
                "supports": [{"source_id": "S1", "excerpt": "Parent overview."}],
            }], "leads": ["UTS 39 confusable skeleton"]})
        if "지원과 반증을 구분" in prompt:
            if "confusable skeleton is used" in prompt:
                supports = [{"source_id": "S2", "excerpt":
                             "A confusable skeleton is used for detection."}]
            else:
                supports = [{"source_id": "S1", "excerpt": "Parent overview."}]
            return json.dumps({"verdict": "supported", "reason": "checked",
                               "supports": supports})
        if "검증된 직접 사실 원장" in prompt:
            return json.dumps({"inferences": [], "unanswered_questions": []})
        raise AssertionError(prompt[:120])

    result = moirai.run_script(
        script, cfg={}, args={"question": "q"}, spawn=spawn)["result"]
    assert child in [row["final_url"] for row in result["source_ledger"]]
    assert "A confusable skeleton is used for detection." in result["answer"]
    assert unsafe in fetched
    assert fetched == [parent, unsafe, child]
    assert parent in fetched and fetched.count(parent) == 1
    assert "https://unicode.example/privacy" not in fetched
    assert "javascript:alert(1)" not in fetched


@pytest.mark.parametrize("worker_url", [
    "https://docs.example.org/good",
    " https://docs.example.org/good ",
])
def test_worker_leads_use_native_discovery_once_and_preserve_exact_provenance(
    script, monkeypatch, worker_url,
):
    initial = "https://example.org/overview"
    native_good = "https://docs.example.org/good"
    native_failed = "https://docs.example.org/failed"
    backend_fallback = "https://search.example.org/fallback"
    userinfo = "https://user:secret@example.org/private"
    unknown = "https://docs.example.org/unknown"
    calls = {"native": 0, "fetch": [], "search": []}

    def search(query, count, ctx):
        del count, ctx
        calls["search"].append(query)
        results = {
            "alpha": [initial], "beta": [initial],
            native_good: [native_good],
            native_failed: [native_failed, backend_fallback],
        }.get(query, [])
        return {"query": query, "status": "ok",
                "results": [{"url": url} for url in results]}

    def fetch(url, ctx):
        del ctx
        calls["fetch"].append(url)
        if url == native_failed:
            return {"status": "network_error", "text": ""}
        text = {initial: "Overview evidence.",
                native_good: "Native source evidence.",
                backend_fallback: "Backend fallback evidence."}[url]
        return {"requested_url": url, "final_url": url, "status": "ok",
                "retrieved_at": "2026-09-08T00:00:00+00:00",
                "published_at": None, "modified_at": None,
                "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "text": text, "truncated": False, "error": None,
                "attempts": []}

    monkeypatch.setattr(web, "research_search", search)
    monkeypatch.setattr(web, "research_fetch", fetch)

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        del binding, cfg, timeout
        if opts.get("native_web"):
            calls["native"] += 1
            return json.dumps({
                "candidates": [
                    {"axis_id": "a", "url": "https://[", "title": "bad"},
                    {"axis_id": "a", "url": userinfo, "title": "private"},
                    {"axis_id": "a", "url": initial, "title": "attempted"},
                    {"axis_id": "unknown", "url": unknown, "title": "unknown"},
                    {"axis_id": "a", "url": native_good, "title": "good"},
                    {"axis_id": "b", "url": native_good, "title": "duplicate"},
                    {"axis_id": "b", "url": native_failed, "title": "failed"},
                ],
                "web_search_count": 1, "observed_query": "worker leads",
                "provenance": "model_discovered_after_web_search",
            })
        if "서로 겹치지 않는 조사 축" in prompt:
            return json.dumps(AXES)
        if "계획 완전성 검토" in prompt or "최종 감사 원장" in prompt:
            return json.dumps({"complete": True, "missing_questions": [],
                               "reason": "covered"})
        if "확장 리드" in prompt:
            return json.dumps({"findings": [], "leads": []})
        if "위 source_id만" in prompt:
            leads = (["find alpha evidence", "find more alpha", worker_url]
                     if "축: 정의" in prompt else ["find beta evidence"])
            return json.dumps({"findings": [{
                "claim_id": "C1", "claim": "Overview exists",
                "supports": [{"source_id": "S1", "excerpt": "Overview evidence."}],
            }], "leads": leads})
        if "지원과 반증을 구분" in prompt:
            return json.dumps({"verdict": "supported", "reason": "checked",
                               "supports": [{"source_id": "S1",
                                             "excerpt": "Overview evidence."}]})
        if "검증된 직접 사실 원장" in prompt:
            return json.dumps({"inferences": [], "unanswered_questions": []})
        raise AssertionError(prompt[:120])

    result = moirai.run_script(
        script, cfg={}, args={"question": "q"}, spawn=spawn)["result"]
    ledger = {row["final_url"]: row for row in result["source_ledger"]}

    assert calls["native"] == 1
    assert calls["search"].count(native_good) == 1
    assert calls["search"].index(native_good) < calls["search"].index(
        "find alpha evidence")
    assert ledger[native_good]["discovery_method"] == (
        "model_discovered_after_web_search")
    assert "discovery_method" not in ledger[backend_fallback]
    assert calls["fetch"] == [
        initial, native_good, native_failed, backend_fallback,
    ]


def test_model_verdict_without_exact_audit_excerpt_cannot_promote(
    script, monkeypatch,
):
    _web(monkeypatch)

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        value = _spawn()(prompt, binding, opts, cfg, timeout=timeout)
        if "지원과 반증을 구분" in prompt:
            return json.dumps({"verdict": "supported", "reason": "guess",
                               "supports": [{"source_id": "S1",
                                             "excerpt": "not in source"}]})
        return value

    out = moirai.run_script(script, cfg={}, args={"question": "q"},
                            spawn=spawn)["result"]
    assert all(item["status"] == "unresolved" for item in out["claim_ledger"])


def test_more_than_twelve_findings_are_all_audited(
    script, monkeypatch,
):
    _web(monkeypatch)
    out = moirai.run_script(script, cfg={}, args={"question": "q"},
                            spawn=_spawn(finding_count=8))["result"]
    assert len(out["claim_ledger"]) == 16
    assert all(item.get("audit_reason") for item in out["claim_ledger"])


def test_audit_budget_includes_late_new_source_and_preserves_overflow(
    script, monkeypatch,
):
    _web(monkeypatch)
    base = _spawn(finding_count=14)

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        payload = json.loads(base(prompt, binding, opts, cfg, timeout=timeout))
        if "위 source_id만" in prompt and "축: 검증" in prompt:
            for finding in payload["findings"][-4:]:
                finding["claim"] = "Late novel evidence"
                finding["supports"] = [{"source_id": "S2", "excerpt":
                                        "Alpha causes 2 documented outcomes independently."}]
        elif "지원과 반증을 구분" in prompt and "Late novel evidence" in prompt:
            payload["supports"] = [{"source_id": "S2", "excerpt":
                                    "Alpha causes 2 documented outcomes independently."}]
        return json.dumps(payload, ensure_ascii=False)

    out = moirai.run_script(
        script, cfg={}, args={"question": "q"},
        spawn=spawn,
    )["result"]
    facts = [row for row in out["claim_ledger"]
             if row.get("claim_type") == "fact"]
    late = [row for row in facts if row["claim"] == "Late novel evidence"]
    overflow = [row for row in facts[:24] if "감사 상한 밖" in row["reason"]]
    assert len(facts) == 28
    assert sum(bool(row.get("audit_reason")) for row in facts) == 24
    assert {row["axis_id"] for row in facts if row.get("audit_reason")} == {"a", "b"}
    assert late and late[0]["status"] == "source_supported"
    assert overflow and all(row["status"] == "unresolved" for row in overflow)


def test_resume_reuses_durable_search_and_fetch_results(script, monkeypatch):
    calls = _web(monkeypatch)
    first = moirai.run_script(script, cfg={}, args={"question": "q"},
                              spawn=_spawn())
    observed = dict(calls)
    second = moirai.run_script(script, cfg={}, args={"question": "q"},
                               resume_from=first["run_id"], spawn=_spawn())
    assert second["result"]["answer"] == first["result"]["answer"]
    assert calls == observed


def test_resume_retries_a_failed_fetch_instead_of_caching_it(script, monkeypatch):
    calls = _web(monkeypatch)
    original = web.research_fetch

    def fail(url, ctx):
        calls["fetch"] += 1
        return {"requested_url": url, "final_url": "", "status": "network_error",
                "retrieved_at": "", "published_at": None, "modified_at": None,
                "content_sha256": "", "text": "", "truncated": False,
                "error": "offline", "attempts": 1}

    monkeypatch.setattr(web, "research_fetch", fail)
    first = moirai.run_script(script, cfg={}, args={"question": "q"}, spawn=_spawn())
    failed_fetches = calls["fetch"]
    monkeypatch.setattr(web, "research_fetch", original)
    second = moirai.run_script(script, cfg={}, args={"question": "q"},
                               resume_from=first["run_id"], spawn=_spawn())
    assert calls["fetch"] > failed_fetches
    assert second["result"]["source_ledger"]


def test_pattern_is_listed_and_keeps_algorithm_credit():
    path = moirai_cli.resolve_script_path("deep-research")
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "insane-search" in text and "ultra-research" in text


def test_same_publisher_pages_are_not_independent():
    from birkin.moirai.patterns.deep_research import _independent_sources

    finding = {"supports": [{"source_id": "S1"}, {"source_id": "S2"}]}
    sources = {
        "S1": {"final_url": "https://www.one.example/a", "text_sha256": "a"},
        "S2": {"final_url": "https://news.one.example/b", "text_sha256": "b"},
    }
    assert _independent_sources(finding, sources) == 1


def test_exact_cross_language_excerpt_is_kept_without_claiming_lexical_proof():
    from birkin.moirai.patterns.deep_research import _valid_supports

    sources = {"S1": {"source_id": "S1", "final_url": "https://example.test",
                       "text": "A 202 response means accepted, not completed."}}
    supports = _valid_supports(
        [{"source_id": "S1", "excerpt": "A 202 response means accepted, not completed."}],
        sources, "202 응답은 완료가 아니라 접수다")
    assert supports == [{"source_id": "S1",
                         "excerpt": "A 202 response means accepted, not completed.",
                         "match": "exact"}]


def test_relevant_text_can_select_a_keyword_sentence_beyond_prefix():
    from birkin.moirai.patterns.deep_research import _relevant_text

    text = ("unrelated material. " * 600) + "POST idempotency requires a key."
    selected = _relevant_text({"text": text}, ["POST idempotency"])
    assert "POST idempotency" in selected


def test_claim_id_collision_loop_and_refutation_citation():
    from birkin.moirai.patterns.deep_research import _render_answer, _unique_claim_ids

    findings = [{"claim_id": "x"}, {"claim_id": "x"}, {"claim_id": "x-2"}]
    assert len({row["claim_id"] for row in _unique_claim_ids(findings)}) == 3
    claims = [{"claim_id": "C1", "claim": "완료됐다", "status": "refuted",
               "supports": [{"source_id": "S1"}],
               "audit_supports": [{"source_id": "S2"}],
               "audit_reason": "조건부 반례가 확인됨"}]
    sources = {"S1": {"final_url": "https://support.test"},
               "S2": {"final_url": "https://counter.test"}}
    answer = _render_answer(claims, sources)
    assert "counter.test" in answer and "support.test" not in answer
    assert "검토: 조건부 반례가 확인됨" in answer


def test_future_publication_is_not_accepted_as_current_evidence():
    from birkin.moirai.patterns.deep_research import _recent_enough

    sources = {"S1": {"published_at": "2027-01-01T00:00:00+00:00",
                       "modified_at": None}}
    assert not _recent_enough(
        [{"source_id": "S1"}], sources, "2026-09-06T00:00:00+00:00")


def test_concurrent_does_not_trigger_the_current_time_gate():
    from birkin.moirai.patterns.deep_research import _TEMPORAL

    assert not _TEMPORAL.search("SQLite concurrent writers and WAL")
    assert _TEMPORAL.search("current SQLite behavior")


def test_protocol_identifiers_are_not_numeric_risk_by_themselves():
    from birkin.moirai.patterns.deep_research import _is_high_risk

    assert not _is_high_risk("RFC 9110 defines HTTP 202 Accepted")
    assert not _is_high_risk("HTTP 202는 RFC 9110이 정의하고 §9.2.2가 관련된다")
    assert not _is_high_risk("Generate a separate request")
    assert _is_high_risk("실패율이 20% 증가한다")
    assert _is_high_risk("이 동작 때문에 중복 실행이 발생한다")


def test_audit_context_prioritizes_all_source_specific_excerpt_anchors():
    from birkin.moirai.patterns.deep_research import _anchored_text, _relevant_text

    anchors = [f"ANCHOR-{index}-" + (str(index) * 390) for index in range(4)]
    text = ("unrelated index material. " * 350).join(anchors)
    selected = _anchored_text(text, [*anchors, anchors[0]])
    assert len(selected) <= 6000
    assert all(anchor in selected for anchor in anchors)
    wrapped = "Some\nclients\ttake a riskier approach when retrying POST."
    normalized = _relevant_text(
        {"text": wrapped}, ["한국어 무관 주장"],
        ["Some clients take a riskier approach when retrying POST."])
    assert "Some\nclients" in normalized


def test_search_candidates_are_interleaved_across_axes():
    from birkin.moirai.patterns.deep_research import _round_robin

    assert _round_robin([["a1", "a2", "a3"], ["b1", "b2"]]) == [
        "a1", "b1", "a2", "b2", "a3"]


def test_lead_scheduler_carries_overflow_and_fairly_serves_axes():
    from birkin.moirai.patterns.deep_research import _schedule_leads

    axis_a = {"id": "a"}
    axis_b = {"id": "b"}
    axis_c = {"id": "c"}
    pending = [(axis_a, "a1"), (axis_a, "shared")] + [
        (axis_a, f"a{index}") for index in range(2, 6)] + [
        (axis_b, "shared"), (axis_b, "b2"), (axis_c, "c1")]
    findings = [{"axis_id": "a", "supports": [{"source_id": "S1"}]},
                {"axis_id": "a", "supports": [{"source_id": "S2"}]},
                {"axis_id": "b", "supports": []}]
    seen = set()

    first, remaining = _schedule_leads(pending, findings, seen, limit=4)
    first_keys = [(axis["id"], lead) for axis, lead in first]
    assert first_keys[:2] == [("b", "shared"), ("c", "c1")]
    assert len(first) == 4 and len(remaining) == 5

    second, remaining = _schedule_leads(
        [*remaining, (axis_b, "b3"), (axis_b, "shared")], findings, seen, limit=4)
    all_selected = first_keys + [(axis["id"], lead) for axis, lead in second]
    assert ("a", "shared") in all_selected and ("b", "shared") in all_selected
    assert len(all_selected) == len(set(all_selected))
    assert remaining, "wave limit overflow must remain pending instead of being dropped"


def test_axis_and_inference_ids_avoid_existing_collisions():
    from birkin.moirai.patterns.deep_research import _unique_axis_ids, _valid_inferences

    axes = _unique_axis_ids([{"id": "same"}, {"id": "same"}, {"id": "same-2"}])
    assert len({axis["id"] for axis in axes}) == 3
    facts = [{"claim_id": "I1"}, {"claim_id": "I2"}]
    rows = _valid_inferences(
        [{"claim": "결론", "premise_claim_ids": ["I1"], "assumptions": []}], facts)
    assert rows[0]["claim_id"] == "I3"


def test_verified_premises_and_explicit_assumptions_produce_inference_status(
    script, monkeypatch,
):
    _web(monkeypatch)
    premise_enums = []

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        del binding, cfg, timeout
        if "서로 겹치지 않는 조사 축" in prompt:
            return json.dumps(AXES, ensure_ascii=False)
        supports = [
            {"source_id": "S1", "excerpt": "Alpha causes 2 documented outcomes."},
            {"source_id": "S2", "excerpt":
             "Alpha causes 2 documented outcomes independently."},
        ]
        if "축: 정의" in prompt:
            return json.dumps({"findings": [{"claim_id": "C1",
                                              "claim": "Alpha causes 2 documented outcomes",
                                              "claim_type": "fact",
                                              "supports": supports}], "leads": []})
        if "축: 검증" in prompt:
            return json.dumps({"findings": [], "leads": []})
        if "검증된 직접 사실 원장" in prompt:
            premise_enums.extend(opts["schema"]["properties"]["inferences"]
                                 ["items"]["properties"]["premise_claim_ids"]
                                 ["items"]["enum"])
            return json.dumps({"inferences": [{
                "claim": "따라서 Alpha 결과를 고려해야 한다",
                "premise_claim_ids": ["C1"], "assumptions": []}],
                "unanswered_questions": []},
                ensure_ascii=False)
        return json.dumps({"verdict": "supported", "reason": "premises support it",
                           "supports": supports})

    result = moirai.run_script(
        script, cfg={}, args={"question": "q"}, spawn=spawn)["result"]
    by_type = {claim["claim_type"]: claim for claim in result["claim_ledger"]}
    assert by_type["fact"]["status"] == "cross_verified"
    assert by_type["inference"]["status"] == "inference_supported"
    assert "전제: C1" in result["answer"]
    assert "가정: 추가 가정 없음" in result["answer"]
    assert premise_enums == ["C1"]


def test_failed_inference_synthesis_keeps_the_run_partial(script, monkeypatch):
    _web(monkeypatch)
    base = _spawn(numeric=True)

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        if "검증된 직접 사실 원장" in prompt:
            raise RuntimeError("synthesis unavailable")
        return base(prompt, binding, opts, cfg, timeout=timeout)

    result = moirai.run_script(
        script, cfg={}, args={"question": "q"}, spawn=spawn)["result"]
    assert result["completion"] == "partial"
    assert "최종 추론 생성에 실패했습니다" in result["reasons"]


def test_final_coverage_replaces_stale_synthesis_gap_with_reviewed_gap(
    script, monkeypatch,
):
    _web(monkeypatch)
    base = _spawn(numeric=True)
    stale = "짧은 인용과 URL은 원장에 없다"
    actual = "실제 환경별 동작은 검증되지 않았다"

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        if "검증된 직접 사실 원장" in prompt:
            assert "https://one.example/a" in prompt
            assert "Alpha causes 2 documented outcomes." in prompt
            return json.dumps({"inferences": [],
                               "unanswered_questions": [stale]}, ensure_ascii=False)
        if "최종 감사 원장" in prompt:
            assert stale in prompt
            assert "https://one.example/a" in prompt
            assert "실제 실험 수행 자체를 누락으로 추가하지 말고" in prompt
            return json.dumps({"complete": False,
                               "missing_questions": [actual],
                               "reason": "최종 원장 재평가"}, ensure_ascii=False)
        return base(prompt, binding, opts, cfg, timeout=timeout)

    result = moirai.run_script(
        script, cfg={}, args={"question": "q"}, spawn=spawn,
    )["result"]

    assert result["final_coverage"]["unanswered_questions"] == [actual]
    assert stale not in result["answer"]
    assert actual in result["answer"]


def test_failed_final_coverage_preserves_synthesis_gap(script, monkeypatch):
    _web(monkeypatch)
    base = _spawn(numeric=True)
    initial = "초기 단계에서 확인하지 못한 조건"

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        if "검증된 직접 사실 원장" in prompt:
            return json.dumps({"inferences": [],
                               "unanswered_questions": [initial]}, ensure_ascii=False)
        if "최종 감사 원장" in prompt:
            raise RuntimeError("final review unavailable")
        return base(prompt, binding, opts, cfg, timeout=timeout)

    result = moirai.run_script(
        script, cfg={}, args={"question": "q"}, spawn=spawn,
    )["result"]

    assert result["final_coverage"]["status"] == "assessment_failed"
    assert result["final_coverage"]["unanswered_questions"] == [initial]
    assert initial in result["answer"]


def test_incomplete_plan_gets_one_bounded_repair(script, monkeypatch):
    _web(monkeypatch)
    base = _spawn(numeric=True)
    calls = {"repair": 0}

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        if "사용자가 명시한 모든 대상" in prompt:
            return json.dumps({"axes": [AXES["axes"][0]]}, ensure_ascii=False)
        if "계획 완전성 검토" in prompt:
            return json.dumps({"complete": False,
                               "missing_questions": ["두 번째 요청 항목"],
                               "reason": "한 항목이 빠짐"}, ensure_ascii=False)
        if "검토자가 찾은 누락" in prompt:
            calls["repair"] += 1
            return json.dumps(AXES, ensure_ascii=False)
        return base(prompt, binding, opts, cfg, timeout=timeout)

    result = moirai.run_script(
        script, cfg={}, args={"question": "alpha와 beta를 비교"}, spawn=spawn)["result"]
    assert calls["repair"] == 1
    assert result["plan_coverage"]["status"] == "repaired"
    assert result["plan_coverage"]["axis_count"] == 2


def test_plan_review_failure_is_reported_as_partial(script, monkeypatch):
    _web(monkeypatch)
    base = _spawn(numeric=True)

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        if "계획 완전성 검토" in prompt:
            raise RuntimeError("review unavailable")
        return base(prompt, binding, opts, cfg, timeout=timeout)

    result = moirai.run_script(
        script, cfg={}, args={"question": "q"}, spawn=spawn)["result"]
    assert result["completion"] == "partial"
    assert result["plan_coverage"]["status"] == "unresolved"
    assert "조사 계획의 원질문 coverage를 확인하지 못했습니다" in result["reasons"]


def test_invalid_decisive_audit_gets_only_one_exact_quote_repair():
    from birkin.moirai.patterns.deep_research import _validated_audit

    source = {"S1": {"source_id": "S1", "final_url": "https://example.test",
                      "text": "Alpha is documented."}}

    class Auditor:
        def __init__(self, response):
            self.response = response
            self.calls = 0

        def agent(self, *args, **kwargs):
            self.calls += 1
            return self.response

    repaired = Auditor({"verdict": "supported", "reason": "fixed",
                        "supports": [{"source_id": "S1",
                                      "excerpt": "Alpha is documented."}]})
    verdict, supports, state = _validated_audit(
        repaired, "Alpha", {"verdict": "supported", "reason": "bad",
                            "supports": [{"source_id": "S1", "excerpt": "invented"}]},
        source, "same context", "repair")
    assert repaired.calls == 1 and verdict["verdict"] == "supported"
    assert supports and state == "repaired"

    mixed = Auditor({"verdict": "supported", "reason": "mixed",
                     "supports": [{"source_id": "S1", "excerpt": "Alpha is documented."},
                                  {"source_id": "S1", "excerpt": "invented"}]})
    _, supports, state = _validated_audit(
        mixed, "Alpha", {"verdict": "supported", "supports": []},
        source, "same context", "repair")
    assert mixed.calls == 1 and supports == [] and state == "repair_invalid"


def test_inference_repair_keeps_canonical_premises_and_assumptions():
    from birkin.moirai.patterns.deep_research import _inference_context, _validated_audit

    text = "A request can be accepted before processing completes."
    sources = {"S1": {"source_id": "S1", "final_url": "https://example.test",
                       "retrieved_at": "now", "published_at": None,
                       "truncated": False, "text": text}}
    facts = [{"claim_id": "C7", "claim": "접수와 완료는 다르다",
              "audit_supports": [{"source_id": "S1", "excerpt": text}]}]
    inference = {"claim_id": "I1", "claim": "완료 확인이 필요하다",
                 "premise_claim_ids": ["C7"],
                 "assumptions": ["별도 완료 알림이 없다"]}
    context = _inference_context(inference, facts, sources)

    class Auditor:
        prompt = ""

        def agent(self, prompt, **kwargs):
            self.prompt = prompt
            return {"verdict": "unresolved", "reason": "조건 부족", "supports": []}

    auditor = Auditor()
    _validated_audit(
        auditor, inference["claim"], {"verdict": "supported", "supports": []},
        sources, context, "repair")
    assert "C7" in auditor.prompt
    assert "별도 완료 알림이 없다" in auditor.prompt


def test_proposal_repair_uses_exact_evidence_without_becoming_a_fact():
    from birkin.moirai.patterns.deep_research import (
        _audited_inferences, _validated_audit,
    )

    excerpt = "There is no universal strategy for every downstream consumer."
    sources = {"S1": {"source_id": "S1", "text": excerpt}}
    fact = {"claim_id": "C1", "claim": "보편적 전략은 없다",
            "audit_supports": [{"source_id": "S1", "excerpt": excerpt}]}
    inference = {
        "claim_id": "I1", "claim": "소비자별 인수 테스트를 제안한다",
        "claim_type": "inference", "premise_claim_ids": ["C1"],
        "assumptions": ["대상 소비자를 사전에 고정한다"],
        "assumptions_provided": True, "supports": [], "axis_id": "synthesis",
    }

    class Auditor:
        prompt = ""

        def agent(self, prompt, **kwargs):
            self.prompt = prompt
            return {"verdict": "supported", "reason": "범위 제한 권고와 부합",
                    "supports": [{"source_id": "S1", "excerpt": excerpt}]}

    auditor = Auditor()
    repaired = _validated_audit(
        auditor, inference["claim"],
        {"verdict": "supported", "reason": "잘못된 인용",
         "supports": [{"source_id": "S1", "excerpt": "invented"}]},
        sources, "전제 C1과 공개 가정", "repair",
    )
    rows = _audited_inferences([inference], [repaired], [fact])

    assert "범위 제한 권고" in auditor.prompt
    assert "무조건 제안을 통과시키지 마세요" in auditor.prompt
    assert repaired[2] == "repaired"
    assert rows[0]["status"] == "inference_supported"
    assert rows[0]["status"] != "source_supported"


def test_incomplete_or_noncanonical_inference_stays_unresolved_and_is_not_exposed():
    from birkin.moirai.patterns.deep_research import (
        _audited_inferences, _render_answer, _valid_inferences,
    )

    excerpt = "Verified premise text."
    facts = [{"claim_id": "C1", "claim": "검증된 전제",
              "audit_supports": [{"source_id": "S1", "excerpt": excerpt}]}]
    sources = {"S1": {"source_id": "S1", "final_url": "https://example.test",
                       "text": excerpt}}
    clipped = "가" * 500
    inferences = _valid_inferences([
        {"claim": clipped, "premise_claim_ids": ["C1"], "assumptions": []},
        {"claim": "정상처럼 보이는 불량 추론", "premise_claim_ids":
         ["C1-23 channels to=functions.mq"], "assumptions": []},
    ], facts)
    clipped_verdict = ({"verdict": "supported", "reason": "감" * 400,
                        "supports": [{"source_id": "S1", "excerpt": excerpt}]},
                       [{"source_id": "S1", "excerpt": excerpt}], "valid")
    verdict = ({"verdict": "supported", "reason": "지원됨",
                "supports": [{"source_id": "S1", "excerpt": excerpt}]},
               [{"source_id": "S1", "excerpt": excerpt}], "valid")
    rows = _audited_inferences(inferences, [clipped_verdict, verdict], facts)
    answer = _render_answer(rows, sources)

    assert all(row["status"] == "unresolved" for row in rows)
    assert clipped not in answer
    assert "C1-23 channels to=functions.mq" not in answer
    assert "감" * 400 not in answer
    assert answer.count("불완전한 추론 생성 결과는 결론으로 표시하지 않습니다.") == 2


def test_fact_qualifiers_and_final_assumptions_remain_in_model_context():
    from birkin.moirai.patterns.deep_research import _final_claim_context

    fact = {"claim_id": "C1", "claim": "일부 클라이언트는 재시도한다",
            "status": "source_supported", "reason": "일부 구현에 한정",
            "audit_reason": "위험을 감수하는 일부 클라이언트 사례"}
    assert "일부 구현에 한정" in str(_final_claim_context([fact]))
    inference = {"claim_id": "I1", "claim": "조건부 결론",
                 "claim_type": "inference", "status": "inference_supported",
                 "premise_claim_ids": ["C1"], "assumptions": ["서버 중복 제거 없음"],
                 "reason": "조건부"}
    assert "서버 중복 제거 없음" in str(_final_claim_context([inference]))


def test_final_claim_context_includes_only_audited_source_evidence():
    from birkin.moirai.patterns.deep_research import _final_claim_context

    claims = [
        {"claim_id": "C1", "claim": "공식 정의", "status": "source_supported",
         "reason": "지원됨", "audit_reason": "정의가 직접 뒷받침",
         "audit_supports": [
             {"source_id": "S1", "excerpt": "Normative definition."},
             {"source_id": "S404", "excerpt": "Unavailable source."},
         ]},
        {"claim_id": "C2", "claim": "확인 불가", "status": "unresolved",
         "reason": "감사 근거 없음", "audit_reason": "원문 부족",
         "audit_supports": []},
    ]
    sources = {"S1": {
        "final_url": "https://unicode.example/spec",
        "retrieved_at": "2026-09-06T00:00:00+00:00",
        "published_at": "2025-09-01T00:00:00+00:00",
        "modified_at": None, "truncated": False,
    }}

    rows = _final_claim_context(claims, sources)
    assert rows[0]["audit_reason"] == "정의가 직접 뒷받침"
    assert rows[0]["evidence"] == [{
        "source_id": "S1", "excerpt": "Normative definition.",
        "url": "https://unicode.example/spec",
        "retrieved_at": "2026-09-06T00:00:00+00:00",
        "published_at": "2025-09-01T00:00:00+00:00",
        "modified_at": None, "truncated": False,
    }]
    assert rows[1]["status"] == "unresolved"
    assert rows[1]["reason"] == "감사 근거 없음"
    assert rows[1]["evidence"] == []


def test_final_coverage_after_audits_surfaces_specific_gap(script, monkeypatch):
    _web(monkeypatch)
    base = _spawn(numeric=True)
    final_prompts = []

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        if "최종 감사 원장" in prompt:
            final_prompts.append(prompt)
            return json.dumps({"complete": False,
                               "missing_questions": ["실패 뒤 복구 조건"],
                               "reason": "감사된 결론 없음"}, ensure_ascii=False)
        return base(prompt, binding, opts, cfg, timeout=timeout)

    result = moirai.run_script(
        script, cfg={}, args={"question": "q"}, spawn=spawn)["result"]
    assert result["completion"] == "partial"
    assert result["final_coverage"]["status"] == "unresolved"
    assert "실패 뒤 복구 조건" in result["answer"]
    assert "https://one.example/a" in final_prompts[0]
    assert "Alpha causes 2 documented outcomes." in final_prompts[0]


def test_internal_research_workspace_is_passed_to_model_spawn(
    script, monkeypatch, tmp_path,
):
    _web(monkeypatch)
    observed = []
    base = _spawn()

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        observed.append(opts.get("cwd"))
        return base(prompt, binding, opts, cfg, timeout=timeout)

    workspace = str(tmp_path.resolve())
    moirai.run_script(script, cfg={},
                      args={"question": "q", "_workspace": workspace}, spawn=spawn)
    assert observed and set(observed) == {workspace}


def test_full_source_cap_still_scans_for_an_existing_counter_hit(
    script, monkeypatch,
):
    urls = [f"https://p{i}.example/source" for i in range(18)]

    def search(query, count, ctx):
        del count, ctx
        hits = ["https://new.example/blocked", urls[0]] if query == "counter" else urls
        return {"query": query, "status": "ok",
                "results": [{"title": url, "url": url, "snippet": ""} for url in hits]}

    def fetch(url, ctx):
        del ctx
        index = urls.index(url)
        text = ("Alpha causes 2 outcomes." if index == 0 else
                "Alpha causes 2 outcomes independently." if index == 1
                else f"Distinct collected source {index}.")
        return {"requested_url": url, "final_url": url, "status": "ok",
                "retrieved_at": "2026-09-06T00:00:00+00:00",
                "published_at": None, "modified_at": None,
                "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "text": text, "truncated": False, "error": None, "attempts": 1}

    monkeypatch.setattr(web, "research_search", search)
    monkeypatch.setattr(web, "research_fetch", fetch)

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        del binding, opts, cfg, timeout
        if "서로 겹치지 않는 조사 축" in prompt:
            return json.dumps({"axes": [{"id": "a", "name": "a", "question": "alpha",
                                          "queries": ["alpha"]}]})
        supports = [{"source_id": "S1", "excerpt": "Alpha causes 2 outcomes."},
                    {"source_id": "S2", "excerpt":
                     "Alpha causes 2 outcomes independently."}]
        if "위 source_id만" in prompt:
            return json.dumps({"findings": [{"claim_id": "C1",
                                              "claim": "Alpha causes 2 outcomes",
                                              "counter_query": "counter",
                                              "supports": supports}], "leads": []})
        return json.dumps({"verdict": "supported", "reason": "checked",
                           "supports": supports})

    result = moirai.run_script(
        script, cfg={}, args={"question": "q"}, spawn=spawn)["result"]
    assert result["claim_ledger"][0]["status"] == "cross_verified"
