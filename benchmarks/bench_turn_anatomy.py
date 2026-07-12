"""Anatomy of one warm Claude Code turn: where do the seconds go?

Drives `claude --print --input/output-format stream-json` directly, prints
every event with a wall-clock offset, and reads the `result` event's own
timing split (duration_ms vs duration_api_ms). Runs two configs:

  default        as birkin's gateway/bare session runs it
  no-thinking    MAX_THINKING_TOKENS=0 in the child env (the user's global
                 config enables extended thinking by default — a trivial
                 gateway chat turn may be paying a thinking budget)

Usage:
  python benchmarks/bench_turn_anatomy.py [--model haiku]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from birkin.proc import claude_child_env, cli_argv

PROMPT = "Reply with exactly one word: ok"


def run_case(name: str, model: str, env_extra: dict[str, str]) -> None:
    env = claude_child_env()
    env.update(env_extra)
    argv = cli_argv(["claude", "--print",
                     "--input-format", "stream-json",
                     "--output-format", "stream-json", "--verbose",
                     "--permission-mode", "acceptEdits",
                     "--model", model, "--strict-mcp-config"])
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, bufsize=1, encoding="utf-8",
                            errors="replace", env=env)
    print(f"\n== {name} ==", flush=True)
    for turn in (1, 2):
        t0 = time.monotonic()
        proc.stdin.write(json.dumps(
            {"type": "user",
             "message": {"role": "user", "content": PROMPT}}) + "\n")
        proc.stdin.flush()
        while True:
            line = proc.stdout.readline()
            if not line:
                print("  [process exited]", flush=True)
                return
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            dt = time.monotonic() - t0
            et = ev.get("type")
            sub = ev.get("subtype", "")
            if et == "assistant":
                blocks = [b.get("type") for b in
                          (ev.get("message") or {}).get("content", [])
                          if isinstance(b, dict)]
                print(f"  t{turn} +{dt:6.2f}s  assistant {blocks}", flush=True)
            elif et == "result":
                print(f"  t{turn} +{dt:6.2f}s  RESULT wall={ev.get('duration_ms')}ms "
                      f"api={ev.get('duration_api_ms')}ms "
                      f"turns={ev.get('num_turns')} "
                      f"usage={json.dumps((ev.get('usage') or {}), separators=(',',':'))[:160]}",
                      flush=True)
                break
            else:
                print(f"  t{turn} +{dt:6.2f}s  {et}{('/' + sub) if sub else ''}",
                      flush=True)
    proc.stdin.close()
    proc.terminate()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="haiku")
    args = ap.parse_args()
    run_case("default", args.model, {})
    run_case("no-thinking", args.model, {"MAX_THINKING_TOKENS": "0"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
