"""Korean decision and recovery copy for workspace presentation events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ..llm import LLMStatus


@dataclass(frozen=True, slots=True)
class ProviderFailurePresentation:
    """One bounded provider failure explanation and recovery contract."""

    summary: str
    refusal_code: str
    retryable: bool


_PROVIDER_FAILURES: Final[dict[str, ProviderFailurePresentation]] = {
    "auth": ProviderFailurePresentation(
        "API 인증에 실패했습니다. API 키 또는 로그인을 확인한 뒤 다시 시도하세요.",
        "E_PROVIDER_AUTH",
        False,
    ),
    "billing": ProviderFailurePresentation(
        "결제 상태 때문에 요청을 처리할 수 없습니다. 제공자 결제 설정을 확인하세요.",
        "E_PROVIDER_BILLING",
        False,
    ),
    "rate_limit": ProviderFailurePresentation(
        "요청이 너무 많아 잠시 대기해야 합니다. 잠시 후 다시 시도하세요.",
        "E_PROVIDER_RATE_LIMIT",
        True,
    ),
    "network": ProviderFailurePresentation(
        "네트워크에 연결할 수 없습니다. 연결 상태를 확인한 뒤 다시 시도하세요.",
        "E_PROVIDER_NETWORK",
        True,
    ),
    "server": ProviderFailurePresentation(
        "제공자 서버에서 응답하지 못했습니다. 잠시 후 다시 시도하세요.",
        "E_PROVIDER_SERVER",
        True,
    ),
    "overflow": ProviderFailurePresentation(
        "대화 내용이 모델 한도를 넘었습니다. 새 대화를 시작하거나 내용을 줄이세요.",
        "E_PROVIDER_CONTEXT_LIMIT",
        False,
    ),
    "client": ProviderFailurePresentation(
        "요청 형식을 처리할 수 없습니다. 입력을 줄이거나 설정을 확인하세요.",
        "E_PROVIDER_REQUEST",
        False,
    ),
    "timeout": ProviderFailurePresentation(
        "응답 시간이 초과되었습니다. 잠시 후 다시 시도하세요.",
        "E_PROVIDER_TIMEOUT",
        True,
    ),
}

_UNKNOWN_PROVIDER_FAILURE: Final = ProviderFailurePresentation(
    "응답을 완료하지 못했습니다. 잠시 후 다시 시도하세요.",
    "E_PROVIDER_UNKNOWN",
    True,
)


def provider_failure(kind: str) -> ProviderFailurePresentation:
    """Map one stable provider kind to Korean recovery guidance."""
    return _PROVIDER_FAILURES.get(kind, _UNKNOWN_PROVIDER_FAILURE)


def llm_status_summary(status: LLMStatus) -> str:
    """Render a typed LLM wait state as bounded Korean progress copy."""
    if status.kind == "failover":
        return (
            "기본 모델을 사용할 수 없어 대체 모델로 전환했습니다. "
            "응답을 계속 기다려 주세요."
        )
    if status.kind == "recovered":
        return (
            "기본 모델 연결이 복구되었습니다. "
            "다음 요청부터 기본 모델을 사용합니다."
        )
    if status.reason == "rate_limit":
        return "요청이 많아 잠시 대기 중입니다. 자동으로 다시 시도합니다."
    if status.reason == "network":
        return "네트워크 연결을 기다리고 있습니다. 자동으로 다시 시도합니다."
    return "제공자 응답을 기다리고 있습니다. 자동으로 다시 시도합니다."
