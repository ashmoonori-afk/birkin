# Birkin Native Windows Test Matrix

Status: implemented local matrix and W7 CI definition; remote W7 execution unproven
Primary hosted runner: GitHub `windows-latest`
Customer OS evidence: Windows 10 22H2 and current Windows 11

## 1. Matrix by layer and platform

| Suite | Ubuntu | macOS | Windows | Purpose |
| --- | --- | --- | --- | --- |
| Python workspace/runtime | Required | Required | Required | Preserve the existing authority independently of either client. |
| Python native protocol, schemas, projection, loopback | Required | Required | Required | Prove the common wire boundary and the already-working Windows loopback path. |
| Python POSIX UDS and peer UID | Required | Required | Not applicable | Exercise UDS modes, peer credentials, and POSIX path rules only where they exist. |
| C# `Birkin.Native.Protocol.Tests` | Required | Required | Required | Keep framing, JSON, handshake, cursor, and projections platform-neutral. |
| C# `Birkin.Native.Shell.Tests` | Required | Required | Required | Keep lifecycle and presentation state independent of WPF. |
| C# `Birkin.Native.App.Tests` | Not run | Not run | Required | Exercise WPF binding, keyboard, accessibility metadata, startup, and real windows. |
| C# live Python bridge journey | Not run | Not run | Required | Spawn the real console-script bridge, authenticate, subscribe, and render its snapshot in WPF. |
| Swift package | Not run | Required | Not run | Preserve the existing macOS client and consume the same Python vectors. |
| Korean IME and Narrator hardware pass | Not run | Not run | Required before beta/release | Cover behavior hosted CI cannot establish with a real IME candidate UI or assistive technology. |
| MSI install/upgrade/uninstall | Not run until packaging phase | Not run | Required after packaging exists | Verify the signed artifact rather than a repository build. |

`Birkin.Native.Protocol` and `Birkin.Native.Shell` target `net8.0`; a WPF type in
either project is therefore a build failure on Ubuntu and macOS, not merely a
style violation.

## 2. Focused local commands

All paths below are from the repository root and are valid in PowerShell on
Windows.

```powershell
# Pure protocol
dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.Protocol.Tests\Birkin.Native.Protocol.Tests.csproj -c Debug

# Pure shell state
dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.Shell.Tests\Birkin.Native.Shell.Tests.csproj -c Debug

# WPF and live bridge
dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.App.Tests\Birkin.Native.App.Tests.csproj -c Debug

# Real bridge plus deterministic production-composed windows
dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.App.Tests\Birkin.Native.App.Tests.csproj -c Release --filter "TestCategory=LiveBridge"

# Fast deterministic Office window seam: real WPF/codec/reducer/Python bridge, no provider
dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.App.Tests\Birkin.Native.App.Tests.csproj -c Release --filter "TestCategory=OfficeWorkflow&TestCategory=DeterministicWindow"

# Existing-account phase-exit filter (recorded pass was local; dispatch job is unproven)
dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.App.Tests\Birkin.Native.App.Tests.csproj -c Release --filter "TestCategory=OfficeWorkflow&TestCategory=ExistingAccountProvider"

# Existing Python Windows/native boundary
uv run --frozen pytest -q tests/test_native_windows_import.py
```

The live test launches the bridge through `ProcessStartInfo` with an argument
list equivalent to this console-script command:

```powershell
uv run --frozen birkin native-bridge serve --transport loopback --root $temporaryRoot
```

It must never use `python -m birkin.cli`.

## 3. Deterministic real-window journeys

The original `LiveBridgeWindowTests.ConnectsAndRendersPythonSnapshot` name below
is historical Phase 1 context. Current production-composed coverage is
`DeterministicWindowJourneyTests` plus
`ProviderOfficeDeterministicSeamTests`: both show a real WPF `MainWindow`, use
the real Python bridge and codec/reducer, and rely on `BridgeSession` rather
than a manual `ReceiveAsync` path. The deterministic Office seam explicitly
performs zero provider invocations. The historical Phase 1 journey did all of
the following in one test process:

1. Create a unique temporary workspace root.
2. Subscribe to redirected stdout and process-exit signals before starting the
   bridge process.
3. Start `uv run --frozen birkin native-bridge serve --transport loopback
   --root <temp>` and await exactly one parsed `listening` announcement with a
   30-second cancellation deadline.
4. Pass that announcement through the same `DevelopmentPreviewRunner` used by
   the executable; no test transport or injected snapshot is permitted.
5. On a dedicated STA dispatcher thread, construct and show `MainWindow` and
   subscribe to `ContentRendered` and `ShellCoordinator.SnapshotApplied` before
   calling connect.
6. Await both signals with a 30-second cancellation deadline.
7. Assert that the visible named WPF elements show the Python-produced
   `session_id`, cursor, reset reason, and at least the canonical panel count;
   assert the model records protocol 1, the announced instance, and loopback.
8. Close the window on its dispatcher, send orderly client shutdown, and stop
   only the `Process` object the harness itself spawned.
9. Assert bridge stderr is empty and delete the temporary root after the
   process exits.

There are no fixed sleeps, retry polls, or wait-for-time loops. Event handlers
are installed before their triggering actions. Every wait has a cancellation
deadline so a failure terminates rather than hanging CI. The displayed session,
cursor, reset reason, and panel count are machine-consumed values; tests do not
pin headings, error prose, or document copy.

## 4. Protocol conformance suite

The protocol fixture is generated once by Python and consumed by both clients.
The checked-in source is:

`macos/BirkinNativeApp/Tests/BirkinNativeProtocolTests/GoldenVectors/native-protocol-vectors.json`

`Birkin.Native.Protocol.Tests.csproj` links that exact file as test content; it
does not commit a Windows copy. The same rule applies to
`native-projection-vectors.json`.

The generator freshness gate is:

```powershell
uv run --frozen python scripts/native/generate_golden_vectors.py
uv run --frozen python scripts/native/generate_projection_vectors.py
git diff --exit-code -- macos/BirkinNativeApp/Tests/BirkinNativeProtocolTests/GoldenVectors/native-protocol-vectors.json macos/BirkinNativeApp/Tests/BirkinNativeProtocolTests/GoldenVectors/native-projection-vectors.json
```

For every valid frame, Python, Swift, and C# must agree on the machine values,
frame byte count, and byte-identical re-encoding. For the projection fixture,
both clients must agree with Python after the snapshot, every contiguous event,
and the gap event.

Phase 2 extends `scripts/native/generate_golden_vectors.py` and its catalogue to
emit invalid raw frames with an expected stable error code. Required negative
classes are duplicate object keys, invalid UTF-8, lone surrogates, non-finite
numbers, signed-64 overflow, parser depth, body depth, frame length, trailing
data, identifier syntax, duplicate IDs, direction, state, and correlation.
Tests compare codes only, not public messages.

The three required conformance commands are:

```powershell
# Python generation and self-check
uv run --frozen python scripts/native/generate_golden_vectors.py

# C# consumer
dotnet test .\windows\BirkinNativeApp\tests\Birkin.Native.Protocol.Tests\Birkin.Native.Protocol.Tests.csproj -c Release --filter "TestCategory=Conformance"

# Swift consumer (run on macOS)
swift test --package-path macos/BirkinNativeApp
```

A protocol pull request cannot update only one client. Generated fixture change,
Python codec/schema tests, Swift conformance, C# conformance, and the normative
protocol document are one required change set.

## 5. GitHub Actions definition

`.github/workflows/native-windows.yml` currently defines these seven jobs. The
superseded decision named CPython `3.12`; the workflow itself is the authority
for its current pinned runtime:

| Job | Runner | Actual command/gate |
| --- | --- | --- |
| `python-windows` | `windows-latest` | Workflow-pinned CPython; `uv sync --frozen --all-extras --all-groups`; full `pytest` with exactly two `--deselect` arguments. |
| `dotnet-portable` | `ubuntu-latest`, `macos-latest`, `windows-latest` matrix | Restore and test the Protocol and Shell projects in Release with `--no-restore --filter "TestCategory!=LiveBridge&TestCategory!=WindowsOnly"`. |
| `wpf-windows` | `windows-latest` | Workflow-pinned CPython; set `UV_NO_SYNC=1`; `uv sync --frozen --all-extras --all-groups`; restore/build the solution; run the unfiltered full Release solution with `--no-build`. |
| `live-bridge-window` | `windows-latest` | Set `UV_NO_SYNC=1`; `uv sync --frozen --all-extras --all-groups`; build App.Tests and run `--filter "TestCategory=LiveBridge"`; upload only TRX on failure. |
| `protocol-fixture-freshness` | `ubuntu-latest` | Regenerate protocol, projection, and invalid vectors; reject tracked or untracked fixture drift. |
| `swift-conformance` | `macos-latest` | Run the full `swift test --package-path macos/BirkinNativeApp` suite. |
| `provider-office-gate` | dispatch-only protected self-hosted Windows x64 | On a protected ref and environment, run only the exact `OfficeWorkflow&ExistingAccountProvider` intersection; no artifact upload. |

The concrete WPF commands are:

```powershell
uv sync --frozen --all-extras --all-groups
dotnet restore .\windows\BirkinNativeApp\BirkinNativeApp.sln
dotnet build .\windows\BirkinNativeApp\BirkinNativeApp.sln -c Release --no-restore
dotnet test .\windows\BirkinNativeApp\BirkinNativeApp.sln -c Release --no-build --logger "trx;LogFilePrefix=native-windows"
```

The portable matrix applies the same explicit exclusion to each project:

```powershell
dotnet test windows/BirkinNativeApp/tests/Birkin.Native.Protocol.Tests/Birkin.Native.Protocol.Tests.csproj -c Release --no-restore --filter "TestCategory!=LiveBridge&TestCategory!=WindowsOnly"
dotnet test windows/BirkinNativeApp/tests/Birkin.Native.Shell.Tests/Birkin.Native.Shell.Tests.csproj -c Release --no-restore --filter "TestCategory!=LiveBridge&TestCategory!=WindowsOnly"
```

The workflow has path filters for `windows/**`, `birkin/native/**`,
`birkin/office/**`, `birkin/workspace/**`, `scripts/native/**`,
`tests/test_native_office*.py`, the golden-vector directory,
`docs/native-app/**`, `pyproject.toml`, `uv.lock`, and its contract files. The
`windows/**` path includes the checked-in App test Office fixtures. A scheduled
weekly run is defined. Repository evidence proves this YAML contract
through `tests/test_native_windows_ci_contract.py`; it does **not** prove that
GitHub ran any job or that branch protection requires it.

`provider-office-gate` is intentionally absent from push/PR execution and runs
only on protected-ref `workflow_dispatch`. The protected environment
`native-windows-existing-account`, the matching labels
`self-hosted, Windows, X64, birkin-existing-account`, and existing-account
provider authentication are external administrator prerequisites. W7 did not
create, inspect, or remotely execute them. Its verification log exists only as
private ignored local evidence at
`.omo/evidence/native-windows-20260824/remediation/w7/verification.txt`; remote
readers cannot access it from the repository or pull request.

Secrets, bootstrap records, capabilities, complete workspace snapshots, raw
stderr, and screenshots are never uploaded. Local screenshots are private,
ignored evidence rather than committed, PR-attached, or remote CI artifacts.
The current failed-live path uploads only TRX.

## 6. Windows gating for the two POSIX symlink tests

These two tests are Unix-only capability tests:

- `tests/test_native_transport.py::test_uds_listener_rejects_symlinked_parent`
- `tests/test_native_transport.py::test_uds_listener_rejects_symlinked_socket_path`

On the target Windows account they fail before the product behavior is reached
with `WinError 1314` because the account lacks symlink-creation privilege.
They are not xfailed, weakened, or "fixed" in the Windows client plan. Ubuntu
and macOS continue to require them.

The `python-windows` job environment-gates only those node IDs:

```powershell
./.venv/Scripts/python.exe -m pytest -q -o addopts="" --deselect tests/test_native_transport.py::test_uds_listener_rejects_symlinked_parent --deselect tests/test_native_transport.py::test_uds_listener_rejects_symlinked_socket_path
```

The job logs the two deselections. All other tests run. This is the sole Windows
exception; a broader `test_native_transport.py` exclusion is forbidden.

## 7. Behavioral coverage by phase

### Phase 1: development preview

- strict valid frame decode/encode and envelope validation;
- announcement/discovery parsing and real loopback handshake;
- exact server-version gate;
- initial snapshot application;
- real WPF window binding and cleanup.

### Phase 2: resilient read-only client

- all malformed-frame classes and error-code parity;
- event contiguity, gap replay, surface revision repair, instance reset;
- capability renewal and expiry;
- heartbeat, bounded backpressure, disconnect, deterministic reconnect;
- external process never terminated, owned process only terminated through its
  returned handle, and five exits in 60 seconds stops restart;
- wrong/expired one-shot bootstrap refusal and the authenticated owner-only
  Python discovery boundary;
- deferred LOW hardening: C# handle-level final-path, reparse/owner, and
  protected-DACL verification (not a current green claim).

### Phase 3: core office workflow

- stable command ID and expected-cursor behavior;
- stale cursor preserves the draft but does not replay it;
- file import stays jailed and Python-owned;
- three jailed imports, Python spreadsheet comparison, sealed report/diff
  approval, visible pre-approval Diff, UI approval, structural OOXML save, and
  Activity receipt through real Python authority;
- deterministic fast regressions use the production-composed real WPF window,
  real bridge, and no provider; one separate existing-account `codex-cli`
  phase-exit run passed locally. Historical W6 provider screenshots are
  `remediation/w6/pre-approval-diff.png` and
  `remediation/w6/post-save-activity-office.png`; final G local visual evidence
  is `final-review-fixes/g/pre-approval-diff-1500x940.png`,
  `post-save-activity-office-1500x940.png`, and
  `post-save-office-1100x700.png`. These paths are beneath the private ignored
  `.omo/evidence/native-windows-20260824/` tree and are not repository, PR, or
  remote CI artifacts;
- interruption and restart recover canonical outcomes rather than optimistic UI
  state.

### Phase 4: desktop quality

- keyboard-only journeys and focus restoration;
- high contrast, 100/125/200 percent scaling, large text, and reduced motion;
- notification navigation without authorization;
- real Microsoft Korean IME composition;
- optional product surfaces only when advertised.

### Phase 5: packaged release

- clean-machine MSI install, launch, upgrade, downgrade refusal, repair, and
  uninstall;
- helper/hash manifest verification and tamper refusal;
- Authenticode chain and timestamp verification;
- complete workflow through the installed signed executable with no repository,
  host Python, uv, or developer override available.

## 8. Korean IME and accessibility evidence

Hosted tests verify `TextCompositionGuard` state transitions and that Enter does
not submit while composition is active, but synthetic events are not accepted
as proof of Korean IME quality.

Before beta and every public release, run the visible app on Windows 10 22H2 and
current Windows 11 with Microsoft Korean IME, 2-set keyboard. Verify Hangul
syllable composition, backspace within composition, candidate selection,
Korean/English toggle, multiline paste, Enter versus Shift+Enter, focus change,
reconnect while a draft exists, and 125/200 percent display scaling. No composed
text may be submitted early or lost.

The same machines run keyboard-only and Narrator journeys at normal and high
contrast. Automation IDs, accessible names, focus order, live-region restraint,
and visible focus are release evidence. A CI screenshot or unit test does not
replace these hardware checks.

## 9. Determinism rules

- Subscribe to the exact process, connection, projection, dispatcher, or UI
  event before triggering it.
- Await that signal with a bounded cancellation token.
- Do not use `Thread.Sleep`, `Task.Delay` as polling, arbitrary retry loops, or
  repeated UI-tree polling in tests.
- Reconnect and supervisor tests inject a fake monotonic clock and explicit
  exit signals.
- Mocks may cover a pure reducer or presenter; handshake and phase-exit journeys
  use the real frame codec, and the vertical slice uses the real Python bridge.
- Test protocol values and rendered machine state, not prose or prompt text.
