"""Provider-agnostic LLM client built on the standard library only.

The *canonical* message format used throughout birkin is the Anthropic
Messages content-block shape::

    {"role": "user"|"assistant", "content": [block, ...]}

where a block is one of::

    {"type": "text", "text": "..."}
    {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
    {"type": "tool_result", "tool_use_id": "...", "content": "...", "is_error": bool}

The Anthropic provider speaks this natively (with SSE streaming). The OpenAI
provider adapts to/from chat-completions function calling (non-streaming).

No third-party packages: requests are made with ``urllib.request``.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

ANTHROPIC_VERSION = "2023-06-01"

# When authenticating with a Claude subscription OAuth token, Anthropic routes
# the request as Claude Code. Custom tools follow the Claude Code / MCP naming
# convention, so birkin's tool names are prefixed on the wire and stripped from
# the response — the agent loop only ever sees the bare names.
_MCP_PREFIX = "mcp_"

# Short model aliases → full API model IDs. The Messages API needs full IDs;
# the REPL/config accept the friendly short names. Unknown values pass through
# unchanged (already a full ID or a custom model string).
_MODEL_ALIASES = {
    "opus": "claude-opus-4-8",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
    "claude-code": "claude-sonnet-4-6",
    "default": "claude-sonnet-4-6",
    "": "claude-sonnet-4-6",
}


def _normalize_model(model: Optional[str]) -> str:
    return _MODEL_ALIASES.get(model or "", model or "claude-sonnet-4-6")


def _mcp_prefix_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a copy of ``messages`` with tool_use names ``mcp_``-prefixed.

    Only assistant messages carrying tool_use blocks are copied; everything else
    is passed through by reference. Keeps the on-wire tool names consistent with
    the (prefixed) tools array for OAuth/Claude Code requests.
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_use" for b in content):
            new_content = []
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    name = b.get("name", "")
                    if name and not name.startswith(_MCP_PREFIX):
                        b = {**b, "name": _MCP_PREFIX + name}
                new_content.append(b)
            out.append({**m, "content": new_content})
        else:
            out.append(m)
    return out


# Streaming callback: receives incremental assistant *text* (not tool args).
StreamCallback = Optional[Callable[[str], None]]


class LLMError(RuntimeError):
    """Raised when the provider call fails after retries."""


class LLMClient:
    def __init__(self, *, provider: str, model: str, api_key: str,
                 base_url: str, max_tokens: int = 4096, temperature: float = 1.0,
                 cli_access: str = "workspace", cli_command: list[str] | None = None,
                 cli_timeout: int = 300, oauth: bool = False):
        self.provider = provider
        self.model = model
        self.api_key = api_key
        # When True, authenticate to the Anthropic Messages API with a Claude
        # subscription OAuth token (Bearer + Claude Code identity) instead of a
        # paid x-api-key. Set for the "claude-oauth" provider. Keeps birkin's own
        # in-process tool loop (no `claude -p` subprocess, so no per-message hooks).
        self.oauth = oauth
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens
        self.temperature = temperature
        # CLI-agent access level: "workspace" (writable, sandboxed) or
        # "full" (dangerous: bypass approvals/sandbox).
        self.cli_access = cli_access
        # argv for the generic "local-cli" provider.
        self.cli_command = list(cli_command or [])
        # Hard cap on a single CLI-agent call (seconds). Kept modest so a hung
        # subprocess (e.g. a blocking Claude Code hook) surfaces fast instead of
        # looking dead for many minutes. Tune via config "cli_timeout".
        self.cli_timeout = int(cli_timeout)

    # -- public API --------------------------------------------------------

    def complete(self, *, system: str, messages: list[dict[str, Any]],
                 tools: Optional[list[dict[str, Any]]] = None,
                 model: Optional[str] = None,
                 on_text: StreamCallback = None) -> dict[str, Any]:
        """Run one assistant turn. Returns a canonical assistant message dict
        ``{"role": "assistant", "content": [...], "stop_reason": str}``.
        """
        model = model or self.model
        if self.provider in ("anthropic", "claude-oauth"):
            return self._anthropic_complete(system, messages, tools, model, on_text)
        if self.provider == "openai":
            return self._openai_complete(system, messages, tools, model, on_text)
        if self.provider in ("claude-cli", "codex-cli", "local-cli"):
            return self._cli_complete(system, messages, model, on_text)
        raise LLMError(f"unknown provider: {self.provider!r}")

    # -- Local CLI agents (Claude Code / Codex) ----------------------------

    @staticmethod
    def _flatten(system: str, messages: list[dict[str, Any]]) -> str:
        """Flatten the conversation into a single prompt for a CLI agent."""
        parts: list[str] = []
        if system:
            parts.append(system)
        for m in messages:
            role = m.get("role", "user").upper()
            blocks = m.get("content", [])
            if isinstance(blocks, str):
                parts.append(f"{role}: {blocks}")
                continue
            for b in blocks:
                if b.get("type") == "text":
                    parts.append(f"{role}: {b.get('text', '')}")
                elif b.get("type") == "tool_result":
                    c = b.get("content", "")
                    parts.append(f"TOOL_RESULT: {c if isinstance(c, str) else c}")
        return "\n\n".join(parts).strip()

    def _cli_complete(self, system, messages, model, on_text) -> dict[str, Any]:
        """Route the turn through a locally-installed agent CLI.

        These CLIs are full agents with their own tools and auth. birkin sends a
        concise CLI system prompt (identity + memory + skills routed to the
        request — built in runtime for CLI providers) plus the conversation, and
        returns the CLI's final reply. The CLI runs its own tools / any bundled
        skill scripts.
        """
        prompt = self._flatten(system, messages)
        if self.provider == "claude-cli":
            text = self._run_claude(prompt, model)
        elif self.provider == "local-cli":
            text = self._run_local_cli(prompt)
        else:  # codex-cli
            text = self._run_codex(prompt, model)
        if on_text and text:
            on_text(text)
        return {"role": "assistant",
                "content": [{"type": "text", "text": text}],
                "stop_reason": "end_turn"}

    def _run_claude(self, prompt: str, model: Optional[str]) -> str:
        # Discrete argv (no shell=True). Writable by default (acceptEdits);
        # "full" bypasses all permission checks.
        from .proc import cli_argv
        parts = ["claude", "-p", "--output-format", "json"]
        if self.cli_access == "full":
            parts.append("--dangerously-skip-permissions")
        else:
            parts += ["--permission-mode", "acceptEdits"]
        if model and model not in ("claude-code", "default", ""):
            parts += ["--model", model]
        try:
            proc = subprocess.run(cli_argv(parts), input=prompt, capture_output=True,
                                  text=True, errors="replace", timeout=self.cli_timeout)
        except subprocess.TimeoutExpired:
            return (f"[birkin] Claude Code timed out after {self.cli_timeout}s. "
                    f"It may be blocked on a Claude Code hook or first-run prompt.")
        out = (proc.stdout or "").strip()
        if out:
            try:
                return str(json.loads(out).get("result") or out)
            except json.JSONDecodeError:
                return out
        return f"[birkin] Claude Code error: {(proc.stderr or '').strip()[:400]}"

    def _run_codex(self, prompt: str, model: Optional[str]) -> str:
        # Discrete argv (no shell=True). `-o` writes ONLY the final assistant
        # message to a file. By default codex uses its own policy
        # (workspace-write); "full" bypasses approvals + sandbox entirely.
        import tempfile

        from .proc import cli_argv
        fd, path = tempfile.mkstemp(suffix="-codex.txt")
        os.close(fd)
        parts = ["codex", "exec", "--skip-git-repo-check", "--color", "never"]
        if self.cli_access == "full":
            parts.append("--dangerously-bypass-approvals-and-sandbox")
        parts += ["-o", path]
        if model and model not in ("codex", "default", ""):
            parts += ["-m", model]
        try:
            proc = subprocess.run(cli_argv(parts), input=prompt, capture_output=True,
                                  text=True, errors="replace", timeout=self.cli_timeout)
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read().strip()
            except OSError:
                text = ""
        except subprocess.TimeoutExpired:
            return f"[birkin] Codex timed out after {self.cli_timeout}s."
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        if text:
            return text
        err = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        return f"[birkin] Codex produced no message. {err[:400]}"

    def _run_local_cli(self, prompt: str) -> str:
        # Generic configured CLI runner: argv from config.cli_command, prompt on
        # stdin, stdout is the reply. Lets any local agent/model be a backend.
        from .proc import cli_argv
        if not self.cli_command:
            return ("[birkin] No cli_command configured. Set config.cli_command "
                    "to an argv list, e.g. [\"my-llm\", \"--flag\"].")
        try:
            proc = subprocess.run(cli_argv(self.cli_command), input=prompt,
                                  capture_output=True, text=True, errors="replace",
                                  timeout=self.cli_timeout)
        except FileNotFoundError:
            return f"[birkin] command not found: {self.cli_command[0]}"
        except subprocess.TimeoutExpired:
            return f"[birkin] local CLI timed out after {self.cli_timeout}s."
        out = (proc.stdout or "").strip()
        if out:
            return out
        return f"[birkin] local CLI no output. {(proc.stderr or '').strip()[:400]}"

    # -- HTTP --------------------------------------------------------------

    def _post(self, url: str, headers: dict[str, str], payload: dict[str, Any],
              *, stream: bool, timeout: float = 300.0):
        data = json.dumps(payload).encode("utf-8")
        last_exc: Exception | None = None
        for attempt in range(4):
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            try:
                resp = urllib.request.urlopen(req, timeout=timeout)
                return resp  # caller reads (stream) or .read()
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")
                # Retry on rate-limit / transient server errors.
                if exc.code in (429, 500, 502, 503, 529) and attempt < 3:
                    backoff = 2 ** attempt
                    time.sleep(backoff)
                    last_exc = LLMError(f"HTTP {exc.code}: {body[:500]}")
                    continue
                raise LLMError(f"HTTP {exc.code}: {body[:1000]}") from exc
            except urllib.error.URLError as exc:
                if attempt < 3:
                    time.sleep(2 ** attempt)
                    last_exc = LLMError(f"network error: {exc.reason}")
                    continue
                raise LLMError(f"network error: {exc.reason}") from exc
        raise last_exc or LLMError("request failed")

    # -- Anthropic ---------------------------------------------------------

    def _anthropic_complete(self, system, messages, tools, model, on_text):
        url = f"{self.base_url}/v1/messages"
        headers = {
            "content-type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        model = _normalize_model(model)

        if self.oauth:
            from . import oauth as _oauth
            token = _oauth.resolve_token() or (
                self.api_key if _oauth.is_oauth_token(self.api_key) else None)
            if not token:
                raise LLMError(
                    "Not logged in to Claude. Run `claude /login` (or "
                    "`claude setup-token`) so birkin can use your subscription, "
                    "then retry.")
            headers.update(_oauth.auth_headers(token))
            # OAuth requires the Claude Code identity as the FIRST system block.
            system_blocks: list[dict[str, Any]] = [
                {"type": "text", "text": _oauth.CLAUDE_CODE_SYSTEM_PREFIX}]
            if system:
                system_blocks.append({"type": "text", "text": system,
                                      "cache_control": {"type": "ephemeral"}})
            else:
                system_blocks[0]["cache_control"] = {"type": "ephemeral"}
            messages = _mcp_prefix_messages(messages)
        else:
            headers["x-api-key"] = self.api_key
            # System as a cacheable block (prompt caching improves repeat-turn cost).
            system_blocks = [{"type": "text", "text": system,
                              "cache_control": {"type": "ephemeral"}}] if system else []

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": system_blocks,
            "messages": messages,
            "stream": True,
        }
        if tools:
            t = [dict(x) for x in tools]
            if self.oauth:
                for spec in t:
                    name = spec.get("name", "")
                    if name and not name.startswith(_MCP_PREFIX):
                        spec["name"] = _MCP_PREFIX + name
            t[-1]["cache_control"] = {"type": "ephemeral"}  # cache the tool list too
            payload["tools"] = t

        resp = self._post(url, headers, payload, stream=True)
        result = self._read_anthropic_stream(resp, on_text)
        if self.oauth:
            # Strip the mcp_ prefix so the agent's registry dispatches normally.
            for b in result.get("content", []):
                if b.get("type") == "tool_use":
                    name = b.get("name") or ""
                    if name.startswith(_MCP_PREFIX):
                        b["name"] = name[len(_MCP_PREFIX):]
        return result

    @staticmethod
    def _read_anthropic_stream(resp, on_text) -> dict[str, Any]:
        # Blocks are tracked by their stream ``index`` (not "last appended"), so
        # multiple/parallel tool_use blocks accumulate their JSON correctly.
        content: list[dict[str, Any]] = []
        stop_reason = "end_turn"
        json_parts: dict[int, list[str]] = {}

        def ensure(idx: int) -> None:
            while len(content) <= idx:
                content.append({"type": "text", "text": ""})

        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if not data:
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            etype = event.get("type")

            if etype == "content_block_start":
                idx = event.get("index", len(content))
                ensure(idx)
                block = event.get("content_block", {})
                if block.get("type") == "tool_use":
                    content[idx] = {"type": "tool_use", "id": block.get("id"),
                                    "name": block.get("name"), "input": {}}
                    json_parts[idx] = []
                else:
                    content[idx] = {"type": "text", "text": ""}
            elif etype == "content_block_delta":
                idx = event.get("index", len(content) - 1)
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    piece = delta.get("text", "")
                    if 0 <= idx < len(content) and content[idx].get("type") == "text":
                        content[idx]["text"] += piece
                    if on_text and piece:
                        on_text(piece)
                elif delta.get("type") == "input_json_delta":
                    json_parts.setdefault(idx, []).append(delta.get("partial_json", ""))
            elif etype == "content_block_stop":
                idx = event.get("index")
                if idx is not None and 0 <= idx < len(content) \
                        and content[idx].get("type") == "tool_use":
                    raw_json = "".join(json_parts.get(idx, [])).strip()
                    try:
                        content[idx]["input"] = json.loads(raw_json) if raw_json else {}
                    except json.JSONDecodeError:
                        content[idx]["input"] = {}
            elif etype == "message_delta":
                sr = event.get("delta", {}).get("stop_reason")
                if sr:
                    stop_reason = sr
            elif etype == "error":
                msg = event.get("error", {}).get("message", "stream error")
                raise LLMError(f"anthropic stream error: {msg}")
            # message_start / message_stop / ping: ignored

        # Drop any empty trailing text blocks we pre-allocated but never filled.
        content = [b for b in content
                   if not (b.get("type") == "text" and not b.get("text"))]
        return {"role": "assistant", "content": content, "stop_reason": stop_reason}

    # -- OpenAI-compatible (non-streaming adapter) -------------------------

    def _openai_complete(self, system, messages, tools, model, on_text):
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.api_key}",
        }
        oai_messages = _to_openai_messages(system, messages)
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": oai_messages,
        }
        if tools:
            payload["tools"] = [{
                "type": "function",
                "function": {"name": t["name"], "description": t.get("description", ""),
                             "parameters": t.get("input_schema", {})},
            } for t in tools]

        resp = self._post(url, headers, payload, stream=False)
        body = json.loads(resp.read().decode("utf-8", "replace"))
        choice = body["choices"][0]
        msg = choice.get("message", {})
        content: list[dict[str, Any]] = []
        text = msg.get("content") or ""
        if text:
            content.append({"type": "text", "text": text})
            if on_text:
                on_text(text)
        for call in msg.get("tool_calls", []) or []:
            fn = call.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            content.append({"type": "tool_use", "id": call.get("id"),
                            "name": fn.get("name"), "input": args})
        finish = choice.get("finish_reason", "stop")
        stop_reason = "tool_use" if finish == "tool_calls" else "end_turn"
        return {"role": "assistant", "content": content, "stop_reason": stop_reason}


def _to_openai_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map canonical content-block messages to OpenAI chat-completions shape."""
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        role = m["role"]
        blocks = m["content"] if isinstance(m["content"], list) else [
            {"type": "text", "text": m["content"]}]
        if role == "assistant":
            text_parts, tool_calls = [], []
            for b in blocks:
                if b["type"] == "text":
                    text_parts.append(b["text"])
                elif b["type"] == "tool_use":
                    tool_calls.append({"id": b["id"], "type": "function",
                                       "function": {"name": b["name"],
                                                    "arguments": json.dumps(b.get("input", {}))}})
            entry: dict[str, Any] = {"role": "assistant",
                                     "content": "\n".join(text_parts) or None}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            out.append(entry)
        else:  # user
            tool_results = [b for b in blocks if b["type"] == "tool_result"]
            if tool_results:
                for tr in tool_results:
                    out.append({"role": "tool", "tool_call_id": tr["tool_use_id"],
                                "content": _stringify(tr.get("content", ""))})
            text_parts = [b["text"] for b in blocks if b["type"] == "text"]
            if text_parts:
                out.append({"role": "user", "content": "\n".join(text_parts)})
    return out


def _stringify(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") if isinstance(b, dict) else str(b)
                         for b in content)
    return str(content)


def build_client(cfg: dict[str, Any], api_key: str) -> LLMClient:
    from .config import OAUTH_PROVIDERS, resolve_base_url
    provider = cfg.get("provider", "anthropic")
    return LLMClient(
        provider=provider,
        model=cfg.get("model", "claude-sonnet-4-6"),
        api_key=api_key,
        base_url=resolve_base_url(cfg),
        max_tokens=int(cfg.get("max_tokens", 4096)),
        temperature=float(cfg.get("temperature", 1.0)),
        cli_access=cfg.get("cli_access", "workspace"),
        cli_command=cfg.get("cli_command", []),
        cli_timeout=int(cfg.get("cli_timeout", 300)),
        oauth=provider in OAUTH_PROVIDERS,
    )
