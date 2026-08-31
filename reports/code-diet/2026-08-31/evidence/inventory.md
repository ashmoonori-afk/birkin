# Working-tree source inventory

Measured: 2026-08-31
Scope: `git ls-files --cached --others --exclude-standard`
Counter: nonblank lines excluding full-line `#` and `//` comments.

## Reproducible command shape

```bash
git ls-files --cached --others --exclude-standard -z -- <pathspecs> |
  xargs -0 perl -ne '$t++; $p++ if /\S/ && !/^\s*(#|\/\/)/; if(eof){print "$p\t$t\t$ARGV\n"; $p=0; $t=0;}'
```

## Scope totals

| Scope | Files | Pure LOC | Files over 250 pure LOC |
|---|---:|---:|---:|
| `birkin/` + `birkin_mnemosyne/` Python | 586 | 96,888 | 66 |
| `tests/` Python | 553 | 83,762 | 71 |
| `script/`, `scripts/`, `benchmarks/` Python | 63 | 9,464 | 8 |
| Windows C# + macOS Swift, including tests | 303 | 28,921 | 19 |
| JavaScript + TypeScript, including QA/tests | 22 | 1,374 | 0 |

## Largest production Python modules

| Pure LOC | Physical LOC | Path |
|---:|---:|---|
| 1,539 | 1,672 | `birkin/web/server.py` |
| 1,385 | 1,567 | `birkin/gateway/channels/telegram.py` |
| 1,325 | 1,543 | `birkin/cli.py` |
| 1,205 | 1,315 | `birkin/skills/manager.py` |
| 1,166 | 1,306 | `birkin/memory.py` |
| 1,133 | 1,278 | `birkin/harness.py` |
| 1,099 | 1,345 | `birkin/gateway/core.py` |
| 907 | 1,085 | `birkin/llm.py` |
| 839 | 1,021 | `birkin/slashcommands.py` |
| 820 | 909 | `birkin/runtime.py` |
| 802 | 916 | `birkin/checkpoints.py` |
| 729 | 933 | `birkin/inline_complete.py` |
| 700 | 855 | `birkin/companion.py` |
| 685 | 771 | `birkin/moirai/journal.py` |
| 674 | 804 | `birkin/mnemosyne.py` |
| 601 | 729 | `birkin/moirai/engine.py` |
| 581 | 946 | `birkin/config.py` |
| 553 | 662 | `birkin/cron.py` |
| 545 | 581 | `birkin/workspace/runtime_adapter.py` |
| 538 | 672 | `birkin/agent.py` |
| 537 | 690 | `birkin/codex_session.py` |
| 532 | 658 | `birkin/morpheus.py` |
| 507 | 576 | `birkin/workbench.py` |
| 503 | 614 | `birkin/scheduler.py` |
| 487 | 603 | `birkin/daedalus.py` |

## Largest native modules

| Pure LOC | Physical LOC | Path |
|---:|---:|---|
| 655 | 694 | `macos/BirkinNativeApp/Sources/BirkinNativeShell/NativeShellView.swift` |
| 643 | 719 | `macos/BirkinNativeApp/Sources/BirkinNativeApp/BirkinNativeApp.swift` |
| 540 | 613 | `windows/BirkinNativeApp/tests/Birkin.Native.Protocol.Tests/Transport/BridgeSessionTests.cs` |
| 440 | 490 | `windows/BirkinNativeApp/src/Birkin.Native.Protocol/Transport/BridgeSession.cs` |
| 344 | 388 | `windows/BirkinNativeApp/src/Birkin.Native.Shell/Lifecycle/BridgeSupervisor.cs` |
| 326 | 364 | `windows/BirkinNativeApp/src/Birkin.Native.Shell/ShellCoordinator.OfficeWorkflow.cs` |
| 314 | 329 | `macos/BirkinNativeApp/Sources/BirkinNativeProtocol/NativeProjectionReducer.swift` |
| 297 | 326 | `macos/BirkinNativeApp/Sources/BirkinNativeProtocol/NativeProjectionStore.swift` |

## Interpretation boundary

- `>250 pure LOC` is a structural-review signal, not deletion evidence.
- Test/QA/native-test LOC is kept separate from production deletion savings.
- Working-tree untracked source is included because the checkout contains active uncommitted work.
- This inventory does not assign removable LOC; candidate manifests must trace consumers first.
