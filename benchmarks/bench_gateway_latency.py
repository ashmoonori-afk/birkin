"""Decompose birkin gateway turn latency vs a bare warm claude session.

Same model, same machine, same CLI — two warm stream-json sessions:

  gateway-like   what `birkin gateway` actually spawns: the composed 10k-char
                 system prompt + full inheritance of the user's Claude Code
                 config (every MCP server, plugin, hook)
  bare           no appended system prompt + --strict-mcp-config (no user MCP)

Reported per session: cold start (spawn -> first reply done), then two warm
turns with TTFT (first streamed text) and total. The delta is the price the
gateway pays per message for config inheritance + prompt size — separate
from the OTHER gap vs hermes (hermes streams partial replies to Telegram;
birkin's gateway only sends the finished turn).

Usage:
  python benchmarks/bench_gateway_latency.py [--model haiku]
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from birkin import config, promptgate
from birkin.claude_session import ClaudeStreamSession
from birkin.runtime import build_session

RES = Path("benchmarks/results")
PROMPT = "Reply with exactly one word: ok"


def gateway_system_prompt(cfg: dict) -> str:
    s = build_session(cfg)
    try:
        idx = s.skills.index()
    except Exception:
        idx = ""
    extra = ("\n\n## birkin skills available\n" + idx) if idx else ""
    return promptgate.compose_cli(cfg, memory_block=s.memory.render(),
                                  extra=extra)


def run_case(name: str, model: str, sys_prompt: str,
             extra_args: list[str] | None) -> dict:
    sess = ClaudeStreamSession(model=model, append_system_prompt=sys_prompt,
                               extra_args=extra_args)
    rows = []
    for i in range(3):                       # turn 1 = cold, 2-3 = warm
        ttft = [None]
        t0 = time.monotonic()

        def on_text(_piece, ttft=ttft, t0=t0):
            if ttft[0] is None:
                ttft[0] = time.monotonic() - t0
        reply = sess.ask(PROMPT, on_text=on_text)
        total = time.monotonic() - t0
        rows.append({"turn": i + 1, "ttft_s": round(ttft[0] or total, 2),
                     "total_s": round(total, 2), "reply": reply[:40]})
        print(f"  {name} turn{i+1}: ttft {rows[-1]['ttft_s']}s "
              f"total {rows[-1]['total_s']}s", flush=True)
    sess.close()
    return {"name": name, "turns": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="haiku")
    args = ap.parse_args()
    cfg = config.load_config()
    sp = gateway_system_prompt(cfg)
    print(f"gateway system prompt: {len(sp)} chars", flush=True)

    out = {"meta": {"date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "model": args.model, "sys_prompt_chars": len(sp)},
           "cases": []}
    out["cases"].append(run_case("gateway-like", args.model, sp, None))
    out["cases"].append(run_case("bare", args.model, "",
                                 ["--strict-mcp-config"]))
    RES.mkdir(parents=True, exist_ok=True)
    p = RES / f"gwlatency-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False),
                 encoding="utf-8")
    print(f"written: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
