"""Bounded entry point for Birkin's bundled deep-research workflow."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from ..moirai import cli as moirai_cli
from ..moirai import bindings
from ..moirai.engine import MoiraiError, load_script, run_script
from ._types import Tool, ToolContext, ToolResult


def _run(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
    question = inp.get("question")
    urls = inp.get("source_urls", [])
    if not isinstance(question, str) or not question.strip():
        return ToolResult("조사 질문을 입력하세요.", is_error=True)
    if ctx.abort is not None and ctx.abort.is_set():
        return ToolResult("조사가 시작되기 전에 중단되었습니다.", is_error=True)
    try:
        invalid_url = any(
            not isinstance(url, str)
            or urlsplit(url).scheme not in {"http", "https"}
            or not urlsplit(url).netloc
            for url in urls
        ) if isinstance(urls, list) else True
    except ValueError:
        invalid_url = True
    if (
        not isinstance(urls, list)
        or len(urls) > 18
        or invalid_url
    ):
        return ToolResult(
            "출처 URL은 HTTP(S) 주소를 최대 18개까지 입력할 수 있습니다.",
            is_error=True,
        )
    try:
        script = load_script(moirai_cli.resolve_script_path("deep-research"))
        provider = str(ctx.cfg.get("provider") or "").removesuffix("-cli")
        model = str(ctx.cfg.get("model") or "")
        if model.strip().lower() == "default":
            model = ""
        global_spec = f"{provider}:{model}" if model else provider
        roles = {
            name: {**decl, "default": global_spec or decl.get("default")}
            for name, decl in script.roles.items()
        }
        outcome = run_script(
            script,
            cfg=ctx.cfg,
            bindings_map=bindings.resolve(roles, cfg=ctx.cfg),
            args={
                "question": question.strip(),
                "source_urls": urls,
                "_workspace": str(ctx.cwd.resolve()),
            },
            on_event=ctx.emit,
            abort=ctx.abort,
        )
    except (MoiraiError, bindings.BindingError):
        return ToolResult("조사를 완료하지 못했습니다. 설정과 연결 상태를 확인하세요.", is_error=True)

    result = outcome.get("result")
    if not isinstance(result, dict):
        return ToolResult("조사 결과를 확인할 수 없습니다.", is_error=True)
    answer = str(result.get("answer") or "").strip()
    unresolved = [
        str(claim.get("claim"))
        for claim in result.get("claim_ledger", [])
        if isinstance(claim, dict)
        and claim.get("status") in {"unresolved", "refuted"}
    ]
    reasons = [str(reason) for reason in result.get("reasons", [])]
    outer_status = str(outcome.get("status") or "")
    completion = str(result.get("completion") or "")
    details = []
    if unresolved:
        details.append("미확정 또는 반박된 항목:\n" + "\n".join(f"- {item}" for item in unresolved))
    if reasons:
        details.append("남은 제약:\n" + "\n".join(f"- {reason}" for reason in reasons))
    verification_basis = str(result.get("verification_basis") or "").strip()
    if verification_basis:
        details.append(f"검증 기준: {verification_basis}")
    if outer_status == "aborted":
        details.insert(0, "조사 상태: 중단")
    elif outer_status == "error" or completion == "failed":
        details.insert(0, "조사 상태: 완료하지 못함")
    elif completion == "partial":
        details.insert(0, "조사 상태: 일부 완료")
    details.append(f"연구 실행 ID: {outcome.get('run_id', '확인 불가')}")
    is_error = completion == "failed" or outer_status in {"error", "aborted"}
    return ToolResult(
        "\n\n".join([answer or "확정된 답변이 없습니다.", *details]),
        is_error=is_error,
    )


def tools() -> list[Tool]:
    return [Tool(
        name="research_run",
        description=(
            "질문을 Birkin의 고정된 deep-research 워크플로우로 조사하고 "
            "검증된 답변, 출처 인용, 미확정 항목과 실행 ID를 반환합니다."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "question": {"type": "string", "minLength": 1},
                "source_urls": {
                    "type": "array",
                    "maxItems": 18,
                    "items": {"type": "string", "format": "uri"},
                },
            },
            "required": ["question"],
            "additionalProperties": False,
        },
        fn=_run,
    )]
