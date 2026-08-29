# Windows First Report Journey

Date: 2026-08-29

## Execution status

**Automated install-to-first-chat slice: Pass.**

GitHub Actions run
[33265797616](https://github.com/ashmoonori-afk/birkin/actions/runs/33265797616)
completed successfully on the ephemeral `windows-latest` hosted runner against
commit `5c2bb92e9aa14cd8b4d1ad83151c794cab7908fd`.
Artifact
[`fresh-windows-first-chat`](https://github.com/ashmoonori-afk/birkin/actions/runs/33265797616/artifacts/9718623916)
contains the installer, CLI, missing-Codex, WPF TRX, model-server, chat, and
assistant-reply evidence. GitHub is scheduled to retain it through
2026-09-12.

The hosted run captured:

- The job started at `17:30:23Z`, the WPF import step completed at
  `17:31:39Z`, and the first chat completed at `17:32:19Z`. The ordered
  install-to-WPF-import-tests-to-chat slice therefore finished in 116 seconds,
  below the 10-minute target.
- `scripts/install.ps1` installed exact commit `5c2bb92e` with uv and verified
  Birkin `0.4.325`.
- `birkin --help` and `birkin --version` succeeded; an invalid command returned
  the bounded argparse usage error.
- A Codex-free `PATH` produced the Korean missing-installation message,
  official Windows installer command, retry choice, and alternate-provider
  choice.
- Six focused WPF picker and routed-drop tests passed on Windows, including the
  real `PreviewDrop` route and command payload.
- Pinned Ollama `0.33.2` served `qwen2.5:0.5b` without credentials, and
  `birkin chat` saved the Korean assistant reply
  `안녕하세요. 어떻게 도와드릴까요?`.

This evidence does not claim a rendered interactive desktop session, a Windows
11 retail image, an installed Microsoft Office application, report generation,
approval, export, rollback, or DACL inspection. Those remain in the extended
manual checklist below.

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
| PowerShell installer | Pass | Run 33265797616 `install.txt`, `version.txt`, `help.txt`, and `invalid-command.txt` |
| Missing Codex detection | Pass | Run 33265797616 `setup-missing-codex.txt` |
| WPF picker and drop | Pass | Run 33265797616 `office-import.trx`: 6 executed, 6 passed |
| First credential-free chat | Pass | Run 33265797616 `first-chat.txt` and `assistant-reply.txt` |
| Ten-minute install-to-WPF-tests-to-chat bound | Pass | GitHub job timestamps: 116 seconds |
| First Office report | Not run | Windows UI plus installed Office tier required |
| Rendered Windows UI | Not run | The hosted WPF gate exercised controls without capturing a rendered desktop |
| Cross-platform trust boundaries | Pass | Local trust-boundary bundle: 38 passed; portable documentation and intake contracts: 9 passed |

Do not change a `Not run` result to `Pass` without attaching the command output
or rendered evidence named in the required clean-VM run.
