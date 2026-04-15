"""Local CLI provider — shells out to claude or codex with real-time streaming."""

from __future__ import annotations

import asyncio
import shutil
from typing import Any, Callable, Optional

from birkin.core.errors import ProviderError, ProviderErrorKind
from birkin.core.models import Message
from birkin.core.providers.base import (
    ModelCapabilities,
    Provider,
    ProviderResponse,
    TokenUsage,
)


class LocalCLIProvider(Provider):
    """Provider that delegates to a local CLI tool (claude or codex).

    Supports real-time stdout streaming so the UI shows output as it arrives.
    Each call spawns a fresh CLI process (no session state in the CLI),
    but Birkin's own session store and WikiMemory persist across calls.
    """

    def __init__(
        self,
        *,
        cli: str = "claude",
        model: Optional[str] = None,
    ) -> None:
        self._cli = cli
        self._model = model or f"{cli}-local"

        binary = shutil.which(cli)
        if not binary:
            raise ProviderError(
                f"CLI tool '{cli}' not found in PATH. Install it first.",
                ProviderErrorKind.AUTH,
            )
        self._binary = binary

    @property
    def name(self) -> str:
        return f"{self._cli}-cli"

    @property
    def model(self) -> str:
        return self._model

    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            context_window=100000,
            supports_tools=False,
            supports_streaming=True,
        )

    def complete(
        self,
        messages: list[Message],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        stream_callback: Optional[Callable[[Optional[str]], None]] = None,
    ) -> ProviderResponse:
        """Run the CLI synchronously."""
        import subprocess

        prompt = self._extract_prompt(messages)
        cmd = self._build_command(prompt)

        try:
            if stream_callback:
                # Stream stdout line by line
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
                output_parts: list[str] = []
                assert proc.stdout is not None
                for line in proc.stdout:
                    output_parts.append(line)
                    stream_callback(line)
                proc.wait(timeout=120)
                stream_callback(None)

                stderr = proc.stderr.read() if proc.stderr else ""
                if proc.returncode != 0:
                    raise ProviderError(
                        f"{self._cli} error: {stderr.strip() or f'exit code {proc.returncode}'}",
                        ProviderErrorKind.SERVER,
                    )
                output = "".join(output_parts).strip()
            else:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if result.returncode != 0:
                    raise ProviderError(
                        f"{self._cli} error: {result.stderr.strip() or f'exit code {result.returncode}'}",
                        ProviderErrorKind.SERVER,
                    )
                output = result.stdout.strip()

            return ProviderResponse(
                content=output,
                tool_calls=None,
                usage=TokenUsage(prompt_tokens=0, completion_tokens=0),
                stop_reason="stop",
                model=self._model,
            )

        except subprocess.TimeoutExpired:
            raise ProviderError(f"{self._cli} timed out after 120 seconds", ProviderErrorKind.SERVER)
        except FileNotFoundError:
            raise ProviderError(f"CLI tool '{self._cli}' not found", ProviderErrorKind.AUTH)

    async def acomplete(
        self,
        messages: list[Message],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        stream_callback: Optional[Callable[[Optional[str]], None]] = None,
    ) -> ProviderResponse:
        """Async version — streams stdout chunks in real-time."""
        prompt = self._extract_prompt(messages)
        cmd = self._build_command(prompt)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            output_parts: list[str] = []

            if stream_callback and proc.stdout:
                # Read and stream chunks as they arrive
                while True:
                    chunk = await asyncio.wait_for(proc.stdout.read(256), timeout=120)
                    if not chunk:
                        break
                    text = chunk.decode("utf-8", errors="replace")
                    output_parts.append(text)
                    stream_callback(text)

                stream_callback(None)
                await proc.wait()
            else:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
                output_parts.append(stdout.decode("utf-8", errors="replace"))

            if proc.returncode != 0:
                stderr_data = b""
                if proc.stderr:
                    stderr_data = await proc.stderr.read()
                error_text = stderr_data.decode().strip() or f"exit code {proc.returncode}"
                raise ProviderError(f"{self._cli} error: {error_text}", ProviderErrorKind.SERVER)

            output = "".join(output_parts).strip()

            return ProviderResponse(
                content=output,
                tool_calls=None,
                usage=TokenUsage(prompt_tokens=0, completion_tokens=0),
                stop_reason="stop",
                model=self._model,
            )

        except asyncio.TimeoutError:
            raise ProviderError(f"{self._cli} timed out after 120 seconds", ProviderErrorKind.SERVER)

    def _extract_prompt(self, messages: list[Message]) -> str:
        """Build a compact prompt for the CLI.

        Only sends the last user message plus minimal recent context
        (last 2 assistant turns) to keep the CLI call fast.
        System prompts and wiki memory are excluded — the CLI
        doesn't need them and they add massive latency.
        """
        # Find the last user message
        last_user = ""
        for msg in reversed(messages):
            if msg.role == "user":
                last_user = msg.content
                break

        if not last_user:
            return ""

        # Collect last 2 assistant messages for minimal context
        recent_context: list[str] = []
        for msg in reversed(messages):
            if msg.role == "assistant" and msg.content:
                recent_context.insert(0, msg.content)
                if len(recent_context) >= 2:
                    break

        if recent_context:
            ctx = "\n".join(f"[Previous reply]\n{r}" for r in recent_context)
            return f"{ctx}\n\n[Current question]\n{last_user}"

        return last_user

    def _build_command(self, prompt: str) -> list[str]:
        """Build the CLI command."""
        if self._cli == "claude":
            return [self._binary, "-p", prompt]
        elif self._cli == "codex":
            return [self._binary, "-q", prompt]
        else:
            return [self._binary, prompt]
