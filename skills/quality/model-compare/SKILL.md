---
name: model-compare
description: "Blind A/B compare two models on one prompt — judge the output, not the brand. Free on the subscription tiers (opus/sonnet/haiku)."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [quality, evaluation, models, compare]
    entrypoint: "birkin compare \"<prompt>\" [--a opus --b sonnet]"
---

# Model Compare — blind A/B

Run the **same prompt through two models** and read the answers **blind**
(randomized A/B) before learning which is which — so you pick based on the output
quality, not the model name. A lightweight take on odysseus's "Compare". On the
subscription path the tiers are free, so e.g. `opus` vs `sonnet` vs `haiku` costs
nothing extra.

## When to Use

- Deciding which model/tier to use for a class of task (does `sonnet` match
  `opus` here? is `haiku` enough?).
- Sanity-checking a cheaper tier before routing quick tasks to it (pairs with the
  Model Router, v2 #1).
- Settling "which answer is better" without brand bias.

## When NOT to Use

- You already know the task needs the top tier — just use it.
- The task is multi-step/agentic (this is a one-shot prompt comparison, not an
  agent run).
- A paid API provider is selected and you don't want to spend on two calls.

## Procedure

1. Run `birkin compare "<prompt>"` — defaults to the current model vs a
   complementary tier; override with `--a` / `--b` (e.g. `--a opus --b sonnet`).
2. Read **A** and **B** with the model names hidden; decide which you prefer.
3. Press Enter to reveal the mapping (`A = … B = …`).
4. If you want the winner as your default, set it (`/models <name>` in the
   gateway, or `birkin model`). Auto-routing by task class is a planned v2 idea
   (Model Router — `docs/v2.md` #1, not shipped as a module).

## Output

- Two answers shown blind (A / B), then the revealed model mapping.
- No file is written; this is an interactive judgment aid. (Programmatic callers
  use `birkin/compare.py`'s `run()` which returns the blind result dict.)

## Notes

- Blind by design: the A/B order is randomized so the label never leaks the model.
- Free-tier first: prefer the subscription tiers; a paid API provider runs two
  metered calls, so only compare there when you accept the cost.
