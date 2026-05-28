# Run birkin's live-LLM smoke suite (Windows / PowerShell).
#
# Requires one of: $env:ANTHROPIC_API_KEY, or `claude` / `codex` on PATH.
$ErrorActionPreference = "Stop"

function Have($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

if (-not $env:ANTHROPIC_API_KEY -and -not (Have "claude") -and -not (Have "codex")) {
    Write-Error "FAIL: no backend available (need ANTHROPIC_API_KEY or claude/codex CLI)"
    exit 2
}

$env:BIRKIN_LIVE = "1"
Write-Host "→ running live tests…"
pytest -m live --no-header -q @args
if ($LASTEXITCODE -ne 0) {
    Write-Error "FAIL: live suite failed"
    exit 1
}
Write-Host "PASS: live suite green"
