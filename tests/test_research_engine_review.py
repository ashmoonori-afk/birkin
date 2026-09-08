"""Parent review: adversarial evidence through the real research pipeline."""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import pytest

from birkin import moirai
from birkin.moirai import cli, journal
from birkin.tools import web
from birkin.moirai.patterns import deep_research


def _run_corpus(tmp_path, monkeypatch, *, supports, numeric=False, axes=1,
                audit_prompts=None, audit_supports=None, dates=None,
                question="요청 수락과 완료를 구분하라", counter_url=None,
                inferences=None, fact_id="shared-model-id", unanswered=None,
                final_review=None, final_prompts=None, finding_claim=None,
                corpus_pages=None, search_results=None, finding_leads=None,
                counter_query=None, failed_urls=(), source_urls=None,
                finding_prompts=None, plan_prompts=None, fact_scope=None,
                attributed_source_id=None, audit_scope_preserved=None,
                inference_scope_preserved=None):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    pages = corpus_pages or {
        "https://one.example/a": "The service accepts requests for later processing.",
        "https://one.example/b": "Acceptance does not demonstrate completed processing.",
        "https://counter.example/c": "The completion status must be checked independently.",
    }
    fetched = []

    class Page(io.BytesIO):
        status = 200
        headers = {"Content-Type": "text/html"}

        def __init__(self, url):
            self.url = url
            date = (dates or {}).get(url, "")
            head = f'<head><meta property="article:published_time" content="{date}"></head>'
            super().__init__(("<html>" + head + "<body><article>" + pages[url]
                              + "</article></body></html>").encode())

        def geturl(self):
            return self.url

    class PublicCorpus:
        def open(self, request, **kwargs):
            fetched.append(request.full_url)
            if request.full_url in failed_urls:
                raise OSError("simulated fetch failure")
            return Page(request.full_url)

    monkeypatch.setattr(web, "pinned_opener", PublicCorpus)
    monkeypatch.setattr(web, "_marginalia", lambda query, count, cfg: [
        {"url": url, "title": f"Discovery for {query}",
         "snippet": f"Evidence candidate for {query}."}
        for url in (search_results(query) if search_results else
                    ([counter_url] if counter_url and query.startswith("반증") else pages))
    ])
    monkeypatch.setattr(web, "_mwmbl", lambda query, count: [])
    monkeypatch.setattr(web, "_bing_rss", lambda query, count: [])

    def respond(prompt, binding, opts, cfg, **kwargs):
        properties = (opts.get("schema") or {}).get("properties", {})
        if "missing_questions" in properties:
            if "최종 감사 원장" in prompt:
                if final_prompts is not None:
                    final_prompts.append(prompt)
                if final_review is not None:
                    return json.dumps(final_review)
            return json.dumps({"complete": True, "missing_questions": [], "reason": "단일 시험 질문을 다룸"})
        if "inferences" in properties:
            return json.dumps({"inferences": inferences or [], "unanswered_questions": unanswered or []})
        if "axes" in properties:
            if plan_prompts is not None:
                plan_prompts.append(prompt)
            return json.dumps({"axes": [
                {"id": str(i), "name": f"검증-{i}", "question": "처리 완료의 근거",
                 "queries": [f"initial-{i}"]}
                for i in range(axes)
            ]})
        if "findings" in properties:
            if finding_prompts is not None:
                finding_prompts.append(prompt)
            finding = {
                "claim_id": fact_id,
                "claim": finding_claim or (
                    "202 응답이면 처리 완료다" if numeric else "요청 수락은 처리 완료다"),
                "supports": supports,
                "counter_query": counter_query or "",
            }
            if fact_scope is not None:
                finding["fact_scope"] = fact_scope
            if attributed_source_id is not None:
                finding["attributed_source_id"] = attributed_source_id
            return json.dumps({"findings": [finding],
                               "leads": finding_leads(prompt) if finding_leads else []})
        if "verdict" in properties:
            if audit_prompts is not None:
                audit_prompts.append(prompt)
            # A credulous model must not bypass structural evidence checks.
            verdict = {"verdict": "supported", "reason": "검증되었다고 주장",
                       "supports": supports if audit_supports is None else audit_supports}
            inference_audit = ("감사할 추론:" in prompt or
                               ("문서 진술 범위 확인 필요: True" in prompt
                                and "지정 귀속 source_id: 없음" in prompt))
            scope = (inference_scope_preserved if inference_audit
                     else audit_scope_preserved)
            if scope is not None:
                verdict["scope_preserved"] = scope
            return json.dumps(verdict)
        raise AssertionError("unexpected model call")

    script = moirai.load_script(cli.resolve_script_path("deep-research"))
    args = {"question": question}
    if source_urls is not None:
        args["source_urls"] = source_urls
    outcome = moirai.run_script(script, cfg={}, args=args, spawn=respond)
    return outcome, fetched, journal.get_run(outcome["run_id"])


@pytest.mark.parametrize("support", [
    {"source_id": "S1", "excerpt": "   "},
    {"source_id": "S999", "excerpt": "The service accepts requests for later processing."},
    {"source_id": "S1", "excerpt": "The Moon is made of silver."},
])
def test_fabricated_or_empty_support_remains_in_unresolved_ledger(tmp_path, monkeypatch, support):
    outcome, fetched, saved = _run_corpus(tmp_path, monkeypatch, supports=[support])
    assert fetched, "the corpus must pass through the actual web fetch and extraction code"
    result = outcome["result"]
    claims = result.get("claim_ledger", [])
    assert len(claims) == 1, "invalid findings must remain auditable, not silently disappear"
    assert claims[0]["status"] == "unresolved"
    assert result["completion"] != "complete"
    assert saved is not None


def test_empty_audit_corpus_skips_model_and_stays_explicitly_unresolved(
    tmp_path, monkeypatch,
):
    audit_prompts = []
    outcome, _, _ = _run_corpus(
        tmp_path, monkeypatch,
        supports=[{"source_id": "S1", "excerpt": "fabricated evidence"}],
        audit_prompts=audit_prompts,
        search_results=lambda query: (
            ["https://one.example/a"] if query == "initial-0" else []),
    )
    claim = outcome["result"]["claim_ledger"][0]

    assert audit_prompts == []
    assert claim["status"] == "unresolved"
    assert claim["reason"] == "검증할 원문 근거가 없습니다"
    assert claim["audit_supports"] == []


def test_counter_only_corpus_keeps_existing_audit_call_boundary(tmp_path, monkeypatch):
    audit_prompts = []
    outcome, _, _ = _run_corpus(
        tmp_path, monkeypatch,
        supports=[{"source_id": "S1", "excerpt": "fabricated evidence"}],
        counter_url="https://counter.example/c", audit_prompts=audit_prompts,
    )

    assert audit_prompts
    assert outcome["result"]["claim_ledger"][0]["status"] == "unresolved"
    assert outcome["result"]["claim_ledger"][0]["reason"] == "검증 근거 부족"


def test_expansion_fetches_explicit_document_before_usable_search_hit(tmp_path, monkeypatch):
    initial = "https://one.example/a"
    explicit = "https://docs.example/target"
    other = "https://related.example/article"
    _, fetched, _ = _run_corpus(
        tmp_path, monkeypatch,
        supports=[{"source_id": "S1",
                   "excerpt": "The service accepts requests for later processing."}],
        corpus_pages={
            initial: "The service accepts requests for later processing.",
            explicit: "The requested document explains how completion is checked.",
            other: "A related article discusses the same general topic.",
        },
        search_results=lambda query: (
            [initial] if query == "initial-0" else [other] if query == explicit else []),
        finding_leads=lambda prompt: [explicit] if "확장 리드:" not in prompt else [],
    )

    assert fetched[:2] == [initial, explicit]
    assert other not in fetched


def test_worker_prompts_request_bounded_leads_and_reject_unrelated_claims(
    tmp_path, monkeypatch,
):
    prompts = []
    plan_prompts = []
    _run_corpus(
        tmp_path, monkeypatch,
        supports=[{"source_id": "S1",
                   "excerpt": "The service accepts requests for later processing."}],
        finding_prompts=prompts,
        plan_prompts=plan_prompts,
        finding_leads=lambda prompt: ["direct documentation"]
        if prompt.startswith("축:") else [],
    )

    assert len(prompts) >= 2
    assert "짧고 구체적인 원문 언어 질의" in plan_prompts[0]
    assert "완전한 HTTPS 문서 주소" in plan_prompts[0]
    assert all("완전한 HTTPS 문서 주소" in prompt for prompt in prompts[:2])
    assert all("부적합한 출처로 관련 없는 claim을 채우지 말고" in prompt
               for prompt in prompts[:2])


def test_two_pages_from_one_publisher_do_not_prove_independent_corroboration(tmp_path, monkeypatch):
    supports = [
        {"source_id": "S1", "excerpt": "The service accepts requests for later processing."},
        {"source_id": "S2", "excerpt": "Acceptance does not demonstrate completed processing."},
    ]
    outcome, fetched, _ = _run_corpus(tmp_path, monkeypatch, supports=supports, numeric=True)
    assert len(set(fetched)) >= 2
    claims = outcome["result"]["claim_ledger"]
    assert claims and all(claim["status"] != "cross_verified" for claim in claims)


def test_same_claim_id_from_parallel_axes_cannot_overwrite_findings(tmp_path, monkeypatch):
    supports = [{"source_id": "S1", "excerpt": "The service accepts requests for later processing."}]
    outcome, _, _ = _run_corpus(tmp_path, monkeypatch, supports=supports, axes=2)
    claims = outcome["result"]["claim_ledger"]
    assert len(claims) == 2
    assert len({claim["claim_id"] for claim in claims}) == len(claims)


def test_source_budget_preserves_later_axis_and_counter_admission(tmp_path, monkeypatch):
    quote = "The service accepts requests for later processing."
    initial = [f"https://initial.example/{axis}-{slot}"
               for slot in range(2) for axis in range(6)]
    failed = "https://expand.example/failure"
    duplicate = "https://expand.example/duplicate"
    expanded = [f"https://expand.example/{axis}" for axis in range(6)]
    counter = "https://counter.example/evidence"
    pages = {url: f"{quote} Unique source {index}." for index, url in enumerate(initial)}
    pages.update({url: f"Expansion evidence {index}." for index, url in enumerate(expanded)})
    pages[duplicate] = pages[initial[0]]
    pages[counter] = "Independent counter evidence."

    def search(query):
        if query.startswith("initial-"):
            axis = int(query.removeprefix("initial-"))
            return [initial[axis], initial[axis + 6]]
        if query == "lead-0":
            return [failed, duplicate, expanded[0]]
        if query.startswith("lead-"):
            return [expanded[int(query.removeprefix("lead-"))]]
        if query == "counter":
            return [counter]
        return []

    def leads(prompt):
        if prompt.startswith("축: 검증-"):
            return [f"lead-{prompt.split('검증-', 1)[1].splitlines()[0]}"]
        return []

    outcome, fetched, _ = _run_corpus(
        tmp_path, monkeypatch, axes=6,
        supports=[{"source_id": "S1", "excerpt": quote}],
        corpus_pages=pages, search_results=search, finding_leads=leads,
        counter_query="counter", failed_urls={failed},
    )
    urls = {source["final_url"] for source in outcome["result"]["source_ledger"]}

    assert set(initial) <= urls, "six axes must share twelve initial admissions"
    assert {expanded[0], expanded[1], expanded[4], counter} <= urls
    assert failed in fetched and duplicate in fetched
    assert duplicate not in urls, "failed and duplicate fetches must not consume admissions"
    assert expanded[2] not in fetched, "wave two must leave one follow-up slot for wave three"
    assert len(urls) == 16


def test_small_plan_leaves_room_for_expansion_after_many_initial_candidates(
    tmp_path, monkeypatch,
):
    quote = "The service accepts requests for later processing."
    initial = [f"https://initial.example/{index}" for index in range(15)]
    expanded = "https://expand.example/follow-up"
    pages = {url: f"{quote} Unique source {index}." for index, url in enumerate(initial)}
    pages[expanded] = "Follow-up evidence."

    def search(query):
        if query == "initial-0":
            return initial
        if query == "lead-0":
            return [expanded]
        return []

    outcome, fetched, _ = _run_corpus(
        tmp_path, monkeypatch,
        supports=[{"source_id": "S1", "excerpt": quote}],
        corpus_pages=pages, search_results=search,
        finding_leads=lambda prompt: ["lead-0"] if prompt.startswith("축:") else [],
        source_urls=initial,
    )
    urls = {source["final_url"] for source in outcome["result"]["source_ledger"]}

    assert set(initial[:13]) <= urls and expanded in urls
    assert initial[13] not in fetched and len(urls) == 14


def test_canonical_ids_handle_worker_supplied_suffix_collisions():
    items = [{"claim_id": value} for value in ("x", "x", "x-2", "x-2")]
    rows = deep_research._unique_claim_ids(items)
    assert len({row["claim_id"] for row in rows}) == len(rows)


def test_long_document_keeps_query_relevant_body_after_navigation():
    key_sentence = "There can only be one writer at a time in SQLite WAL mode."
    source = {"final_url": "https://sqlite.org/wal.html",
              "text": ("Navigation and introduction.\n" * 3000) + key_sentence}
    packet = deep_research._source_prompt(
        {"S1": {**source, "retrieved_at": "2026-09-06T00:00:00Z"}},
        ["SQLite WAL concurrency writers checkpoint durability"])
    assert key_sentence in packet


def test_korean_translation_preserves_real_english_evidence():
    quote = "The request has been accepted; processing has not completed."
    source = {"source_id": "S1", "final_url": "https://example.org/spec",
              "text": quote}
    findings = deep_research._valid_findings([{
        "claim_id": "translated", "claim": "요청 수락은 처리 완료를 뜻하지 않는다.",
        "supports": [{"source_id": "S1", "excerpt": quote}],
    }], {"S1": source})
    assert findings[0]["supports"], "translation must reach the semantic auditor"


def test_concurrent_is_not_a_current_information_request():
    assert not deep_research._TEMPORAL.search("SQLite WAL concurrent writers")
    assert deep_research._TEMPORAL.search("current SQLite release")
    assert deep_research._TEMPORAL.search("현재 릴리스")


def test_auditor_receives_claim_sources_instead_of_unrelated_corpus(tmp_path, monkeypatch):
    prompts = []
    _run_corpus(tmp_path, monkeypatch, supports=[{
        "source_id": "S1", "excerpt": "The service accepts requests for later processing.",
    }], audit_prompts=prompts)
    assert prompts
    assert "[S1] URL:" in prompts[0]
    assert "[S3] URL:" not in prompts[0], "unrelated source must not inflate audit corroboration"


@pytest.mark.parametrize("audited_date", ["2000-01-01T00:00:00Z", "2999-01-01T00:00:00Z"])
def test_recent_worker_citation_cannot_launder_stale_or_future_audit_evidence(
    tmp_path, monkeypatch, audited_date,
):
    outcome, _, _ = _run_corpus(
        tmp_path, monkeypatch,
        supports=[{"source_id": "S1", "excerpt": "The service accepts requests for later processing."}],
        audit_supports=[{"source_id": "S2", "excerpt": "Acceptance does not demonstrate completed processing."}],
        dates={"https://one.example/a": datetime.now(timezone.utc).isoformat(),
               "https://one.example/b": audited_date},
        question="현재 요청 수락과 완료를 구분하라",
        counter_url="https://one.example/b",
    )
    claim = outcome["result"]["claim_ledger"][0]
    assert claim["status"] == "unresolved"
    assert "시점" in claim["reason"]


def test_discarded_old_worker_source_does_not_disqualify_current_audit_evidence(tmp_path, monkeypatch):
    current = {"source_id": "S1", "excerpt": "The service accepts requests for later processing."}
    outcome, _, _ = _run_corpus(
        tmp_path, monkeypatch,
        supports=[current, {"source_id": "S2", "excerpt": "Acceptance does not demonstrate completed processing."}],
        audit_supports=[current],
        dates={"https://one.example/a": datetime.now(timezone.utc).isoformat(),
               "https://one.example/b": "2000-01-01T00:00:00Z"},
        question="현재 요청 수락과 완료를 구분하라",
    )
    assert outcome["result"]["claim_ledger"][0]["status"] == "source_supported"


def test_attributed_document_statement_has_distinct_fail_closed_status(
    tmp_path, monkeypatch,
):
    excerpt = "The document describes a maximum precision of 15 digits."
    common = {
        "supports": [{"source_id": "S1", "excerpt": excerpt}],
        "corpus_pages": {"https://one.example/a": excerpt},
        "finding_claim": "Microsoft 문서는 숫자 정밀도를 15자리로 설명한다.",
        "fact_scope": "documentary_statement",
        "attributed_source_id": "S1",
        "question": "현재 Excel의 숫자 정밀도를 확인하라",
    }
    final_prompts = []
    documented, _, _ = _run_corpus(
        tmp_path, monkeypatch, audit_scope_preserved=True,
        final_prompts=final_prompts, **common)
    row = documented["result"]["claim_ledger"][0]
    assert row["status"] == "documented_statement"
    assert row["audit_scope_preserved"] is True
    assert "출처 문서 설명" in documented["result"]["answer"]
    assert "현재 제품 동작을 독립 검증한 판정은 아님" in documented["result"]["answer"]
    assert "documented_statement" in final_prompts[0]

    repair_prompts = []
    missing_scope, _, _ = _run_corpus(
        tmp_path, monkeypatch, audit_scope_preserved=None,
        audit_prompts=repair_prompts, **common)
    assert missing_scope["result"]["claim_ledger"][0]["status"] == "unresolved"
    assert len(repair_prompts) == 2
    assert "지정 귀속 source_id: S1" in repair_prompts[1]

    world, _, _ = _run_corpus(
        tmp_path, monkeypatch, audit_scope_preserved=True,
        **{**common, "fact_scope": "world_fact"})
    assert world["result"]["claim_ledger"][0]["status"] == "unresolved"

    wrong_source, _, _ = _run_corpus(
        tmp_path, monkeypatch, audit_scope_preserved=True,
        **{**common, "attributed_source_id": "S2"})
    assert wrong_source["result"]["claim_ledger"][0]["status"] == "unresolved"


def test_document_scope_cannot_be_laundered_into_current_world_inference(
    tmp_path, monkeypatch,
):
    excerpt = "The document describes a maximum precision of 15 digits."
    outcome, _, _ = _run_corpus(
        tmp_path, monkeypatch,
        supports=[{"source_id": "S1", "excerpt": excerpt}],
        corpus_pages={"https://one.example/a": excerpt},
        finding_claim="Microsoft 문서는 숫자 정밀도를 15자리로 설명한다.",
        fact_scope="documentary_statement", attributed_source_id="S1",
        audit_scope_preserved=True, inference_scope_preserved=False,
        inferences=[{
            "claim": "따라서 현재 모든 Excel 환경은 숫자를 15자리로 제한한다.",
            "premise_claim_ids": ["shared-model-id"], "assumptions": [],
        }],
    )
    inference = next(row for row in outcome["result"]["claim_ledger"]
                     if row.get("claim_type") == "inference")
    assert inference["status"] == "unresolved"
    assert inference["audit_scope_preserved"] is False
    assert "문서 진술 전제의 귀속 범위" in inference["reason"]
    assert inference["documentary_premise_ids"] == ["shared-model-id"]
    context = deep_research._final_claim_context([inference])
    assert context[0]["fact_scope"] is None
    assert context[0]["documentary_premise_ids"] == ["shared-model-id"]

    missing_scope, _, _ = _run_corpus(
        tmp_path, monkeypatch,
        supports=[{"source_id": "S1", "excerpt": excerpt}],
        corpus_pages={"https://one.example/a": excerpt},
        finding_claim="Microsoft 문서는 숫자 정밀도를 15자리로 설명한다.",
        fact_scope="documentary_statement", attributed_source_id="S1",
        audit_scope_preserved=True, inference_scope_preserved=None,
        inferences=[{
            "claim": "따라서 현재 모든 Excel 환경은 숫자를 15자리로 제한한다.",
            "premise_claim_ids": ["shared-model-id"], "assumptions": [],
        }],
    )
    missing_inference = next(
        row for row in missing_scope["result"]["claim_ledger"]
        if row.get("claim_type") == "inference")
    assert missing_inference["status"] == "unresolved"
    assert missing_inference["audit_scope_preserved"] is None
    assert "문서 진술 전제의 귀속 범위" in missing_inference["reason"]

    bounded, _, _ = _run_corpus(
        tmp_path, monkeypatch,
        supports=[{"source_id": "S1", "excerpt": excerpt}],
        corpus_pages={"https://one.example/a": excerpt},
        finding_claim="Microsoft 문서는 숫자 정밀도를 15자리로 설명한다.",
        fact_scope="documentary_statement", attributed_source_id="S1",
        audit_scope_preserved=True, inference_scope_preserved=True,
        inferences=[{
            "claim": "이 문서만으로 모든 Excel 환경의 동작을 보장할 수 없다.",
            "premise_claim_ids": ["shared-model-id"], "assumptions": [],
        }],
    )
    bounded_inference = next(
        row for row in bounded["result"]["claim_ledger"]
        if row.get("claim_type") == "inference")
    assert bounded_inference["status"] == "inference_supported"


def test_suffixed_max_length_canonical_id_can_ground_an_inference(
    tmp_path, monkeypatch,
):
    model_id = "C" + "x" * 29
    suffixed_id = f"{model_id}-2"
    outcome, _, _ = _run_corpus(
        tmp_path, monkeypatch, axes=2, fact_id=model_id,
        supports=[{
            "source_id": "S1",
            "excerpt": "The service accepts requests for later processing.",
        }],
        inferences=[{
            "claim": "완료 상태를 별도로 확인해야 한다.",
            "premise_claim_ids": [suffixed_id], "assumptions": [],
        }],
    )
    rows = [row for row in outcome["result"]["claim_ledger"]
            if row.get("claim_type") == "inference"]
    assert any(row["claim_id"] == suffixed_id
               for row in outcome["result"]["claim_ledger"])
    assert len(rows) == 1 and rows[0]["status"] == "inference_supported"


@pytest.mark.parametrize("premises", [["unknown"], ["shared-model-id", "unknown"], ["I1"]])
def test_model_cannot_promote_inference_with_unknown_or_self_referencing_premises(
    tmp_path, monkeypatch, premises,
):
    outcome, _, _ = _run_corpus(
        tmp_path, monkeypatch,
        supports=[{"source_id": "S1", "excerpt": "The service accepts requests for later processing."}],
        inferences=[{"claim": "접수 확인만으로 후속 처리를 보장할 수 없다.",
                     "premise_claim_ids": premises, "assumptions": ["별도 완료 확인 경로가 없다."]}],
    )
    rows = [row for row in outcome["result"]["claim_ledger"]
            if row.get("claim_type") == "inference"]
    assert not rows, "schema-invalid inference must not enter the claim ledger"
    assert outcome["result"]["completion"] != "complete"
    assert "최종 추론 생성에 실패했습니다" in outcome["result"]["reasons"]
    assert all(value not in outcome["result"]["answer"]
               for value in premises if value != "shared-model-id")


def test_grounded_inference_displays_its_conditions_without_becoming_a_direct_fact(tmp_path, monkeypatch):
    condition = "별도 완료 확인 경로가 없다."
    outcome, _, _ = _run_corpus(
        tmp_path, monkeypatch,
        supports=[{"source_id": "S1", "excerpt": "The service accepts requests for later processing."}],
        inferences=[{"claim": "접수 확인만으로 후속 처리를 보장할 수 없다.",
                     "premise_claim_ids": ["shared-model-id"], "assumptions": [condition]}],
    )
    result = outcome["result"]
    inferred = [row for row in result["claim_ledger"] if row.get("claim_type") == "inference"]
    assert len(inferred) == 1 and inferred[0]["status"] == "inference_supported"
    assert "근거 기반 추론" in result["answer"]
    assert condition in result["answer"] and "shared-model-id" in result["answer"]


def test_inference_ids_cannot_shadow_a_verified_fact_id(tmp_path, monkeypatch):
    outcome, _, _ = _run_corpus(
        tmp_path, monkeypatch, fact_id="I1",
        supports=[{"source_id": "S1", "excerpt": "The service accepts requests for later processing."}],
        inferences=[{"claim": "접수 확인만으로 후속 처리를 보장할 수 없다.",
                     "premise_claim_ids": ["I1"], "assumptions": ["추가 완료 확인이 없다."]}],
    )
    rows = outcome["result"]["claim_ledger"]
    assert len(rows) == 2
    assert len({row["claim_id"] for row in rows}) == 2
    inferred = next(row for row in rows if row["claim_type"] == "inference")
    assert inferred["claim_id"] not in inferred["premise_claim_ids"]
    assert inferred["premise_claim_ids"] == ["I1"]


def test_successful_facts_cannot_hide_explicitly_unanswered_user_question(tmp_path, monkeypatch):
    missing = "원격 처리 완료는 어떻게 확인하는가?"
    outcome, _, _ = _run_corpus(
        tmp_path, monkeypatch,
        supports=[{"source_id": "S1", "excerpt": "The service accepts requests for later processing."}],
        unanswered=[missing],
        final_review={"complete": False, "missing_questions": [missing],
                      "reason": "최종 감사에서도 원격 완료 확인 근거가 없습니다"},
    )
    result = outcome["result"]
    assert result["claim_ledger"][0]["status"] == "source_supported"
    assert result["completion"] == "partial"
    assert missing in json.dumps(result, ensure_ascii=False)
    assert missing in result["answer"], "the unanswered question must be visible to the user"


@pytest.mark.parametrize("claim", [
    "HTTP 202는 요청 접수를 뜻한다.",
    "RFC 9110이 메서드 의미를 정의한다.",
    "RFC 9110 §9.2.2는 재시도의 조건을 설명한다.",
])
def test_korean_particles_do_not_turn_protocol_identifiers_into_statistics(claim):
    assert not deep_research._is_high_risk(claim)
    assert deep_research._is_high_risk(claim + " 오류율이 20% 증가했다.")


@pytest.mark.parametrize("claim", [
    "UTS #39는 식별자 보안 메커니즘을 정의한다.",
    "UAX #15는 정규화 형식을 정의한다.",
    "ISO-IEC #27001은 요구사항을 정의한다.",
])
def test_hash_prefixed_standard_identifiers_are_not_numbers(claim):
    assert not deep_research._is_high_risk(claim)
    assert deep_research._is_high_risk(claim + " 오류율이 20% 증가한다.")
    assert deep_research._is_high_risk(claim + " 12건에서 관찰됐다.")
    assert deep_research._is_high_risk(claim + " 이 때문에 오류가 발생한다.")
    assert deep_research._is_high_risk(claim + " 2024년에 변경됐다.")


def test_audited_standard_identifier_claim_needs_no_second_source(tmp_path, monkeypatch):
    quote = "The service accepts requests for later processing."
    outcome, _, _ = _run_corpus(
        tmp_path, monkeypatch,
        supports=[{"source_id": "S1", "excerpt": quote}],
        finding_claim="UTS #39의 서비스는 요청을 받아 나중에 처리한다.",
    )

    claim = outcome["result"]["claim_ledger"][0]
    assert claim["status"] == "source_supported"
    assert quote in outcome["result"]["answer"]


def test_audit_keeps_the_exception_around_a_quote_in_a_long_foreign_language_source():
    qualifier = "Some clients take a riskier approach and guess whether retrying is safe."
    quote = "A client might retry a POST after the connection closes."
    text = ("Navigation entry.\n" * 2000 + qualifier + "\n" + quote
            + "\nThis example does not guarantee safety.\n" + "POST index HTTP.\n" * 2000)
    prompt = deep_research._source_prompt(
        {"S1": {"final_url": "https://example.org/spec", "text": text,
                "retrieved_at": "2026-09-06T00:00:00Z"}},
        ["HTTP 연결이 끊어지면 POST 재시도가 허용된다."],
        {"S1": [quote]},
    )
    assert qualifier in prompt and quote in prompt
    assert "This example does not guarantee safety." in prompt


def test_four_distant_long_citations_all_survive_the_context_budget():
    anchors = [f"Evidence {index}: " + chr(65 + index) * 380 for index in range(4)]
    body = ("padding " * 1500).join(anchors)
    result = deep_research._relevant_text({"text": body}, [], anchors)
    assert len(result) <= 6000
    assert all(anchor in result for anchor in anchors)


def test_query_context_uses_budget_for_distinct_table_examples_among_repeated_code():
    common = [
        f"Normalization compatibility canonical overview {index} " + "background " * 120 + "."
        for index in range(20)
    ]
    alpha = "Alpha table | SpecialGlyph | maps to | plain-a."
    beta = "Beta table | DistinctToken | maps to | plain-b."
    text = "\n".join([*common[:7], alpha, *common[7:14], beta, *common[14:]])

    result = deep_research._query_relevant(
        text,
        ["normalization compatibility canonical SpecialGlyph DistinctToken"],
        6000,
    )

    assert len(result) <= 6000
    assert alpha in result and beta in result


def test_oversized_matching_sentence_does_not_erase_the_source_context():
    text = "RareTopic " + "long detail " * 1000
    result = deep_research._query_relevant(text, ["RareTopic"], 6000)
    assert result == text[:6000]


def test_valid_fragment_cannot_launder_an_invalid_part_of_audit_evidence(tmp_path, monkeypatch):
    valid = {"source_id": "S1", "excerpt": "The service accepts requests for later processing."}
    prompts = []
    outcome, _, _ = _run_corpus(
        tmp_path, monkeypatch, supports=[valid], audit_prompts=prompts,
        audit_supports=[valid, {"source_id": "S1", "excerpt": "All accepted work always completes."}],
    )
    assert outcome["result"]["claim_ledger"][0]["status"] == "unresolved"
    assert len(prompts) <= 2, "citation correction must not create an unbounded model loop"


def test_final_coverage_sees_rejected_inference_and_preserves_its_gap(tmp_path, monkeypatch):
    gap = "외부 처리와 로컬 완료 기록 사이의 장애는 어떻게 처리하는가?"
    prompts = []
    outcome, _, _ = _run_corpus(
        tmp_path, monkeypatch,
        supports=[{"source_id": "S1", "excerpt": "The service accepts requests for later processing."}],
        inferences=[{"claim": "외부 작업은 완료됐다.", "premise_claim_ids": ["missing"],
                     "assumptions": []}],
        final_prompts=prompts,
        final_review={"complete": True, "missing_questions": [gap], "reason": "모순된 모델 응답"},
    )
    result = outcome["result"]
    assert len(prompts) == 1 and "unresolved" in prompts[0]
    assert "외부 작업은 완료됐다." not in prompts[0]
    assert result["completion"] == "partial"
    assert result["final_coverage"]["status"] == "unresolved"
    assert gap in result["answer"], "complete=true must not erase the model's explicit gaps"


def test_auditor_scope_is_preserved_in_synthesis_and_user_output():
    limitation = "일부 구현의 위험한 추측을 설명할 뿐 일반적인 허용 규칙이 아니다."
    fact = {"claim_id": "C1", "claim": "클라이언트는 재시도할 수 있다.",
            "claim_type": "fact", "status": "source_supported", "supports": [],
            "reason": limitation, "audit_reason": limitation, "audit_supports": []}
    assert limitation in json.dumps(deep_research._final_claim_context([fact]), ensure_ascii=False)
    assert limitation in deep_research._render_answer([fact], {})
    assumption = "중복 제거 계약은 제공되지 않는다."
    inference = {**fact, "claim_id": "I1", "claim_type": "inference",
                 "premise_claim_ids": ["C1"], "assumptions": [assumption]}
    assert assumption in json.dumps(deep_research._final_claim_context([inference]), ensure_ascii=False)


def test_all_six_unanswered_axes_get_a_turn_before_repeated_expansion():
    axes = [{"id": str(i)} for i in range(6)]
    pending = [(axis, f"lead-{j}") for axis in axes for j in range(4)]
    seen = set()
    first, remaining = deep_research._schedule_leads(pending, [], seen, limit=4)
    second, remaining = deep_research._schedule_leads(remaining, [], seen, limit=4)
    assert {axis["id"] for axis, _ in first + second} == set(map(str, range(6)))
    assert len(seen) == 8 and len(remaining) == 16


def test_inline_extraction_fixes_real_quote_without_accepting_joined_sentences():
    from birkin.tools.web_document import extract_document

    text = extract_document(
        '<p>In <a href="wal.html">WAL mode</a>, SQLite exhibits "snapshot isolation".</p>'
        '<p>Important limitation remains.</p><p>Readers see a snapshot.</p>'
    ).text
    sources = {"S1": {"source_id": "S1", "text": text}}
    real = 'In WAL mode, SQLite exhibits "snapshot isolation".'
    assert deep_research._valid_supports([{"source_id": "S1", "excerpt": real}], sources, "q")
    assert not deep_research._valid_supports([
        {"source_id": "S1", "excerpt": real + " Readers see a snapshot."}], sources, "q")


def test_answer_quotes_only_audited_excerpts_that_exist_in_the_linked_source():
    real = "The service accepts requests for later processing."
    worker_only = "Acceptance does not demonstrate completed processing."
    sources = {
        "S1": {"source_id": "S1", "final_url": "https://example.org/spec", "text": real},
        "S2": {"source_id": "S2", "final_url": "https://example.org/worker",
               "text": worker_only},
    }
    claim = {"claim_id": "C1", "claim": "요청이 접수됐다.", "claim_type": "fact",
             "status": "source_supported",
             "supports": [{"source_id": "S2", "excerpt": worker_only}],
             "audit_supports": [{"source_id": "S1", "excerpt": real},
                                {"source_id": "S1", "excerpt": "fabricated evidence"}],
             "reason": "검증됨", "audit_reason": "검증됨"}

    answer = deep_research._render_answer([claim], sources)

    assert "## 확인한 원문" in answer
    assert f'[S1](https://example.org/spec): “{real}”' in answer
    assert "fabricated evidence" not in answer
    assert worker_only not in answer and "https://example.org/worker" not in answer


def test_answer_shares_a_25_word_quote_budget_per_url_without_repeating_quotes():
    first = " ".join(f"word{i}" for i in range(1, 31))
    second = " ".join(f"extra{i}" for i in range(1, 11))
    url = "https://example.org/spec"
    sources = {
        "S1": {"source_id": "S1", "final_url": url, "text": f"{first} {second}"},
        "S2": {"source_id": "S2", "final_url": url, "text": f"{first} {second}"},
    }
    claims = [
        {"claim_id": "C1", "claim": "첫 주장", "claim_type": "fact",
         "status": "source_supported", "supports": [],
         "audit_supports": [{"source_id": "S1", "excerpt": first}],
         "reason": "검증됨", "audit_reason": "검증됨"},
        {"claim_id": "C2", "claim": "둘째 주장", "claim_type": "fact",
         "status": "source_supported", "supports": [],
         "audit_supports": [{"source_id": "S1", "excerpt": first},
                            {"source_id": "S2", "excerpt": second}],
         "reason": "검증됨", "audit_reason": "검증됨"},
    ]

    answer = deep_research._render_answer(claims, sources)
    quote_lines = [line for line in answer.splitlines() if line.startswith("- [S")]

    assert len(quote_lines) == 1
    assert "word25” … (원문 앞 25단어 한도에서 잘림)" in quote_lines[0]
    assert "word26" not in answer and "extra1" not in answer
