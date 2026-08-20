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
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
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
    """Raised when the provider call fails after retries.

    Carries the HTTP ``status`` (when the failure came from one) and a coarse
    ``kind`` so callers can react without re-parsing the message string:
    failover picks a fallback model for transient/auth failures, and the
    compactor retries after shrinking history on ``overflow``.
    """

    def __init__(self, message: str, *, status: Optional[int] = None,
                 kind: str = "unknown"):
        super().__init__(message)
        self.status = status
        self.kind = kind


# Kinds worth trying a different provider/model for. "client" (a malformed or
# oversized request) is deliberately absent — a different model won't fix it.
FAILOVER_KINDS = frozenset({"auth", "billing", "rate_limit", "server", "network"})


def _kind_for_status(code: int, body: str = "") -> str:
    """Map an HTTP status to a coarse failure kind.

    ponytail: status codes only. First-party Anthropic/OpenAI APIs return
    honest codes, so hermes' ~500 lines of message-pattern matching buys
    nothing here. The one exception is 400, which Anthropic uses for context
    overflow as well as for genuine request bugs — hence the body sniff.
    """
    if code in (401, 403):
        return "auth"
    if code == 402:
        return "billing"
    if code == 429:
        return "rate_limit"
    if code >= 500:
        return "server"
    if code == 413 or (code == 400 and _looks_like_overflow(body)):
        return "overflow"
    return "client"


_OVERFLOW_MARKERS = (
    "prompt is too long", "context length", "context window", "context_length",
    "input length", "too many tokens", "maximum context",
)


def _transport_for(provider: str) -> str:
    """Map a provider id to its wire transport.

    Returns "" for unknown provider ids (complete() raises LLMError), and
    "openai_chat" only for the built-in openai provider. Named config
    providers (``providers:``) get their transport from the entry via
    ``_plain_client``.
    """
    if provider in ("anthropic", "claude-oauth"):
        return "anthropic_messages"
    if provider in ("claude-cli", "codex-cli", "local-cli"):
        return "cli"
    if provider in ("openai", "gemini", "nvidia", "freellmapi"):
        # gemini/nvidia/freellmapi all expose OpenAI Chat Completions; their
        # differences are base_url + key env, both in birkin.config.
        return "openai_chat"
    return ""


def _looks_like_overflow(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _OVERFLOW_MARKERS)


class LLMClient:
    def __init__(self, *, provider: str, model: str, api_key: str,
                 base_url: str, max_tokens: int = 4096, temperature: float = 1.0,
                 cli_access: str = "workspace", cli_command: list[str] | None = None,
                 cli_timeout: int = 300, oauth: bool = False,
                 cli_network_access: bool = False,
                 egress_enforced: bool = False,
                 transport: str = ""):
        self.provider = provider
        self.model = model
        self.api_key = api_key
        # Optional status sink for transient conditions (retry/backoff) so a
        # stalled turn is explained rather than silent (P1-3). Defaults to a
        # server-log print; a surface can set it to reach the user.
        self._status: Callable[[str], None] | None = None
        # When True, authenticate to the Anthropic Messages API with a Claude
        # subscription OAuth token (Bearer + Claude Code identity) instead of a
        # paid x-api-key. Set for the "claude-oauth" provider. Keeps birkin's own
        # in-process tool loop (no `claude -p` subprocess, so no per-message hooks).
        self.oauth = oauth
        # Effective wire transport for named (config ``providers:``) providers:
        # "openai_chat" | "anthropic_messages" | "cli". Empty = derive from
        # ``provider`` below.
        self.transport = transport or _transport_for(provider)
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens
        self.temperature = temperature
        # CLI-agent access level: "workspace" (writable, sandboxed) or
        # "full" (dangerous: bypass approvals/sandbox).
        self.cli_access = cli_access
        self.cli_network_access = cli_network_access
        self.egress_enforced = bool(egress_enforced)
        # argv for the generic "local-cli" provider.
        self.cli_command = list(cli_command or [])
        # Hard cap on a single CLI-agent call (seconds). Kept modest so a hung
        # subprocess (e.g. a blocking Claude Code hook) surfaces fast instead of
        # looking dead for many minutes. Tune via config "cli_timeout".
        self.cli_timeout = int(cli_timeout)
        self.birkin_mcp = False
        self.birkin_mcp_scope = "full"

    # -- public API --------------------------------------------------------

    def complete(self, *, system: str, messages: list[dict[str, Any]],
                 tools: Optional[list[dict[str, Any]]] = None,
                 model: Optional[str] = None,
                 on_text: StreamCallback = None,
                 abort: Optional[Any] = None) -> dict[str, Any]:
        """Run one assistant turn. Returns a canonical assistant message dict
        ``{"role": "assistant", "content": [...], "stop_reason": str}``.

        ``abort`` (anything with ``is_set()``) interrupts: the Anthropic stream
        stops between SSE events and a CLI subprocess is killed (Esc in the REPL).
        """
        model = model or self.model
        if self.transport == "anthropic_messages":
            return self._anthropic_complete(system, messages, tools, model, on_text, abort)
        if self.transport == "openai_chat":
            return self._openai_complete(system, messages, tools, model, on_text, abort)
        if self.transport == "cli":
            return self._cli_complete(system, messages, model, on_text, abort)
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
                    parts.append(f"TOOL_RESULT: {_stringify(c)}")
        return "\n\n".join(parts).strip()

    def _cli_complete(self, system, messages, model, on_text,
                      abort=None) -> dict[str, Any]:
        """Route the turn through a locally-installed agent CLI.

        These CLIs are full agents with their own tools and auth. birkin sends a
        concise CLI system prompt (identity + memory + skills routed to the
        request — built in runtime for CLI providers) plus the conversation, and
        returns the CLI's final reply. The CLI runs its own tools / any bundled
        skill scripts. ``abort`` kills the subprocess (Esc in the REPL).
        """
        prompt = self._flatten(system, messages)
        if self.provider == "claude-cli":
            # claude streams incrementally via on_text inside _run_claude.
            text, streamed = self._run_claude(prompt, model, abort, on_text)
        elif self.provider == "local-cli":
            text, streamed = self._run_local_cli(prompt, abort), False
        else:  # codex-cli — output captured from a file only after exit
            text, streamed = self._run_codex(prompt, model, abort), False
        if on_text and text and not streamed:
            on_text(text)
        return {"role": "assistant",
                "content": [{"type": "text", "text": text}],
                "stop_reason": "end_turn"}

    def _run_cli_capture(self, argv: list[str], prompt: str, abort=None,
                         env: Optional[dict[str, str]] = None,
                         on_line: Optional[Callable[[str], None]] = None
                         ) -> tuple[str, str, bool, bool]:
        """Run ``argv`` feeding ``prompt`` on stdin; capture stdout/stderr.

        Uses Popen + drain threads (no pipe-buffer deadlock) and polls so the
        child is KILLED on ``abort`` (Esc) or ``cli_timeout``. ``env`` overrides
        the child environment (defaults to inheriting the parent). ``on_line``,
        if given, is called with each stdout line AS IT ARRIVES (from the drain
        thread) so a caller can stream incrementally; stdout is still buffered
        and returned for fallback parsing. Returns
        ``(stdout, stderr, timed_out, aborted)``."""
        import threading

        from .proc import kill_tree, popen_tree_kwargs
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                errors="replace", env=env,
                                **popen_tree_kwargs())
        chunks: dict[str, list[str]] = {"out": [], "err": []}

        def _drain(stream, key: str) -> None:
            try:
                for line in stream:
                    chunks[key].append(line)
                    if on_line is not None and key == "out":
                        try:
                            on_line(line)
                        except Exception:
                            pass
            except Exception:
                pass

        def _feed() -> None:
            try:
                if prompt and proc.stdin:
                    proc.stdin.write(prompt)
            except Exception:
                pass
            finally:
                try:
                    if proc.stdin:
                        proc.stdin.close()
                except Exception:
                    pass

        threads = [threading.Thread(target=_drain, args=(proc.stdout, "out"), daemon=True),
                   threading.Thread(target=_drain, args=(proc.stderr, "err"), daemon=True),
                   threading.Thread(target=_feed, daemon=True)]
        for t in threads:
            t.start()
        deadline = time.monotonic() + self.cli_timeout
        timed_out = aborted = False
        while proc.poll() is None:
            if abort is not None and abort.is_set():
                aborted = True
                break
            if time.monotonic() > deadline:
                timed_out = True
                break
            time.sleep(0.05)
        if timed_out or aborted:
            kill_tree(proc)
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
        for t in threads:
            t.join(timeout=1)
        return "".join(chunks["out"]), "".join(chunks["err"]), timed_out, aborted

    def _run_claude(self, prompt: str, model: Optional[str], abort=None,
                    on_text: StreamCallback = None) -> tuple[str, bool]:
        """Run ``claude -p`` and stream its reply. Returns ``(text, streamed)``.

        Uses ``--output-format stream-json`` so Claude Code emits a JSONL event
        stream as it works; the parser forwards assistant text deltas to
        ``on_text`` the instant they arrive instead of waiting for the process
        to exit. ``streamed`` is True when at least one delta was forwarded (so
        the caller knows not to re-print the reply). Falls back to the final
        ``result`` text when a claude too old for partial messages emits no
        deltas — preserving the old print-once behavior.
        """
        # Discrete argv (no shell=True). Writable by default (acceptEdits);
        # "full" bypasses all permission checks.
        from .proc import claude_child_env, cli_argv
        parts = ["claude", "-p", "--output-format", "stream-json", "--verbose",
                 "--include-partial-messages"]
        mcp_path: str | None = None
        if self.egress_enforced:
            from .claude_session import enforced_egress_args
            from .mcp_server import write_mcp_config

            fd, mcp_path = tempfile.mkstemp(suffix="-birkin-mcp.json")
            os.close(fd)
            try:
                mcp_path = str(
                    write_mcp_config(Path(mcp_path), model=model))
            except Exception:
                os.unlink(mcp_path)
                raise
            parts += ["--mcp-config", mcp_path]
            parts.extend(enforced_egress_args())
        elif self.cli_access == "full":
            parts.append("--dangerously-skip-permissions")
        elif self.cli_access == "read-only":
            parts += ["--safe-mode", "--tools", "",
                      "--no-session-persistence"]
        else:
            parts += ["--permission-mode", "acceptEdits"]
        if model and model not in ("claude-code", "default", ""):
            parts += ["--model", model]

        st: dict[str, Any] = {"delta": [], "result": None, "assistant": [],
                              "streamed": False}

        def _on_line(line: str) -> None:
            line = line.strip()
            if not line:
                return
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                return  # non-JSON log line — skip
            typ = obj.get("type")
            if typ == "stream_event":
                ev = obj.get("event") or {}
                if ev.get("type") == "content_block_delta":
                    delta = ev.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        piece = delta.get("text") or ""
                        if piece:
                            st["delta"].append(piece)
                            st["streamed"] = True
                            if on_text:
                                on_text(piece)
            elif typ == "assistant":
                for block in (obj.get("message") or {}).get("content") or []:
                    if block.get("type") == "text" and block.get("text"):
                        st["assistant"].append(block["text"])
            elif typ == "result":
                res = obj.get("result")
                if isinstance(res, str):
                    st["result"] = res

        try:
            stdout, stderr, timed_out, aborted = self._run_cli_capture(
                cli_argv(parts), prompt, abort, env=claude_child_env(),
                on_line=_on_line)
        except FileNotFoundError:
            return "[birkin] command not found: claude", False
        finally:
            if mcp_path:
                try:
                    os.unlink(mcp_path)
                except FileNotFoundError:
                    pass

        streamed_text = "".join(st["delta"])
        if aborted:
            return (streamed_text, True) if streamed_text else ("[birkin] (aborted)", False)
        if timed_out:
            if streamed_text:
                return streamed_text, True
            return (f"[birkin] Claude Code timed out after {self.cli_timeout}s. "
                    f"It may be blocked on a Claude Code hook or first-run prompt."), False
        if st["streamed"]:
            return streamed_text, True
        # No token deltas (claude too old for --include-partial-messages, or a
        # non-streaming build): fall back to the final result / assistant text.
        if st["result"]:
            return st["result"], False
        if st["assistant"]:
            return "\n".join(st["assistant"]), False
        out = (stdout or "").strip()
        if out:
            try:  # tolerate a single-object json blob (older --output-format)
                return str(json.loads(out).get("result") or out), False
            except json.JSONDecodeError:
                return out, False
        return f"[birkin] Claude Code error: {(stderr or '').strip()[:400]}", False

    def _run_codex(self, prompt: str, model: Optional[str], abort=None) -> str:
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
        elif self.cli_access == "read-only":
            parts += ["--sandbox", "read-only", "--ephemeral",
                      "--ignore-user-config", "--ignore-rules",
                      "-c", "sandbox_workspace_write.network_access=false"]
        else:
            parts += [
                "--sandbox", "workspace-write",
                "-c",
                "sandbox_workspace_write.network_access="
                f"{str(self.cli_network_access is True).lower()}",
            ]
        parts += ["-o", path]
        if model and model not in ("codex", "default", ""):
            parts += ["-m", model]
        if self.birkin_mcp:
            from .mcp_server import codex_config_args
            parts += codex_config_args(
                scope=self.birkin_mcp_scope,
                model=model,
            )
        try:
            stdout, stderr, timed_out, aborted = self._run_cli_capture(
                cli_argv(parts), prompt, abort)
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read().strip()
            except OSError:
                text = ""
        except FileNotFoundError:
            return "[birkin] command not found: codex"
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        if aborted:
            return "[birkin] (aborted)"
        if timed_out:
            # kind="timeout" (not in FAILOVER_KINDS): a CLI provider's own
            # subprocess stalling is not something a fallback API model fixes.
            raise LLMError(f"Codex timed out after {self.cli_timeout}s.",
                           kind="timeout")
        if text:
            return text
        err = (stderr or "").strip() or (stdout or "").strip()
        return f"[birkin] Codex produced no message. {err[:400]}"

    def _run_local_cli(self, prompt: str, abort=None) -> str:
        # Generic configured CLI runner: argv from config.cli_command, prompt on
        # stdin, stdout is the reply. Lets any local agent/model be a backend.
        from .proc import cli_argv
        if not self.cli_command:
            return ("[birkin] No cli_command configured. Set config.cli_command "
                    "to an argv list, e.g. [\"my-llm\", \"--flag\"].")
        try:
            stdout, stderr, timed_out, aborted = self._run_cli_capture(
                cli_argv(self.cli_command), prompt, abort)
        except FileNotFoundError:
            return f"[birkin] command not found: {self.cli_command[0]}"
        if aborted:
            return "[birkin] (aborted)"
        if timed_out:
            return f"[birkin] local CLI timed out after {self.cli_timeout}s."
        out = (stdout or "").strip()
        if out:
            return out
        return f"[birkin] local CLI no output. {(stderr or '').strip()[:400]}"

    # -- HTTP --------------------------------------------------------------

    def _post(self, url: str, headers: dict[str, str], payload: dict[str, Any],
              *, stream: bool, timeout: float = 300.0):
        data = json.dumps(payload).encode("utf-8")
        last_exc: Exception | None = None

        def _wait(why: str, attempt: int) -> None:
            # Surface the backoff so a stalled turn is explained, not silent
            # (P1-3): a rate-limited retry otherwise looks like a frozen turn.
            backoff = 2 ** attempt
            if self._status is not None:
                self._status(f"{why} — retrying in {backoff}s ({attempt + 2}/4)")
            else:
                print(f"[birkin] {why} — retrying in {backoff}s "
                      f"({attempt + 2}/4)", flush=True)
            time.sleep(backoff)

        for attempt in range(4):
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            try:
                resp = urllib.request.urlopen(req, timeout=timeout)
                return resp  # caller reads (stream) or .read()
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")
                kind = _kind_for_status(exc.code, body)
                # Retry on rate-limit / transient server errors.
                if exc.code in (429, 500, 502, 503, 529) and attempt < 3:
                    _wait(f"rate-limited (HTTP {exc.code})" if exc.code == 429
                          else f"server error (HTTP {exc.code})", attempt)
                    last_exc = LLMError(f"HTTP {exc.code}: {body[:500]}",
                                        status=exc.code, kind=kind)
                    continue
                raise LLMError(f"HTTP {exc.code}: {body[:1000]}",
                               status=exc.code, kind=kind) from exc
            except urllib.error.URLError as exc:
                if attempt < 3:
                    _wait(f"network error ({exc.reason})", attempt)
                    last_exc = LLMError(f"network error: {exc.reason}",
                                        kind="network")
                    continue
                raise LLMError(f"network error: {exc.reason}",
                               kind="network") from exc
        raise last_exc or LLMError("request failed")

    # -- Anthropic ---------------------------------------------------------

    def _anthropic_complete(self, system, messages, tools, model, on_text, abort=None):
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
                    "then retry.", kind="auth")
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
        result = self._read_anthropic_stream(resp, on_text, abort)
        if self.oauth:
            # Strip the mcp_ prefix so the agent's registry dispatches normally.
            # Rebuild immutably — a caller (retry/audit) may still hold the
            # original blocks, and mutating them in place would corrupt those.
            result = {**result, "content": [
                {**b, "name": (b.get("name") or "")[len(_MCP_PREFIX):]}
                if b.get("type") == "tool_use"
                and (b.get("name") or "").startswith(_MCP_PREFIX)
                else b
                for b in result.get("content", [])
            ]}
        return result

    @staticmethod
    def _read_anthropic_stream(resp, on_text, abort=None) -> dict[str, Any]:
        # Blocks are tracked by their stream ``index`` (not "last appended"), so
        # multiple/parallel tool_use blocks accumulate their JSON correctly.
        content: list[dict[str, Any]] = []
        stop_reason = "end_turn"
        json_parts: dict[int, list[str]] = {}

        def ensure(idx: int) -> None:
            while len(content) <= idx:
                content.append({"type": "text", "text": ""})

        for raw in resp:
            if abort is not None and abort.is_set():
                # Esc / interrupt — stop consuming the stream and return what we
                # have so far (the agent loop sees this and stops too).
                try:
                    resp.close()
                except Exception:
                    pass
                stop_reason = "aborted"
                break
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
                raise LLMError(
                    f"anthropic stream error: {msg}",
                    kind="overflow" if _looks_like_overflow(msg) else "server")
            # message_start / message_stop / ping: ignored

        # Drop any empty trailing text blocks we pre-allocated but never filled.
        content = [b for b in content
                   if not (b.get("type") == "text" and not b.get("text"))]
        return {"role": "assistant", "content": content, "stop_reason": stop_reason}

    # -- OpenAI-compatible (non-streaming adapter) -------------------------

    def _openai_complete(self, system, messages, tools, model, on_text,
                         abort=None):
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

        if on_text is not None:
            # Stream token deltas (first tokens at model latency, like the
            # Anthropic path) — a text-only turn is the common case; tool
            # calls still stream and are reassembled by index.
            payload["stream"] = True
            resp = self._post(url, headers, payload, stream=True)
            return self._read_openai_stream(resp, on_text, abort)
        resp = self._post(url, headers, payload, stream=False)
        body = json.loads(resp.read().decode("utf-8", "replace"))
        choices = body.get("choices") or []
        if not choices:  # content-filter / billing block / odd 3rd-party server
            raise LLMError(f"OpenAI response had no choices: {str(body)[:300]}")
        choice = choices[0]
        msg = choice.get("message", {})
        from . import reasoning as _reasoning  # local import avoids cycles
        extracted = _reasoning.extract_reasoning(msg)
        content: list[dict[str, Any]] = []
        text = msg.get("content") or ""
        if text:
            text = _reasoning.strip_think_blocks(text)
        if text:
            content.append({"type": "text", "text": text})
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
        out: dict[str, Any] = {"role": "assistant", "content": content,
                               "stop_reason": stop_reason}
        if extracted:
            out["reasoning"] = extracted
        return out

    @staticmethod
    def _read_openai_stream(resp, on_text, abort=None) -> dict[str, Any]:
        """Parse an OpenAI chat-completions SSE stream into the canonical
        assistant message. Text deltas forward to on_text as they arrive;
        tool_call deltas accumulate by their ``index`` (name arrives once,
        arguments stream as JSON fragments)."""
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tools: dict[int, dict[str, Any]] = {}     # index -> {id,name,args}
        finish = "stop"
        for raw in resp:
            if abort is not None and abort.is_set():
                try:
                    resp.close()
                except Exception:
                    pass
                finish = "aborted"
                break
            line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) \
                else raw
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if not data or data == "[DONE]":
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = event.get("choices") or []
            if not choices:
                continue
            ch = choices[0]
            delta = ch.get("delta") or {}
            piece = delta.get("content")
            if piece:
                text_parts.append(piece)
                on_text(piece)
            for _rkey in ("reasoning", "reasoning_content"):
                _rpiece = delta.get(_rkey)
                if _rpiece:
                    reasoning_parts.append(_rpiece)
            for tc in delta.get("tool_calls") or []:
                # OpenAI always sends 'index'; a non-strict proxy/local server
                # might not. Fall back to the tool_call id, then to a fresh
                # slot per new call — never collapse distinct calls into 0.
                idx = tc.get("index")
                if idx is None:
                    idx = tc.get("id") or f"_pos{len(tools)}"
                slot = tools.setdefault(idx, {"id": None, "name": None,
                                              "args": []})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["args"].append(fn["arguments"])
            if ch.get("finish_reason"):
                finish = ch["finish_reason"]
        from . import reasoning as _reasoning  # local import avoids cycles
        content: list[dict[str, Any]] = []
        raw = "".join(text_parts)
        joined = _reasoning.strip_think_blocks(raw) if raw else ""
        if joined:
            content.append({"type": "text", "text": joined})
        # dict preserves insertion (arrival) order — don't sort, since keys may
        # now mix int indices and str-id fallbacks, which sorted() can't compare.
        for slot in tools.values():
            try:
                args = json.loads("".join(slot["args"]) or "{}")
            except json.JSONDecodeError:
                args = {}
            content.append({"type": "tool_use", "id": slot["id"],
                            "name": slot["name"], "input": args})
        stop_reason = ("aborted" if finish == "aborted"
                       else "tool_use" if finish == "tool_calls"
                       else "end_turn")
        out: dict[str, Any] = {"role": "assistant", "content": content,
                               "stop_reason": stop_reason}
        extracted = ("\n".join(reasoning_parts) if reasoning_parts
                     else _reasoning.extract_reasoning({"content": raw}))
        if extracted:
            out["reasoning"] = extracted
        return out


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
            parts: list[dict[str, Any]] = []
            has_image = False
            for b in blocks:
                if b["type"] == "text":
                    parts.append({"type": "text", "text": b["text"]})
                elif b["type"] == "image":
                    part = _openai_image_part(b)
                    if part is not None:
                        parts.append(part)
                        has_image = True
            if parts:
                # Text-only stays a plain string — the shape every non-vision
                # OpenAI-compatible endpoint accepts.
                content: Any = parts if has_image else "\n".join(
                    p["text"] for p in parts)
                out.append({"role": "user", "content": content})
    return out


def _openai_image_part(block: dict[str, Any]) -> dict[str, Any] | None:
    """Anthropic image block → OpenAI ``image_url`` part, ``None`` if unusable.

    A malformed attachment is skipped rather than raised on: dropping one image
    is recoverable, killing the turn is not.
    """
    source = block.get("source")
    if not isinstance(source, dict):
        return None
    kind = source.get("type")
    if kind == "base64":
        media_type = str(source.get("media_type") or "").strip()
        data = source.get("data")
        if not media_type or not isinstance(data, str) or not data:
            return None
        url = f"data:{media_type};base64,{data}"
    elif kind == "url":
        url = str(source.get("url") or "").strip()
        if not url:
            return None
    else:
        return None
    return {"type": "image_url", "image_url": {"url": url}}


def _stringify(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") if isinstance(b, dict) else str(b)
                         for b in content)
    return str(content)


def _plain_client(cfg: dict[str, Any], api_key: str) -> LLMClient:
    from .config import OAUTH_PROVIDERS, _named_provider, resolve_base_url
    provider = cfg.get("provider", "anthropic")
    # A hermes-style named provider from config ``providers:`` routes through
    # the OpenAI-compatible transport unless the entry says otherwise. Keep
    # the original provider id on the client (labels, failover) while the
    # transport decision below uses the effective API kind.
    named = _named_provider(cfg, provider)
    transport = ""
    if named:
        # Named config providers default to the OpenAI-compatible transport
        # unless the entry says otherwise.
        transport = str(named.get("transport") or "openai_chat")
    egress_cfg = cfg.get("egress", {})
    egress_enforced = (
        isinstance(egress_cfg, dict)
        and bool(egress_cfg)
        and bool(egress_cfg.get("enabled", True))
        and bool(egress_cfg.get("enforced", True))
    )
    return LLMClient(
        provider=provider,
        model=cfg.get("model", "claude-sonnet-4-6"),
        api_key=api_key,
        base_url=resolve_base_url(cfg),
        max_tokens=int(cfg.get("max_tokens", 4096)),
        temperature=float(cfg.get("temperature", 1.0)),
        cli_access=cfg.get("cli_access", "workspace"),
        cli_network_access=cfg.get("cli_network_access", False) is True,
        egress_enforced=egress_enforced,
        cli_command=cfg.get("cli_command", []),
        cli_timeout=int(cfg.get("cli_timeout", 300)),
        oauth=provider in OAUTH_PROVIDERS,
        transport=transport,
    )


def build_client(cfg: dict[str, Any], api_key: str) -> Any:
    """Build the client for ``cfg``, wrapped for rotation and failover.

    Order matters. The credential pool sits INSIDE the failover wrapper, so a
    rate-limited account spends its own remaining keys before the turn moves to
    a different provider on a different model.
    """
    primary: Any = _plain_client(cfg, api_key)
    from . import credpool
    pool = credpool.from_config(cfg, api_key)
    if pool is not None:
        primary = credpool.RotatingClient(
            pool, lambda key: _plain_client(cfg, key))
    return _maybe_wrap_failover(cfg, primary)


def _fallback_specs(cfg: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Ordered ``(provider, model, base_url)`` fallbacks, best first.

    The legacy single fallback (``fallback_provider`` / ``fallback_model``)
    stays the first hop so existing configs keep their exact behavior, and
    ``fallback_chain`` extends past it. Entries the model layer cannot use —
    not a mapping, missing provider or model — are dropped here rather than
    exploding later, because a typo in one chain entry must not cost the daemon
    every remaining fallback.
    """
    specs: list[tuple[str, str, str]] = []
    provider = (cfg.get("fallback_provider") or "").strip()
    model = (cfg.get("fallback_model") or "").strip()
    if provider and model:
        specs.append((provider, model, str(cfg.get("fallback_base_url") or "")))
    raw = cfg.get("fallback_chain")
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            entry_provider = str(entry.get("provider") or "").strip()
            entry_model = str(entry.get("model") or "").strip()
            if entry_provider and entry_model:
                specs.append((entry_provider, entry_model,
                              str(entry.get("base_url") or "")))
    return specs


def _maybe_wrap_failover(cfg: dict[str, Any], primary: Any) -> Any:
    """Wrap ``primary`` in an ordered chain of FailoverClients.

    The chain is a right-fold of the existing two-client wrapper: with models
    A -> B -> C the result is ``Failover(A, Failover(B, C))``, so every hop
    keeps its own independent cooldown and ``failover.py`` needs no changes.

    Returns ``primary`` untouched — with a warning — whenever no fallback can
    actually serve, so a misconfiguration degrades to today's behavior instead
    of failing at the worst moment.
    """
    from .config import CLI_PROVIDERS, get_api_key

    specs = _fallback_specs(cfg)
    if not specs:
        return primary

    if primary.provider in CLI_PROVIDERS:
        # A CLI provider reports failures as reply *text*, not exceptions, so
        # there is nothing for the wrapper to catch.
        print(f"[birkin] fallback_model is ignored for provider "
              f"{primary.provider!r} (CLI agents handle their own errors).",
              flush=True)
        return primary

    clients: list[Any] = []
    seen = {(primary.provider, primary.model)}
    for provider, model, base_url in specs:
        if (provider, model) in seen:
            continue
        fb_cfg = {**cfg, "provider": provider, "model": model,
                  "base_url": base_url}
        key = get_api_key(fb_cfg)
        if not key:
            print(f"[birkin] fallback {provider}/{model} has no credentials — "
                  f"skipping it.", flush=True)
            continue
        seen.add((provider, model))
        clients.append(_plain_client(fb_cfg, key))

    if not clients:
        print("[birkin] no usable fallback — running without a fallback.",
              flush=True)
        return primary

    from .failover import FailoverClient
    cooldown = float(cfg.get("fallback_cooldown", 300))
    chain = clients[-1]
    for client in reversed(clients[:-1]):
        chain = FailoverClient(client, chain, cooldown_s=cooldown)
    return FailoverClient(primary, chain, cooldown_s=cooldown)
