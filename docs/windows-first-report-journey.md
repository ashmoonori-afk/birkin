# Windows First Report Journey

Date: 2026-08-29

## Execution status

The fresh-Windows-VM journey was not executed in this worktree session. The
available workstation is Darwin arm64. The Windows-only WPF test project cannot
load `Microsoft.NET.Sdk.WindowsDesktop.targets` from the installed macOS .NET
8 SDK, so this document does not claim rendered Windows evidence.

The following cross-platform evidence was captured:

- Portable picker, drop, chip, live-refusal, and visual-state contracts: 5
  passed.
- Python jailed import and runtime adapter regression bundle: 35 passed.
- Windows Shell authority and imported-receipt suite: 78 passed.
- Windows Protocol suite: 134 passed.
- Codex probe, retry, and model picker suite: 24 passed.
- A real local `codex --version` probe resolved
  `/opt/homebrew/bin/codex`; this proves the probe surface, not Windows
  installation behavior.

## Required clean-VM run

Use a new Windows 11 VM with no Birkin configuration and no trusted developer
toolchain state.

| Step | Command or action | Record |
|---|---|---|
| Establish baseline | `Get-Command python, py, uv, pipx, codex -ErrorAction SilentlyContinue` | Every resolved path and whether it is under `Microsoft\WindowsApps` |
| Install Birkin | `irm https://raw.githubusercontent.com/ashmoonori-afk/birkin/main/scripts/install.ps1 \| iex` | Installer-selected tool, exit code, and full stdout |
| Verify command | `birkin --version`; `birkin --help` | Version and subcommand list |
| Exercise invalid command | `birkin definitely-not-a-command` | Non-zero exit and bounded usage error |
| Recover Codex | Run `birkin setup` with Codex absent; execute the displayed installer; select `설치 후 다시 확인` | Installer command, retry result, and proof that the provider step did not restart |
| Persist data root | `setx BIRKIN_HOME "$env:USERPROFILE\.birkin"` | User-scope registry value, unchanged current-process value, populated value in a new PowerShell |
| Install Office tier | `python -m pip install ".[office]"` from the reviewed source checkout | Exit code and installed Birkin version |
| Start the journey | `birkin chat` | Ready status with no provider error |
| Import by picker | In Birkin for Windows, Browse to one XLSX | Read-only path field, one `file.import`, imported-file chip |
| Import by drop | Drop one DOCX anywhere in the window | Full-window overlay, one `file.import`, imported-file chip |
| Reject ambiguous drop | Drop two files together | No command submission and an inline live message |
| Request report | `incoming의 매출.xlsx를 요약해서 보고서 초안을 만들어줘` | Office routing, progress states, draft destination |
| Review authority | `birkin review` | Source, destination, operations, overwrite decision, and approval result |
| Confirm output | Open the approved destination and compare it with the source | Source unchanged, output present, receipt ID |
| Inspect protection | `icacls "$env:USERPROFILE\.birkin"` | Owner-only inheritable DACL |
| Clean persistence | `reg delete HKCU\Environment /v BIRKIN_HOME /f` | Variable absent in a new PowerShell |

## Acceptance record

| Surface | Result | Evidence |
|---|---|---|
| PowerShell installer | Not run | Fresh Windows VM required |
| Missing Codex recovery | Not run | Fresh Windows VM required |
| WPF picker and drop | Not run | WindowsDesktop SDK and rendered window required |
| First Office report | Not run | Windows UI plus installed Office tier required |
| Cross-platform trust boundaries | Pass | Test counts listed above |

Do not change a `Not run` result to `Pass` without attaching the command output
or rendered evidence named in the required clean-VM run.
