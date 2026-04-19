"""Translator skill — tool implementations."""

from __future__ import annotations

from typing import Any

from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolParameter, ToolSpec

# Common tech terms: English -> Korean and Korean -> English
_EN_TO_KR: dict[str, str] = {
    "algorithm": "알고리즘",
    "api": "API",
    "authentication": "인증",
    "authorization": "인가",
    "backend": "백엔드",
    "bug": "버그",
    "cache": "캐시",
    "callback": "콜백",
    "class": "클래스",
    "cloud": "클라우드",
    "commit": "커밋",
    "component": "컴포넌트",
    "container": "컨테이너",
    "database": "데이터베이스",
    "deploy": "배포",
    "deployment": "배포",
    "endpoint": "엔드포인트",
    "framework": "프레임워크",
    "frontend": "프론트엔드",
    "function": "함수",
    "interface": "인터페이스",
    "library": "라이브러리",
    "middleware": "미들웨어",
    "module": "모듈",
    "pipeline": "파이프라인",
    "refactor": "리팩터링",
    "repository": "저장소",
    "server": "서버",
    "testing": "테스팅",
    "variable": "변수",
}

# Build reverse mapping
_KR_TO_EN: dict[str, str] = {v: k for k, v in _EN_TO_KR.items() if v != k}


class TranslateTool(Tool):
    """Translate common tech terms between Korean and English."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="translate_text",
            description=(
                "Translate common tech terms between Korean and English. "
                "For full sentence translation, use the LLM chat directly."
            ),
            parameters=[
                ToolParameter(
                    name="text",
                    type="string",
                    description="Text or term to translate",
                ),
                ToolParameter(
                    name="target_language",
                    type="string",
                    description="Target language code: 'ko' for Korean, 'en' for English",
                ),
            ],
            toolset="skills",
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        text = args.get("text", "")
        target = args.get("target_language", "")

        if not text.strip():
            return ToolOutput(success=False, output="", error="No text provided to translate")

        if not target.strip():
            return ToolOutput(
                success=False,
                output="",
                error="Target language is required (use 'ko' or 'en')",
            )

        target_lower = target.lower().strip()
        text_lower = text.lower().strip()

        if target_lower == "ko":
            translated = self._translate_to_korean(text_lower)
        elif target_lower == "en":
            translated = self._translate_to_english(text.strip())
        else:
            return ToolOutput(
                success=False,
                output="",
                error=f"Unsupported target language: '{target}'. Use 'ko' or 'en'.",
            )

        if translated:
            return ToolOutput(success=True, output=f"{text.strip()} -> {translated}")

        return ToolOutput(
            success=True,
            output=(
                f"No dictionary match for '{text.strip()}'. "
                "Full translation requires LLM. Use chat for complete translations."
            ),
        )

    @staticmethod
    def _translate_to_korean(term: str) -> str | None:
        """Look up an English term in the dictionary."""
        return _EN_TO_KR.get(term)

    @staticmethod
    def _translate_to_english(term: str) -> str | None:
        """Look up a Korean term in the dictionary."""
        return _KR_TO_EN.get(term)
