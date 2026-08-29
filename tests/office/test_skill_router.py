from __future__ import annotations

from itertools import combinations

import pytest

from birkin.office.skill_router import route_office_request

_FORMAT_EXAMPLES = {
    "docx": "보고서",
    "xlsx": "엑셀",
    "pptx": "피피티",
    "pdf": "PDF",
    "hwpx": "한글파일",
}


@pytest.mark.parametrize(
    ("phrase", "expected_skill", "expected_format"),
    [
        ("보고서 만들어줘", "word-documents", "docx"),
        ("리포트 작성해줘", "word-documents", "docx"),
        ("파워포인트 만들어줘", "presentations", "pptx"),
        ("피피티 검토해줘", "presentations", "pptx"),
        ("한글파일 작성해줘", "korean-hwp-documents", "hwpx"),
    ],
)
def test_korean_format_aliases_route_deterministically(
    phrase: str,
    expected_skill: str,
    expected_format: str,
) -> None:
    route = route_office_request(phrase)

    assert route is not None
    assert route.skill_name == expected_skill
    assert route.format_name == expected_format
    assert route.conflict is False
    assert route.clarification_question is None


@pytest.mark.parametrize(
    "formats",
    [
        *combinations(_FORMAT_EXAMPLES, 2),
        *combinations(_FORMAT_EXAMPLES, 3),
    ],
)
def test_mixed_format_request_promotes_clarification_question(
    formats: tuple[str, ...],
) -> None:
    phrase = ", ".join(_FORMAT_EXAMPLES[format_name] for format_name in formats)
    phrase += " 형식으로 만들어줘"
    route = route_office_request(phrase)

    assert route is not None
    assert route.skill_name == "office-documents"
    assert route.format_name is None
    assert route.conflict is True
    assert route.clarification_question == "어느 포맷으로 저장할까요?"
