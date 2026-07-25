"""Moirai — deterministic multi-agent orchestration across providers.

Control flow belongs to code, not to a model deciding whether to call a tool
again. A workflow is a plain Python file: it declares ``meta`` (including the
*roles* it needs) and a ``main(m)`` that calls ``m.agent(...)``,
``m.parallel(...)`` and ``m.pipeline(...)``. Which model answers each call is
decided before the run starts (see :mod:`birkin.moirai.bindings`), so the same
script runs on codex once and claude the next time without an edit.

Three concerns, named after the Fates:

- **Clotho** spins the threads — spawning agents and routing them to a provider.
- **Lachesis** measures — the journal, tokens, and what the picker shows.
- **Atropos** cuts — abort, spawn caps, and the budget gate.

Pure standard library. Entry is always explicit (CLI or slash command); no
model can start a workflow, which is the one spawn path that could run away.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional

from .. import config, ledger, store
from . import bindings as _bindings
from . import journal
from .bindings import Binding, BindingError

DEFAULT_WORKERS = 4
DEFAULT_MAX_AGENTS = 100
# role= appearing in a script's source, for the pre-run call-count estimate.
_ROLE_CALL_RE = re.compile(r"""role\s*=\s*["']([A-Za-z0-9_-]+)["']""")


class MoiraiError(RuntimeError):
    """A workflow that cannot start, or cannot keep going."""


# -- script loading --------------------------------------------------------

class Script:
    """A loaded workflow file: its metadata, its ``main``, and its identity."""

    def __init__(self, path: Path, meta: dict, main: Callable,
                 source: str) -> None:
        self.path = path
        self.meta = meta
        self.main = main
        self.source = source
        self.sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
        self.roles = _bindings.declared_roles(meta)

    @property
    def name(self) -> str:
        return str(self.meta.get("name") or self.path.stem)

    @property
    def description(self) -> str:
        return str(self.meta.get("description") or "")

    def roles_used(self) -> set[str]:
        """Roles the body actually references — a typo here is caught once,
        before anything spawns, instead of on the call that reaches it."""
        return set(_ROLE_CALL_RE.findall(self.source))

    def estimated_calls(self) -> dict[str, int]:
        """How many times each role is likely called. A static count of
        ``role=`` occurrences: right for straight-line scripts, low for loops.
        The picker marks it '~' and the journal corrects it afterwards."""
        counts: dict[str, int] = {}
        for role in _ROLE_CALL_RE.findall(self.source):
            counts[role] = counts.get(role, 0) + 1
        return counts


def load_script(path: str | Path) -> Script:
    """Read and exec a workflow file, then demand the two symbols.

    The file is user code, exactly like a skill script: birkin does not
    sandbox it, and the trust boundary is that the user (or an approval gate)
    put it there.
    """
    p = Path(path).expanduser()
    if not p.is_file():
        raise MoiraiError(f"워크플로우 파일이 없습니다: {p}")
    source = p.read_text(encoding="utf-8")
    namespace: dict[str, Any] = {"__file__": str(p), "__name__": "__moirai__"}
    try:
        exec(compile(source, str(p), "exec"), namespace)   # noqa: S102
    except Exception as exc:
        raise MoiraiError(f"워크플로우 로드 실패 ({p.name}): {exc}") from exc

    meta = namespace.get("meta")
    if not isinstance(meta, dict) or not meta.get("name"):
        raise MoiraiError(
            f"{p.name}: meta dict에 최소한 name이 있어야 합니다")
    main = namespace.get("main")
    if not callable(main):
        raise MoiraiError(f"{p.name}: main(m) 함수가 없습니다")
    return Script(p, meta, main, source)


# -- the API handed to a script -------------------------------------------

class MoiraiBudget:
    """The token allowance for one run, as the script sees it."""

    def __init__(self, total: Optional[int]) -> None:
        self.total = total
        self._spent = 0
        self._lock = threading.Lock()

    def add(self, tokens: int) -> None:
        with self._lock:
            self._spent += max(0, int(tokens))

    def spent(self) -> int:
        return self._spent

    def remaining(self) -> float:
        if not self.total:
            return float("inf")
        return max(0, self.total - self._spent)


class MoiraiAPI:
    """``m`` — the only surface a workflow script is given."""

    def __init__(self, run: "Run") -> None:
        self._run = run
        self.args = run.args
        self.budget = run.budget

    # -- primitives --------------------------------------------------------

    def agent(self, prompt: str, *, role: Optional[str] = None,
              provider: Optional[str] = None, model: Optional[str] = None,
              label: Optional[str] = None, phase: Optional[str] = None,
              schema: Optional[dict] = None, tools: Optional[str] = None,
              cwd: Optional[str] = None, max_turns: int = 12,
              timeout: float = 900.0,
              effort: Optional[str] = None) -> Any:
        """Run one agent. Returns its text (or parsed object with ``schema``),
        or ``None`` if it failed — a failed agent must not abort the run."""
        return self._run.call_agent(
            prompt, role=role, provider=provider, model=model, label=label,
            phase=phase, schema=schema, tools=tools, cwd=cwd,
            max_turns=max_turns, timeout=timeout, effort=effort)

    def parallel(self, thunks: list[Callable[[], Any]]) -> list[Any]:
        """Run thunks concurrently and wait for all of them.

        A barrier: use it when the next step needs every result together.
        A thunk that raises becomes ``None`` in the results — the call itself
        never raises, so one bad branch cannot take down the workflow.
        """
        return self._run.run_parallel(list(thunks))

    def pipeline(self, items: list[Any], *stages: Callable) -> list[Any]:
        """Send each item through all stages independently — no barrier
        between stages, so a fast item finishes while a slow one is still in
        stage one. The default shape for multi-stage work."""
        return self._run.run_pipeline(list(items), stages)

    def phase(self, title: str) -> None:
        self._run.set_phase(str(title))

    def log(self, message: str) -> None:
        self._run.emit_log(str(message))


# -- the run ---------------------------------------------------------------

class Run:
    """One execution of one script: journal, executor, guards."""

    def __init__(self, script: Script, *, cfg: dict,
                 bindings_map: dict[str, Binding],
                 args: Optional[dict] = None,
                 run_id: Optional[str] = None,
                 resume_from: Optional[str] = None,
                 on_event: Optional[Callable[[str, dict], None]] = None,
                 abort: Optional[Any] = None,
                 spawn: Optional[Callable] = None) -> None:
        self.script = script
        self.cfg = cfg
        self.bindings = bindings_map
        self.args = dict(args or {})
        self.run_id = run_id or f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
        self.on_event = on_event
        self.abort = abort
        self._spawn = spawn or _default_spawn

        self.workers = max(1, int(cfg.get("moirai_workers", DEFAULT_WORKERS)))
        self.max_agents = max(1, int(cfg.get("moirai_max_agents",
                                             DEFAULT_MAX_AGENTS)))
        self.budget = MoiraiBudget(_run_token_budget(cfg))

        self._seq = 0
        self._seq_lock = threading.Lock()
        self._phase = ""
        self._spawned = 0
        self._cache = journal.cached_calls(resume_from) if resume_from else {}
        self.cache_hits = 0

    # -- guards (Atropos) --------------------------------------------------

    def _aborted(self) -> bool:
        return self.abort is not None and self.abort.is_set()

    def _guard(self) -> Optional[str]:
        """Why the next agent must not start, or None."""
        if self._aborted():
            return "중단됨"
        if self._spawned >= self.max_agents:
            return f"스폰 상한 도달 ({self.max_agents})"
        if self.budget.total and self.budget.remaining() <= 0:
            return "토큰 예산 소진"
        return None

    # -- events ------------------------------------------------------------

    def _emit(self, event: str, payload: dict) -> None:
        if self.on_event:
            try:
                self.on_event(event, payload)
            except Exception:
                pass

    def set_phase(self, title: str) -> None:
        self._phase = title
        self._emit("moirai.phase", {"title": title})

    def emit_log(self, message: str) -> None:
        self._emit("moirai.log", {"message": message})

    # -- the agent call ----------------------------------------------------

    def call_agent(self, prompt: str, *, role: Optional[str], **opts) -> Any:
        binding = self._binding_for(role, opts)
        call_opts = {
            "provider": binding.provider, "model": binding.model,
            "schema": opts.get("schema"),
            "tools": opts.get("tools") or binding.tools,
            "effort": opts.get("effort"), "cwd": opts.get("cwd"),
            "max_turns": opts.get("max_turns", 12),
        }
        key = journal.call_key(prompt, call_opts)

        with self._seq_lock:
            self._seq += 1
            seq = self._seq

        cached = self._cache.get(seq)
        if cached and cached.get("call_key") == key:
            self.cache_hits += 1
            self._emit("moirai.cached", {"seq": seq,
                                         "label": opts.get("label") or role or ""})
            return _decode(cached.get("result"), call_opts.get("schema"))

        blocked = self._guard()
        if blocked:
            self.emit_log(f"에이전트 건너뜀 ({blocked})")
            return None

        self._spawned += 1
        label = opts.get("label") or role or binding.model or binding.provider
        journal.record_call(self.run_id, seq, key, role=role or "",
                            provider=binding.provider, model=binding.model,
                            label=label,
                            phase=opts.get("phase") or self._phase)
        # Reuse the existing subagent vocabulary so the TUI's trace tree
        # renders a workflow with no changes.
        self._emit("subagent.start", {"task": f"[{label}] {prompt[:160]}"})
        started = time.monotonic()
        try:
            text = self._spawn(prompt, binding, call_opts, self.cfg,
                               timeout=opts.get("timeout", 900.0))
        except Exception as exc:
            journal.finish_call(self.run_id, seq, status="error",
                                error=str(exc)[:2000])
            self._emit("subagent.done", {"error": str(exc)[:200]})
            self.emit_log(f"에이전트 실패 [{label}]: {exc}")
            return None

        elapsed = time.monotonic() - started
        if isinstance(text, str) and text.startswith("[provider-error]"):
            journal.finish_call(self.run_id, seq, status="error",
                                error=text[:2000])
            self._emit("subagent.done", {"error": text[:200]})
            self.emit_log(f"에이전트 실패 [{label}]: {text[:160]}")
            return None

        tokens = store.estimate_usage(prompt, text or "").get("estTokens", 0)
        self.budget.add(tokens)
        journal.finish_call(self.run_id, seq, status="ok",
                            result=text or "", tokens=tokens)
        ledger.event("moirai.agent",
                     f"{self.script.name}/{label} {binding.spec} {elapsed:.1f}s",
                     tokens=tokens)
        self._emit("subagent.done", {"chars": len(text or "")})
        return _decode(text, call_opts.get("schema"))

    def _binding_for(self, role: Optional[str], opts: dict) -> Binding:
        """Rung 1 of the ladder: an explicit provider/model on the call wins
        over whatever the role was bound to."""
        provider, model = opts.get("provider"), opts.get("model")
        if provider or model:
            base = self.bindings.get(role or "") if role else None
            return Binding(
                role=role or "(inline)",
                provider=str(provider or (base.provider if base else "")
                             ).removesuffix("-cli"),
                model=str(model or (base.model if base else "")),
                source="call",
                tools=str(opts.get("tools") or (base.tools if base else "none")))
        if role:
            if role not in self.bindings:
                raise MoiraiError(
                    f"선언되지 않은 role: {role!r} — meta['roles']에 추가하세요")
            return self.bindings[role]
        if "" in self.bindings:
            return self.bindings[""]
        raise MoiraiError(
            "role 없이 호출하려면 provider=/model=을 주거나 "
            "meta['roles']를 선언하세요")

    # -- executors ---------------------------------------------------------

    def run_parallel(self, thunks: list[Callable[[], Any]]) -> list[Any]:
        if not thunks:
            return []
        if len(thunks) == 1:
            return [_safe(thunks[0])]
        results: list[Any] = [None] * len(thunks)
        with ThreadPoolExecutor(
                max_workers=min(len(thunks), self.workers)) as pool:
            futures = {pool.submit(_safe, t): i for i, t in enumerate(thunks)}
            for fut, idx in futures.items():
                try:
                    results[idx] = fut.result()
                except Exception:
                    results[idx] = None
        return results

    def run_pipeline(self, items: list[Any],
                     stages: tuple[Callable, ...]) -> list[Any]:
        def chain(item: Any, index: int) -> Any:
            value = item
            for stage in stages:
                try:
                    value = stage(value, item, index)
                except TypeError:
                    value = stage(value)
                except Exception:
                    return None
                if value is None:
                    return None
            return value

        return self.run_parallel(
            [lambda it=it, i=i: chain(it, i) for i, it in enumerate(items)])


def _safe(thunk: Callable[[], Any]) -> Any:
    try:
        return thunk()
    except Exception:
        return None


def _decode(text: Any, schema: Optional[dict]) -> Any:
    """Placeholder for M2's structured decoding; text passes through today."""
    return text


def _run_token_budget(cfg: dict) -> Optional[int]:
    """A run's own token ceiling, if the user set one."""
    raw = cfg.get("moirai_token_budget") or 0
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value or None


def _default_spawn(prompt: str, binding: Binding, opts: dict, cfg: dict, *,
                   timeout: float = 900.0) -> str:
    """Text-only agent: one shot through the existing provider layer.

    Tool-bearing agents (``tools != "none"``) arrive in M3; until then the
    engine refuses rather than silently running a weaker agent than the script
    asked for.
    """
    from .. import providers
    if (opts.get("tools") or "none") != "none":
        raise MoiraiError(
            "tools= 에이전트는 아직 지원되지 않습니다 (M3) — tools='none'으로 두세요")
    completer = providers.get_completer(
        binding.provider, model=binding.model or None, cfg=cfg,
        timeout=int(timeout), cwd=opts.get("cwd"))
    return completer(prompt)


# -- top level -------------------------------------------------------------

def run_script(script: Script, *, cfg: Optional[dict] = None,
               bindings_map: Optional[dict[str, Binding]] = None,
               args: Optional[dict] = None,
               resume_from: Optional[str] = None,
               on_event: Optional[Callable[[str, dict], None]] = None,
               abort: Optional[Any] = None,
               spawn: Optional[Callable] = None) -> dict[str, Any]:
    """Execute one workflow end to end. Returns a summary dict."""
    cfg = cfg if cfg is not None else config.load_config()
    if bindings_map is None:
        bindings_map = _bindings.resolve(script.roles, cfg=cfg)
    _bindings.check_roles_used(script.roles, script.roles_used())
    _bindings.validate(bindings_map, cfg)

    run = Run(script, cfg=cfg, bindings_map=bindings_map, args=args,
              resume_from=resume_from, on_event=on_event, abort=abort,
              spawn=spawn)
    journal.start_run(run.run_id, name=script.name,
                      script_path=str(script.path),
                      script_sha256=script.sha256, args=run.args,
                      bindings=_bindings.as_specs(bindings_map))
    api = MoiraiAPI(run)
    started = time.monotonic()
    try:
        result = script.main(api)
        status = "aborted" if run._aborted() else "completed"
    except Exception as exc:
        journal.finish_run(run.run_id, "error", result={"error": str(exc)},
                           tokens=run.budget.spent())
        store.save_run("moirai", f"{script.name}: 실패 — {exc}",
                       details={"run_id": run.run_id, "error": str(exc)})
        raise MoiraiError(f"워크플로우 실패 ({script.name}): {exc}") from exc

    elapsed = time.monotonic() - started
    journal.finish_run(run.run_id, status, result=result,
                       tokens=run.budget.spent())
    store.save_run(
        "moirai", f"{script.name}: {status} · 에이전트 {run._spawned}",
        details={"run_id": run.run_id, "script": str(script.path),
                 "bindings": _bindings.as_specs(bindings_map),
                 "agents": run._spawned, "cache_hits": run.cache_hits,
                 "seconds": round(elapsed, 1)},
        usage={"estTokens": run.budget.spent()})
    store.append_activity(f"moirai: {script.name} {status} "
                          f"({run._spawned} agents, {elapsed:.0f}s)")
    return {"run_id": run.run_id, "status": status, "result": result,
            "agents": run._spawned, "cache_hits": run.cache_hits,
            "tokens": run.budget.spent(), "seconds": round(elapsed, 1)}
