"""Provider registry for model-agnostic curation.

Each provider is reduced to the single contract CurationPlan/2 needs:

    complete(prompt: str) -> str

Nothing about tools, files, or sandboxes leaks past this line — the model is a
pure text generator, and the deterministic executor in :mod:`birkin.curation`
does all the (safe) work. Adding a new model means adding one ~10-line adapter
here; the prompt, schema, gate, and scorer are shared and unchanged.

Built-in providers: ``claude`` and ``codex`` (subscription CLIs, run in a
no-write configuration since the model only emits text), ``api`` (Anthropic or
OpenAI via the existing :class:`~birkin.llm.LLMClient`), and best-effort
``gemini`` / ``local`` CLI wrappers. Unknown/unavailable providers raise a
clear error rather than silently degrading.
"""

from __future__ import annotations

import os
import json
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

Completer = Callable[[str], str]

_CLI_TIMEOUT = 900


def _run(argv: list[str], stdin: str | None = None,
         timeout: int = _CLI_TIMEOUT, cwd: str | None = None,
         env: dict | None = None, abort=None) -> tuple[str, str, int]:
    """Discrete-argv subprocess (never shell=True). Returns (out, err, code)."""
    try:
        if abort is not None and abort.is_set():
            return "", "cancelled", -2
        from .proc import kill_tree, popen_tree_kwargs

        job = None
        proc = None
        try:
            kwargs = popen_tree_kwargs()
            if os.name == "nt":
                from ._winjob import WindowsJob

                job = WindowsJob.create()
                kwargs["creationflags"] |= getattr(
                    subprocess, "CREATE_SUSPENDED", 0x00000004)
            proc = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, errors="replace", cwd=cwd,
                env=env, **kwargs,
            )
            if job is not None:
                job.assign(proc.pid)
                job.resume(proc.pid)
        except BaseException:
            try:
                if job is not None:
                    job.terminate()
                if proc is not None and proc.poll() is None:
                    proc.kill()
                if proc is not None:
                    proc.wait(timeout=10)
            finally:
                if job is not None:
                    job.close()
            raise
        deadline = time.monotonic() + timeout
        pending_input = stdin
        try:
            while True:
                try:
                    out, err = proc.communicate(input=pending_input, timeout=0.1)
                    return out or "", err or "", proc.returncode
                except subprocess.TimeoutExpired:
                    pending_input = None
                    if abort is not None and abort.is_set():
                        job.terminate() if job is not None else kill_tree(proc)
                        out, err = proc.communicate()
                        return out or "", err or "cancelled", -2
                    if time.monotonic() >= deadline:
                        job.terminate() if job is not None else kill_tree(proc)
                        out, err = proc.communicate()
                        return out or "", err or f"timed out after {timeout}s", -1
        except BaseException:
            job.terminate() if job is not None else kill_tree(proc)
            try:
                proc.communicate()
            except Exception:
                pass
            raise
        finally:
            if job is not None:
                job.close()
    except subprocess.TimeoutExpired:
        return "", f"timed out after {timeout}s", -1
    except FileNotFoundError:
        return "", "command not found", 127


def claude_completer(model: Optional[str] = None,
                     timeout: int = _CLI_TIMEOUT, abort=None) -> Completer:
    """Claude Code with NO tools — pure text generation of the plan."""
    def complete(prompt: str) -> str:
        exe = shutil.which("claude")
        if not exe:
            return "[provider-error] claude CLI not found"
        argv = [exe, "-p", "--output-format", "json",
                "--allowedTools", "", "--permission-mode", "default"]
        if model and model not in ("claude-code", "default", ""):
            argv += ["--model", model]
        kwargs = {"abort": abort} if abort is not None else {}
        out, err, code = _run(argv, stdin=prompt, timeout=timeout, **kwargs)
        if code == -2:
            return "[provider-error] claude: cancelled"
        out = out.strip()
        if out:
            try:
                payload = json.loads(out)
            except (ValueError, json.JSONDecodeError):
                return out
            text = str(payload.get("result") or out)
            # `claude -p` reports auth and API trouble *in band*: exit 0, a
            # normal-looking envelope, and the complaint sitting in "result".
            # Without this check "Failed to authenticate: OAuth session
            # expired" is handed back as if the model had said it, and a
            # workflow happily builds on the sentence.
            if payload.get("is_error"):
                return f"[provider-error] claude: {text[:300]}"
            return text
        return f"[provider-error] claude: {err.strip()[:300]}"
    return complete


def codex_completer(model: Optional[str] = None,
                    timeout: int = _CLI_TIMEOUT,
                    cwd: Optional[str] = None,
                    schema: Optional[dict] = None, abort=None) -> Completer:
    """codex exec in a READ-ONLY sandbox — it only needs to emit text.

    Read-only means codex structurally cannot touch the vault even if it wanted
    to; the plan it prints is what matters. ``-o`` captures only the final
    assistant message. ``--ignore-user-config`` sidesteps the user's slow
    xhigh default and hook overhead.

    ``cwd`` matters: codex is agentic and will *read* its working directory.
    Point it at the vault being curated so any files it inspects are the same
    notes the prompt describes — otherwise it may ground its plan in whatever
    unrelated project happens to sit in the launch directory (it reads, e.g.,
    a repo's ``memory/`` folder and invents slugs from there).

    CODEX_HOME is deliberately left alone. An earlier version copied
    ``auth.json`` into a throwaway home to "isolate" the run; the child then
    refreshed the token, the server rotated it, the copy was deleted with the
    temp dir, and the user's real ``~/.codex/auth.json`` was left holding a
    spent refresh token — so the next codex call anywhere died with
    ``refresh_token_reused``. It bought nothing either: the flags above already
    ignore the user's config, and the ``exec.allow_untrusted`` entry the old
    docstring claimed was never actually written."""
    def complete(prompt: str) -> str:
        exe = shutil.which("codex")
        if not exe:
            return "[provider-error] codex CLI not found"
        fd, outpath = tempfile.mkstemp(suffix="-codex-plan.txt")
        os.close(fd)
        schema_path = ""
        if schema:
            sfd, schema_path = tempfile.mkstemp(suffix="-schema.json")
            os.close(sfd)
            Path(schema_path).write_text(
                json.dumps(schema), encoding="utf-8")
        argv = [exe, "exec", "--skip-git-repo-check", "--color", "never",
                "--sandbox", "read-only", "--ignore-user-config",
                "--ignore-rules", "--ephemeral", "-o", outpath]
        if schema_path:
            argv += ["--output-schema", schema_path]
        if cwd:
            argv += ["--cd", cwd]
        if model:
            argv += ["-m", model]
        argv.append("-")
        try:
            kwargs = {"abort": abort} if abort is not None else {}
            out, err, code = _run(
                argv, stdin=prompt, timeout=timeout, cwd=cwd, **kwargs,
            )
            if code == -2:
                return "[provider-error] codex: cancelled"
            if code == -1:
                return f"[provider-error] codex: {timeout}초 후 시간 초과"
            if code != 0:
                return f"[provider-error] codex: 종료 코드 {code}"
            text = ""
            try:
                text = Path(outpath).read_text(encoding="utf-8",
                                               errors="replace").strip()
            except OSError:
                pass
            return text or out.strip() or "[provider-error] codex: 모델 응답이 비어 있습니다"
        finally:
            try:
                os.unlink(outpath)
            except OSError:
                pass
            if schema_path:
                try:
                    os.unlink(schema_path)
                except OSError:
                    pass
    return complete


def codex_web_discovery(prompt: str, *, model: str = "",
                        timeout: int = _CLI_TIMEOUT,
                        schema: Optional[dict] = None,
                        abort=None) -> str:
    """One ephemeral native-web turn, returning only verified event metadata."""
    exe = shutil.which("codex")
    if not exe:
        return "[provider-error] codex CLI not found"
    developer = (
        "You are a read-only URL discovery worker. Use native web_search "
        "exactly once with at most four queries, each at most 500 characters. "
        "Do not use shell, filesystem, MCP, browser automation, "
        "or any other tool. Return only the requested JSON schema. Candidate "
        "URLs are discovery metadata, not verified source evidence."
    )
    with tempfile.TemporaryDirectory(prefix="birkin-codex-web-") as isolated:
        schema_path = Path(isolated) / "schema.json"
        if schema:
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
        argv = [
            exe, "--search", "--disable", "shell_tool", "--disable",
            "unified_exec", "exec", "--skip-git-repo-check", "--ephemeral",
            "--sandbox", "read-only", "--ignore-user-config", "--ignore-rules",
            "--color", "never", "--json", "--cd", isolated,
            "-c", "sandbox_workspace_write.network_access=false",
            "-c", f"developer_instructions={json.dumps(developer)}",
        ]
        if schema:
            argv += ["--output-schema", str(schema_path)]
        if model:
            argv += ["-m", model]
        argv.append("-")
        out, _err, code = _run(
            argv, stdin=prompt, timeout=timeout, cwd=isolated, abort=abort,
        )
    if code == -2:
        return "[provider-error] codex native web: cancelled"
    if code == -1:
        return "[provider-error] codex native web: timed out"
    if code != 0:
        return f"[provider-error] codex native web: exit {code}"
    try:
        events = [json.loads(line) for line in out.splitlines() if line.strip()]
        if not events or not all(isinstance(event, dict) for event in events):
            raise ValueError("event was not an object")
        indexed_items = [
            (index, event["type"], event["item"])
            for index, event in enumerate(events)
            if event.get("type") in {"item.started", "item.completed"}
            and isinstance(event.get("item"), dict)
        ]
        other_tools = [
            item for _, _, item in indexed_items
            if item.get("type") not in {"agent_message", "reasoning", "web_search"}
        ]
        started = [
            (index, item) for index, kind, item in indexed_items
            if kind == "item.started" and item.get("type") == "web_search"
        ]
        searches = [
            (index, item) for index, kind, item in indexed_items
            if kind == "item.completed" and item.get("type") == "web_search"
        ]
        messages = [
            (index, item) for index, kind, item in indexed_items
            if kind == "item.completed" and item.get("type") == "agent_message"
        ]
        terminals = [
            (index, event.get("type")) for index, event in enumerate(events)
            if event.get("type") in {"turn.completed", "turn.failed"}
        ]
        action = searches[0][1].get("action") if len(searches) == 1 else None
        raw_query = action.get("query") if isinstance(action, dict) else None
        raw_queries = action.get("queries") if isinstance(action, dict) else None
        query_value = raw_query.strip() if isinstance(raw_query, str) else None
        queries_value = (
            [query.strip() for query in raw_queries]
            if isinstance(raw_queries, list) and 1 <= len(raw_queries) <= 4
            and all(isinstance(query, str) and query.strip() for query in raw_queries)
            else None
        )
        query_shape_valid = raw_query is None or bool(query_value)
        queries_shape_valid = raw_queries is None or bool(queries_value)
        queries = queries_value or ([query_value] if query_value else [])
        query_valid = (
            isinstance(action, dict)
            and action.get("type") == "search"
            and query_shape_valid and queries_shape_valid
            and not (query_value and queries_value and [query_value] != queries_value)
        )
        reason = None
        if len(started) != 1 or len(searches) != 1:
            reason = "search_count"
        elif other_tools:
            reason = "other_tool"
        elif len(messages) != 1:
            reason = "message_count"
        elif len(terminals) != 1 or terminals[0][1] != "turn.completed":
            reason = "terminal"
        elif terminals[0][0] != len(events) - 1:
            reason = "terminal_order"
        elif (not isinstance(started[0][1].get("id"), str)
              or not started[0][1].get("id")
              or started[0][1].get("id") != searches[0][1].get("id")):
            reason = "search_id"
        elif not (started[0][0] < searches[0][0]
                  < messages[0][0] < terminals[0][0]):
            reason = "order"
        elif not query_valid or not queries:
            reason = "query"
        elif any(len(query) > 500 for query in queries):
            reason = "query_length"
        if reason:
            return f"[provider-error] codex native web: invalid tool trace ({reason})"
        payload = json.loads(str(messages[0][1].get("text") or ""))
        if not isinstance(payload, dict):
            raise ValueError("message was not an object")
        payload.update(
            web_search_count=1,
            observed_query="\n".join(queries),
            provenance="model_discovered_after_web_search",
        )
        return json.dumps(payload, ensure_ascii=False)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return "[provider-error] codex native web: invalid event stream"


def _responses_text(raw: str) -> str:
    """Pull the assistant text out of a Responses API reply (SSE or JSON).

    The Codex backend streams Server-Sent Events, but the same endpoint answers
    plain JSON when a proxy buffers it, so both shapes are handled here rather
    than assuming one and failing opaquely on the other.
    """
    def from_output(response: dict) -> str:
        chunks = []
        for item in response.get("output") or []:
            if not isinstance(item, dict):
                continue
            for block in item.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "output_text":
                    chunks.append(str(block.get("text") or ""))
        return "".join(chunks)

    stripped = raw.lstrip()
    if stripped.startswith("{"):
        try:
            response = json.loads(stripped)
        except json.JSONDecodeError:
            return ""
        if response.get("status") in {"failed", "incomplete"} \
                or response.get("error"):
            return "[provider-error] codex oauth: response failed"
        return from_output(response).strip()

    deltas: list[str] = []
    final = ""
    failed = False
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if not body or body == "[DONE]":
            continue
        try:
            event = json.loads(body)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind in {"error", "response.failed", "response.incomplete"} \
                or event.get("error"):
            failed = True
            continue
        if kind == "response.output_text.delta":
            deltas.append(str(event.get("delta") or ""))
        elif kind == "response.completed":
            response = event.get("response")
            if isinstance(response, dict):
                final = from_output(response)
    # Deltas are the live text; the terminal event repeats it in full and is
    # the only source when the server decides not to stream token-by-token.
    if failed:
        return "[provider-error] codex oauth: response failed"
    return ("".join(deltas) or final).strip()


def codex_oauth_available() -> bool:
    """True when birkin has its own Codex login (cheap check, no network)."""
    from . import codex_oauth
    return codex_oauth.is_logged_in()


def codex_oauth_completer(model: Optional[str] = None,
                          timeout: int = _CLI_TIMEOUT,
                          cfg: Optional[dict] = None,
                          schema: Optional[dict] = None, abort=None) -> Completer:
    """Codex over OAuth — a direct HTTPS call, no ``codex`` CLI subprocess.

    Uses birkin's own ChatGPT session (:mod:`birkin.codex_oauth`), so it neither
    needs the CLI installed nor disturbs its login.
    """
    from . import codex_oauth
    from .http_transport import (
        HTTPAborted, HTTPTransportError, open_no_redirect, post,
    )

    def complete(prompt: str) -> str:
        try:
            token = (codex_oauth.resolve_token(abort=abort)
                     if abort is not None else codex_oauth.resolve_token())
        except HTTPAborted:
            return "[provider-error] codex oauth: cancelled"
        except codex_oauth.CodexAuthError as exc:
            return f"[provider-error] codex oauth: {exc}"
        if not token:
            return ("[provider-error] codex oauth: not logged in — "
                    "run `birkin auth codex login`")

        chosen = model
        if not chosen:
            from .models import codex_model_ids
            ids = codex_model_ids(cfg)
            chosen = ids[0] if ids else "gpt-5.5"
        payload: dict = {
            "model": chosen,
            "instructions": "You output only what the user asks for.",
            "input": [{"role": "user",
                       "content": [{"type": "input_text", "text": prompt}]}],
            "store": False,
            "stream": True,
            "include": [],
        }
        if schema:
            payload["text"] = {"format": {"type": "json_schema",
                                          "name": "birkin_schema",
                                          "schema": schema, "strict": False}}
        headers = codex_oauth.auth_headers(token)
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "text/event-stream"
        req = urllib.request.Request(
            f"{codex_oauth.base_url()}/responses",
            data=json.dumps(payload).encode(), method="POST", headers=headers)
        try:
            if abort is None:
                with open_no_redirect(req, timeout=timeout) as resp:
                    raw = resp.read().decode("utf-8", "replace")
            else:
                response = post(
                    req.full_url, headers=dict(req.headers),
                    data=req.data or b"", timeout=timeout, abort=abort,
                )
                if response.status >= 300:
                    hint = ""
                    if response.status == 401:
                        hint = " — run `birkin auth codex login`"
                    elif response.status == 403:
                        hint = " — Codex rejected the client identity or the account"
                    return f"[provider-error] codex oauth HTTP {response.status}{hint}"
                raw = response.read().decode("utf-8", "replace")
        except HTTPAborted:
            return "[provider-error] codex oauth: cancelled"
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            hint = ""
            if exc.code == 401:
                hint = " — run `birkin auth codex login`"
            elif exc.code == 403:
                hint = " — Codex rejected the client identity or the account"
            return f"[provider-error] codex oauth HTTP {exc.code}{hint}: {detail}"
        except (urllib.error.URLError, HTTPTransportError,
                OSError, TimeoutError) as exc:
            return f"[provider-error] codex oauth: {exc}"
        return _responses_text(raw) or "[provider-error] codex oauth: empty reply"
    return complete


def api_completer(cfg: dict, model: Optional[str] = None, abort=None) -> Completer:
    """Anthropic/OpenAI via the existing LLMClient (single-turn, no tools)."""
    from .config import get_api_key
    from .llm import LLMError, build_client
    client = build_client(cfg, get_api_key(cfg) or "")

    def complete(prompt: str) -> str:
        try:
            kwargs = {"abort": abort} if abort is not None else {}
            resp = client.complete(
                system="You output only the requested JSON plan.",
                messages=[{"role": "user", "content": [{"type": "text",
                                                         "text": prompt}]}],
                tools=[], model=model, **kwargs)
        except LLMError as exc:
            return f"[provider-error] api: {str(exc)[:300]}"
        parts = [b.get("text", "") for b in resp.get("content", [])
                 if b.get("type") == "text"]
        return "\n".join(parts)
    return complete


def _generic_cli_completer(exe_name: str, argv_tail: list[str],
                           model: Optional[str],
                           model_flag: Optional[str],
                           timeout: int) -> Completer:
    def complete(prompt: str) -> str:
        exe = shutil.which(exe_name)
        if not exe:
            return f"[provider-error] {exe_name} CLI not found"
        argv = [exe, *argv_tail]
        if model and model_flag:
            argv += [model_flag, model]
        out, err, code = _run(argv, stdin=prompt, timeout=timeout)
        return out.strip() or f"[provider-error] {exe_name}: {err.strip()[:300]}"
    return complete


def gemini_completer(model: Optional[str] = None,
                     timeout: int = _CLI_TIMEOUT) -> Completer:
    """Best-effort Gemini CLI wrapper (prompt on stdin)."""
    return _generic_cli_completer("gemini", ["-p", "-"], model, "-m", timeout)


# OpenAI-compatible HTTP providers. Their base_url and key env live in
# birkin.config, so adding one here is a name plus a lookup. ``gemini`` above
# stays the CLI wrapper it has always been — the HTTP API is ``gemini-api``,
# and conflating them would silently change what existing configs run.
HTTP_API_PROVIDERS = {
    "gemini-api": "gemini",
    "nvidia": "nvidia",
    "freellmapi": "freellmapi",
}


def http_api_completer(provider: str, cfg: Optional[dict] = None,
                       model: Optional[str] = None, abort=None) -> Completer:
    """An OpenAI-compatible HTTP provider through the shared LLMClient.

    A missing key is reported in band like every other adapter here: curation
    treats a provider failure as text to score, never as an exception to
    unwind, so the caller sees ``[provider-error] ...`` and moves on.
    """
    from .config import PROVIDER_API_KEY_ENV, get_api_key

    llm_provider = HTTP_API_PROVIDERS[provider]
    provider_cfg = {**(cfg or {}), "provider": llm_provider}
    if model:
        provider_cfg["model"] = model

    def complete(prompt: str) -> str:
        key = get_api_key(provider_cfg)
        if not key:
            env = PROVIDER_API_KEY_ENV.get(llm_provider, "")
            return (f"[provider-error] {provider}: no credentials"
                    + (f" — set {env}" if env else ""))
        from .llm import LLMError, build_client
        try:
            client = build_client(provider_cfg, key)
            kwargs = {"abort": abort} if abort is not None else {}
            resp = client.complete(
                system="You output only what the user asks for.",
                messages=[{"role": "user",
                           "content": [{"type": "text", "text": prompt}]}],
                tools=[], model=provider_cfg.get("model"), **kwargs)
        except LLMError as exc:
            return f"[provider-error] {provider}: {str(exc)[:300]}"
        parts = [b.get("text", "") for b in resp.get("content", [])
                 if b.get("type") == "text"]
        return "\n".join(parts)
    return complete


def local_completer(model: Optional[str] = None,
                    timeout: int = _CLI_TIMEOUT) -> Completer:
    """Best-effort local model via `ollama run <model>` (prompt on stdin)."""
    def complete(prompt: str) -> str:
        exe = shutil.which("ollama")
        if not exe:
            return "[provider-error] ollama CLI not found"
        argv = [exe, "run", model or "llama3"]
        out, err, code = _run(argv, stdin=prompt, timeout=timeout)
        return out.strip() or f"[provider-error] ollama: {err.strip()[:300]}"
    return complete


def get_completer(provider: str, *, model: Optional[str] = None,
                  cfg: Optional[dict] = None,
                  timeout: int = _CLI_TIMEOUT,
                  cwd: Optional[str] = None,
                  schema: Optional[dict] = None, abort=None) -> Completer:
    """Resolve ``provider`` (claude|codex|api|gemini|local, or the ``*-cli``
    aliases) to a ``complete(prompt) -> text`` function.

    ``cwd`` anchors filesystem-reading agentic CLIs (codex) to the vault being
    curated; ignored by pure text providers.

    ``codex`` prefers birkin's own OAuth session (no subprocess, no CLI needed)
    and falls back to the ``codex`` CLI when the user has not run
    ``birkin auth codex login``."""
    p = provider.removesuffix("-cli")
    if p in ("claude", "claude-code"):
        return (
            claude_completer(model, timeout, abort=abort)
            if abort is not None else claude_completer(model, timeout)
        )
    if p == "codex":
        if codex_oauth_available():
            return (
                codex_oauth_completer(
                    model, timeout, cfg=cfg, schema=schema, abort=abort)
                if abort is not None else
                codex_oauth_completer(model, timeout, cfg=cfg, schema=schema)
            )
        return (
            codex_completer(model, timeout, cwd=cwd, schema=schema, abort=abort)
            if abort is not None else
            codex_completer(model, timeout, cwd=cwd, schema=schema)
        )
    if p in ("api", "anthropic", "openai"):
        return (api_completer(cfg or {}, model, abort=abort)
                if abort is not None else api_completer(cfg or {}, model))
    if p == "gemini":
        return gemini_completer(model, timeout)
    if p in ("local", "ollama"):
        return local_completer(model, timeout)
    if provider in HTTP_API_PROVIDERS:
        # Matched on the full name: `gemini-api` must not be reduced to
        # `gemini` by the ``-cli`` suffix stripping above.
        return (http_api_completer(provider, cfg, model, abort=abort)
                if abort is not None else http_api_completer(provider, cfg, model))
    raise ValueError(
        f"unknown curation provider {provider!r} (want: claude | codex | api "
        f"| gemini | local | {' | '.join(sorted(HTTP_API_PROVIDERS))})")
