"""Provider registry for model-agnostic curation.

Each provider is reduced to the single contract CurationPlan/1 needs:

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
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

Completer = Callable[[str], str]

_CLI_TIMEOUT = 900


def _run(argv: list[str], stdin: str | None = None,
         timeout: int = _CLI_TIMEOUT, cwd: str | None = None,
         env: dict | None = None) -> tuple[str, str, int]:
    """Discrete-argv subprocess (never shell=True). Returns (out, err, code)."""
    try:
        proc = subprocess.run(argv, input=stdin, capture_output=True,
                              text=True, errors="replace", timeout=timeout,
                              cwd=cwd, env=env)
        return proc.stdout or "", proc.stderr or "", proc.returncode
    except subprocess.TimeoutExpired:
        return "", f"timed out after {timeout}s", -1
    except FileNotFoundError:
        return "", "command not found", 127


# The CurationPlan/1 wire shape. Lives here because codex can enforce a
# JSON schema natively; it is passed IN by the curation caller rather
# than baked into the completer — a generic provider layer must not
# impose one application's output format on every other caller.
CURATION_PLAN_SCHEMA = {
    "type": "object",
    "required": ["plan_version", "ops", "summary"],
    "properties": {
        "plan_version": {"type": "integer", "const": 1},
        "summary": {"type": "string"},
        "ops": {"type": "array", "items": {
            "type": "object",
            "required": [
                "op", "slug", "zone", "a", "b", "stale", "by",
                "reason",
            ],
            "properties": {
                "op": {"type": "string"},
                "slug": {"type": ["string", "null"]},
                "zone": {"type": ["string", "null"]},
                "a": {"type": ["string", "null"]},
                "b": {"type": ["string", "null"]},
                "stale": {"type": ["string", "null"]},
                "by": {"type": ["string", "null"]},
                "reason": {"type": ["string", "null"]},
            },
            "additionalProperties": False,
        }},
    },
    "additionalProperties": False,
}


def claude_completer(model: Optional[str] = None,
                     timeout: int = _CLI_TIMEOUT) -> Completer:
    """Claude Code with NO tools — pure text generation of the plan."""
    def complete(prompt: str) -> str:
        exe = shutil.which("claude")
        if not exe:
            return "[provider-error] claude CLI not found"
        argv = [exe, "-p", "--output-format", "json",
                "--allowedTools", "", "--permission-mode", "default"]
        if model and model not in ("claude-code", "default", ""):
            argv += ["--model", model]
        out, err, code = _run(argv, stdin=prompt, timeout=timeout)
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
                    schema: Optional[dict] = None) -> Completer:
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
            out, err, code = _run(argv, stdin=prompt, timeout=timeout,
                                  cwd=cwd)
            text = ""
            try:
                text = Path(outpath).read_text(encoding="utf-8",
                                               errors="replace").strip()
            except OSError:
                pass
            return text or out.strip() or f"[provider-error] codex: {err.strip()[:2000]}"
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
            return from_output(json.loads(stripped)).strip()
        except json.JSONDecodeError:
            return ""

    deltas: list[str] = []
    final = ""
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
        if kind == "response.output_text.delta":
            deltas.append(str(event.get("delta") or ""))
        elif kind in ("response.completed", "response.incomplete"):
            response = event.get("response")
            if isinstance(response, dict):
                final = from_output(response)
    # Deltas are the live text; the terminal event repeats it in full and is
    # the only source when the server decides not to stream token-by-token.
    return ("".join(deltas) or final).strip()


def codex_oauth_available() -> bool:
    """True when birkin has its own Codex login (cheap check, no network)."""
    from . import codex_oauth
    return codex_oauth.is_logged_in()


def codex_oauth_completer(model: Optional[str] = None,
                          timeout: int = _CLI_TIMEOUT,
                          cfg: Optional[dict] = None,
                          schema: Optional[dict] = None) -> Completer:
    """Codex over OAuth — a direct HTTPS call, no ``codex`` CLI subprocess.

    Uses birkin's own ChatGPT session (:mod:`birkin.codex_oauth`), so it neither
    needs the CLI installed nor disturbs its login.
    """
    from . import codex_oauth

    def complete(prompt: str) -> str:
        try:
            token = codex_oauth.resolve_token()
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
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            hint = ""
            if exc.code == 401:
                hint = " — run `birkin auth codex login`"
            elif exc.code == 403:
                hint = " — Codex rejected the client identity or the account"
            return f"[provider-error] codex oauth HTTP {exc.code}{hint}: {detail}"
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            return f"[provider-error] codex oauth: {exc}"
        return _responses_text(raw) or "[provider-error] codex oauth: empty reply"
    return complete


def api_completer(cfg: dict, model: Optional[str] = None) -> Completer:
    """Anthropic/OpenAI via the existing LLMClient (single-turn, no tools)."""
    from .config import get_api_key
    from .llm import LLMError, build_client
    client = build_client(cfg, get_api_key(cfg) or "")

    def complete(prompt: str) -> str:
        try:
            resp = client.complete(
                system="You output only the requested JSON plan.",
                messages=[{"role": "user", "content": [{"type": "text",
                                                         "text": prompt}]}],
                tools=[], model=model)
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
                  schema: Optional[dict] = None) -> Completer:
    """Resolve ``provider`` (claude|codex|api|gemini|local, or the ``*-cli``
    aliases) to a ``complete(prompt) -> text`` function.

    ``cwd`` anchors filesystem-reading agentic CLIs (codex) to the vault being
    curated; ignored by pure text providers.

    ``codex`` prefers birkin's own OAuth session (no subprocess, no CLI needed)
    and falls back to the ``codex`` CLI when the user has not run
    ``birkin auth codex login``."""
    p = provider.removesuffix("-cli")
    if p in ("claude", "claude-code"):
        return claude_completer(model, timeout)
    if p == "codex":
        if codex_oauth_available():
            return codex_oauth_completer(model, timeout, cfg=cfg, schema=schema)
        return codex_completer(model, timeout, cwd=cwd, schema=schema)
    if p in ("api", "anthropic", "openai"):
        return api_completer(cfg or {}, model)
    if p == "gemini":
        return gemini_completer(model, timeout)
    if p in ("local", "ollama"):
        return local_completer(model, timeout)
    raise ValueError(f"unknown curation provider {provider!r} "
                     "(want: claude | codex | api | gemini | local)")
