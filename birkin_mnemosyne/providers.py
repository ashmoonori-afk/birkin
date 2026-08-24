"""Provider registry for model-agnostic curation.

Each provider is reduced to the single contract CurationPlan/1 needs:

    complete(prompt: str) -> str

Nothing about tools, files, or sandboxes leaks past this line — the model is a
pure text generator, and the deterministic executor in :mod:`mnemosyne.curation`
does all the (safe) work. Adding a new model means adding one ~10-line adapter
here; the prompt, schema, gate, and scorer are shared and unchanged.

Built-in providers: ``claude`` and ``codex`` (subscription CLIs, run in a
no-write configuration since the model only emits text), ``api`` (the Anthropic
Messages API via stdlib ``urllib`` — no SDK), and best-effort ``gemini`` /
``local`` CLI wrappers. For anything else, pass your own ``complete`` callable
straight to :func:`mnemosyne.run_curation_pass`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from types import TracebackType

from .json_types import JsonValue, load_json
from .provider_api import api_completer
from .provider_schema import curation_plan_schema

Completer = Callable[[str], str]
ProviderConfig = Mapping[str, JsonValue]

_CLI_TIMEOUT = 900


def _run(argv: list[str], stdin: str | None = None,
         timeout: int = _CLI_TIMEOUT, cwd: str | None = None,
         env: Mapping[str, str] | None = None) -> tuple[str, str, int]:
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

    def retry_readonly(
        func: Callable[[str], None],
        name: str,
        _exc: tuple[type[BaseException], BaseException, TracebackType],
    ) -> None:
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


def claude_completer(model: str | None = None,
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
        out, err, _code = _run(argv, stdin=prompt, timeout=timeout)
        out = out.strip()
        if out:
            try:
                payload = load_json(out)
                if isinstance(payload, dict):
                    return str(payload.get("result") or out)
            except (ValueError, json.JSONDecodeError):
                pass
            return out
        return f"[provider-error] claude: {err.strip()[:300]}"
    return complete


def codex_completer(model: str | None = None,
                    timeout: int = _CLI_TIMEOUT,
                    isolate_home: bool = True,
                    cwd: str | None = None) -> Completer:
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
        _ = Path(schema_path).write_text(
            json.dumps(curation_plan_schema()),
            encoding="utf-8",
        )
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
                _ = shutil.copy2(auth, home / "auth.json")
            env["CODEX_HOME"] = str(home)
        try:
            out, err, _code = _run(argv, stdin=prompt, timeout=timeout,
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


def _generic_cli_completer(exe_name: str, argv_tail: list[str],
                           model: str | None,
                           model_flag: str | None,
                           timeout: int) -> Completer:
    def complete(prompt: str) -> str:
        exe = shutil.which(exe_name)
        if not exe:
            return f"[provider-error] {exe_name} CLI not found"
        argv = [exe, *argv_tail]
        if model and model_flag:
            argv += [model_flag, model]
        out, err, _code = _run(argv, stdin=prompt, timeout=timeout)
        return out.strip() or f"[provider-error] {exe_name}: {err.strip()[:300]}"
    return complete


def gemini_completer(model: str | None = None,
                     timeout: int = _CLI_TIMEOUT) -> Completer:
    """Best-effort Gemini CLI wrapper (prompt on stdin)."""
    return _generic_cli_completer("gemini", ["-p", "-"], model, "-m", timeout)


def local_completer(model: str | None = None,
                    timeout: int = _CLI_TIMEOUT) -> Completer:
    """Best-effort local model via `ollama run <model>` (prompt on stdin)."""
    def complete(prompt: str) -> str:
        exe = shutil.which("ollama")
        if not exe:
            return "[provider-error] ollama CLI not found"
        argv = [exe, "run", model or "llama3"]
        out, err, _code = _run(argv, stdin=prompt, timeout=timeout)
        return out.strip() or f"[provider-error] ollama: {err.strip()[:300]}"
    return complete


def get_completer(provider: str, *, model: str | None = None,
                  cfg: ProviderConfig | None = None,
                  timeout: int = _CLI_TIMEOUT,
                  cwd: str | None = None) -> Completer:
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
    message = (
        f"unknown curation provider {provider!r} "
        "(want: claude | codex | api | gemini | local)"
    )
    raise ValueError(message)
