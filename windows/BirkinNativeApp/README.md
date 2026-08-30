# Birkin for Windows

Birkin for Windows is a WPF development preview that connects to the local
`birkin native-bridge` process. The window opens before the bridge connection
finishes. If the CLI is missing, exits repeatedly, fails its handshake, or does
not announce an endpoint within 15 seconds, the app keeps running and shows a
reason, recovery instructions, an executable-path field, and a retry action.

## Requirements

- Windows 10 or Windows 11
- .NET 8 SDK
- Python 3.10 or newer
- The Birkin CLI installed locally
- `uv` when running the complete repository test suite

Install Birkin from the repository root:

```powershell
py -3 -m pip install .
birkin setup
```

Confirm that Windows can find the CLI:

```powershell
where.exe birkin
birkin --help
```

## Build

Run these commands from the repository root:

```powershell
dotnet restore .\windows\BirkinNativeApp\BirkinNativeApp.sln
dotnet build .\windows\BirkinNativeApp\BirkinNativeApp.sln -c Release --no-restore
```

WPF projects require Windows. The portable Protocol and Shell projects can also
be tested on macOS or Linux.

## Run

```powershell
dotnet run --project .\windows\BirkinNativeApp\src\Birkin.Native.App\Birkin.Native.App.csproj -c Release
```

By default, the app starts:

```text
birkin native-bridge serve --transport loopback
```

The status indicator is gray while disconnected, amber while connecting,
green only when ready, and red after a failure.

## Configure the CLI path

The preferred setup is to place `birkin.exe` on `PATH`. Restart the terminal
and the Windows app after changing `PATH`.

If the CLI is installed outside `PATH`, enter its fully qualified path in the
first-run failure card and select **경로 저장 후 다시 시도**. The app stores that
path in the current-user `BIRKIN_EXECUTABLE` environment variable and retries
immediately.

The same setting can be written manually:

```powershell
setx BIRKIN_EXECUTABLE "C:\path\to\Python\Scripts\birkin.exe"
```

For one PowerShell session only:

```powershell
$env:BIRKIN_EXECUTABLE = "C:\path\to\Python\Scripts\birkin.exe"
```

## First-run failures

| Code | Meaning | Recovery |
| --- | --- | --- |
| `E_CLI_LAUNCH` | Windows could not start the configured Birkin executable. | Install Birkin, fix `PATH`, or configure the full executable path, then retry. |
| `E_CLI_TIMEOUT` | The CLI did not announce a bridge endpoint within 15 seconds. | Check the executable and retry. |
| `E_CLI_STARTUP` | The CLI started but its bridge announcement or handshake failed. | Run the native bridge command in a terminal, inspect the error, then retry. |
| `E_CLI_CRASH_LOOP` | The CLI exited five times within one minute. | Resolve the CLI failure before retrying. |

The failure card never renders raw exception messages, process IDs, or private
filesystem paths.

## Test

```powershell
uv sync --all-extras --all-groups
dotnet test .\windows\BirkinNativeApp\BirkinNativeApp.sln -c Release
```

The Windows suite includes these user-facing proofs:

- `FirstRunWindowTests` starts the real WPF executable with an isolated `PATH`,
  confirms the Korean missing-CLI guidance, invokes **다시 시도**, and verifies
  that the recoverable failure state returns.
- `StartupFailureViewTests` renders the complete recovery card and verifies the
  executable-path and retry actions.
- `WorkspaceSnapshotViewTests` drives every connection state and verifies that
  the status indicator uses the disconnected, connecting, ready, and failed
  brushes truthfully.

The Windows CI workflow renders the first-run failure card and uploads
`.omo/evidence/native-shell/windows-first-run-failure.png`.
