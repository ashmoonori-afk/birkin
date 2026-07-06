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
import time
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


def _rmtree_retry(path: Path, attempts: int = 20, delay: float = 0.15) -> None:
    target = Path(path)
    delete_path = target
    if os.name == "nt":
        resolved = str(target.resolve())
        if not resolved.startswith("\\\\?\\"):
            delete_path = Path("\\\\?\\" + resolved)

    def retry_readonly(func, name, _exc):
        os.chmod(name, 0o700)
        func(name)

    for attempt in range(attempts):
        if not target.exists():
            return
        try:
            shutil.rmtree(delete_path, onerror=retry_readonly)
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay * (attempt + 1))


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
                import json
                return str(json.loads(out).get("result") or out)
            except (ValueError, json.JSONDecodeError):
                return out
        return f"[provider-error] claude: {err.strip()[:300]}"
    return complete


def codex_completer(model: Optional[str] = None,
                    timeout: int = _CLI_TIMEOUT,
                    isolate_home: bool = True,
                    cwd: Optional[str] = None) -> Completer:
    """codex exec in a READ-ONLY sandbox — it only needs to emit text.

    Read-only means codex structurally cannot touch the vault even if it wanted
    to; the plan it prints is what matters. ``-o`` captures only the final
    assistant message. ``--ignore-user-config`` sidesteps the user's slow
    xhigh default and hook overhead.

    ``cwd`` matters: codex is agentic and will *read* its working directory.
    Point it at the vault being curated so any files it inspects are the same
    notes the prompt describes — otherwise it may ground its plan in whatever
    unrelated project happens to sit in the launch directory (it reads, e.g.,
    a repo's ``memory/`` folder and invents slugs from there). Runs in an
    isolated fresh CODEX_HOME with an ``exec.allow_untrusted`` project entry so
    a throwaway vault dir is runnable without a manual trust prompt."""
    def complete(prompt: str) -> str:
        exe = shutil.which("codex")
        if not exe:
            return "[provider-error] codex CLI not found"
        fd, outpath = tempfile.mkstemp(suffix="-codex-plan.txt")
        os.close(fd)
        sfd, schema_path = tempfile.mkstemp(suffix="-curation-plan.schema.json")
        os.close(sfd)
        Path(schema_path).write_text(json.dumps({
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
        }), encoding="utf-8")
        argv = [exe, "exec", "--skip-git-repo-check", "--color", "never",
                "--sandbox", "read-only", "--ignore-user-config",
                "--ignore-rules", "--ephemeral", "--output-schema", schema_path,
                "-o", outpath]
        if cwd:
            argv += ["--cd", cwd]
        if model:
            argv += ["-m", model]
        argv.append("-")
        env = dict(os.environ)
        home: Path | None = None
        if isolate_home:
            src = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
            tmp_root = Path.cwd() / ".omo" / "tmp"
            tmp_root.mkdir(parents=True, exist_ok=True)
            home = Path(tempfile.mkdtemp(suffix="-codex-home",
                                         dir=str(tmp_root)))
            auth = src / "auth.json"
            if auth.is_file():
                shutil.copy2(auth, home / "auth.json")
            env["CODEX_HOME"] = str(home)
        try:
            out, err, code = _run(argv, stdin=prompt, timeout=timeout,
                                  env=env, cwd=cwd)
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
            try:
                os.unlink(schema_path)
            except OSError:
                pass
            if home is not None:
                _rmtree_retry(home)
    return complete


def api_completer(cfg: dict, model: Optional[str] = None) -> Completer:
    """Anthropic/OpenAI via the existing LLMClient (single-turn, no tools)."""
    from .llm import LLMClient
    client = LLMClient(cfg)

    def complete(prompt: str) -> str:
        resp = client.complete(
            system="You output only the requested JSON plan.",
            messages=[{"role": "user", "content": [{"type": "text",
                                                     "text": prompt}]}],
            tools=[], model=model)
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
                  cwd: Optional[str] = None) -> Completer:
    """Resolve ``provider`` (claude|codex|api|gemini|local, or the ``*-cli``
    aliases) to a ``complete(prompt) -> text`` function.

    ``cwd`` anchors filesystem-reading agentic CLIs (codex) to the vault being
    curated; ignored by pure text providers."""
    p = provider.removesuffix("-cli")
    if p in ("claude", "claude-code"):
        return claude_completer(model, timeout)
    if p == "codex":
        return codex_completer(model, timeout, cwd=cwd)
    if p in ("api", "anthropic", "openai"):
        return api_completer(cfg or {}, model)
    if p == "gemini":
        return gemini_completer(model, timeout)
    if p in ("local", "ollama"):
        return local_completer(model, timeout)
    raise ValueError(f"unknown curation provider {provider!r} "
                     "(want: claude | codex | api | gemini | local)")
