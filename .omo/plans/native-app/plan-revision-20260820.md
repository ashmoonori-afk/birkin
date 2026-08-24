# Plan Revision Note — 2026-08-20

## Baseline

- Original plan baseline: `origin/main` at `79a0b230` (merge-base of the
  feature branch).
- Revised baseline: `origin/main` at `0ac1312`, package version `0.4.242`.
- Feature branch `feat/native-app-implementation-20260817`: 30 commits
  ahead, 23 behind the revised baseline. The branch has never been pushed
  (no `origin/feat/...` ref exists).

## Contract audit result

Diff `79a0b230..0ac1312` inspected for every surface the native plan
depends on:

- `birkin/workspace/`, `birkin/native/`, `birkin/computer_use/`,
  `birkin/omo*`: **unchanged**. All protocol, capability, transport,
  endpoint, projection, and workspace-command contracts the Foundation
  phase was built against remain valid. No Foundation rework needed.
- `birkin/cli.py`: +67 lines on main (new `daedalus` subcommand and
  parser wiring). No native-plan contract impact; the native shell talks
  to the workspace service, not the CLI parser.
- `pyproject.toml`: version bump only (0.4.227 -> 0.4.242).
- `tests/test_workspace_contract.py`: main replaced the `/dash`
  parametrize row with `/workbench`; the branch added
  `test_workspace_command_accepts_macos_client_surface`. Hunks are
  disjoint; git can auto-merge.
- `README.md` / `README.ko.md`: main rewrote ~109/108 lines (office
  walkthrough, unified workbench, model fallback); the branch added 2
  lines each. Small conflict risk at merge; resolve by taking main's
  rewrite and re-applying the branch's native-app lines.

Plan-document scan (12 docs under `.omo/plans/native-app/` and
`docs/native-app/`): the only stale references were the two baseline SHA
pins in `masterplan.md` and `release.md`, both now updated. No plan doc
referenced `/dash`, `/models`, removed commands, worker names, providers,
or old version strings.

## Main-side changes relevant to later phases

- Slash-command surface consolidated 43 -> 35 (`/dash` removed with a
  `/workbench` alias, `/models` folded into `/model`, `/persona` merged).
  Affects Product Surfaces: any native command palette / terminal
  projection must mirror the live 35-command surface and must not
  advertise removed commands.
- `/work` workbench unification and `worker_invoke` + `daedalus` workers:
  Product Surfaces (owned terminal and tool execution; approvals and
  activity receipts) should project these through the existing workspace
  command contract; no new native protocol messages required.
- Ordered LLM fallback chain and new providers (gemini-api, nvidia,
  freellmapi): no native-shell impact; Python remains authority for model
  routing.
- `.omo/evidence` and benchmark artifacts untracked on main: consistent
  with our CI, which writes `.omo/evidence/native-protocol` at runtime
  and uploads it as an artifact without committing it.
- CI wait budgets widened for Windows runners: reduces flake risk for our
  three-platform gates; no plan change.

## Affected phases / waves / tasks

- Foundation: no change; all 59 tasks remain valid (58 done, SwiftUI
  shell task open).
- Product Surfaces: "Connect owned terminal and tool execution" and
  "Connect approvals and activity receipts" must target the post-merge
  command surface (35 commands, `/workbench` alias, workbench-unified
  `/work`). Acceptance assertions must be written against merged main.
- Verification / Delivery: unchanged, but all gates now run against the
  merged tree (0ac1312 ancestry).

## Integration decision

**Merge `origin/main` into the feature branch** (`git merge origin/main`).

- Rebase is rejected: it would rewrite 30 verified atomic commits for no
  benefit; the brief forbids reset/force-push and requires preserving
  commits.
- Expected conflicts: at most README.md / README.ko.md. Resolution
  policy: keep main's rewritten sections, re-add the branch's native-app
  lines.
- After the merge: run the full verification gates (native + workspace +
  CI-matrix pytest, basedpyright, ruff, uv build, bandit) via an
  ultrawork subagent before any further implementation.

## Compatibility risks

1. README conflict resolution could drop the branch's native-app lines —
   verify both lines survive post-merge.
2. Post-merge test surface includes main's updated `/workbench`
   parametrize row — the merged suite must pass as-is; any failure is an
   integration defect, not a pre-existing one.
3. Native shell work must read command surfaces from the merged tree,
   never from pre-merge assumptions.

## Verification gates (post-merge, before new implementation)

- `uv run pytest -q tests/test_native_*.py tests/test_workspace_contract.py
  tests/test_workspace_session_protocol.py tests/test_ci_platform_matrix.py`
- `uv run basedpyright birkin/native birkin/workspace/contracts.py
  birkin/workspace/service.py tests/test_native_*.py`
- `uv run ruff check` (same scope), `uv build`,
  `uv run bandit -r birkin/native -q`

All gates delegated to ultrawork subagents; Fable reviews outputs only.
