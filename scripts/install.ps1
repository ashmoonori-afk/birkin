# birkin installer (Windows, PowerShell).
#
#   irm https://raw.githubusercontent.com/ashmoonori-afk/birkin/main/scripts/install.ps1 | iex
#
# Installs the `birkin` command using uv (preferred), pipx, or pip --user.
$ErrorActionPreference = "Stop"

$Repo = if ($env:BIRKIN_REPO) { $env:BIRKIN_REPO } else { "https://github.com/ashmoonori-afk/birkin" }
$Ref  = if ($env:BIRKIN_REF)  { $env:BIRKIN_REF }  else { "main" }
$Spec = "git+$Repo@$Ref"

Write-Host "==> Installing birkin from $Spec"

function Have($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

if (Have "uv") {
  Write-Host "    using uv"
  uv tool install --force $Spec
} elseif (Have "pipx") {
  Write-Host "    using pipx"
  pipx install --force $Spec
} elseif (Have "python") {
  Write-Host "    using pip (--user)"
  python -m pip install --user --upgrade $Spec
} elseif (Have "py") {
  Write-Host "    using pip (--user)"
  py -3 -m pip install --user --upgrade $Spec
} else {
  Write-Error "Need one of: uv, pipx, or python. Install Python 3.10+ first."
  exit 1
}

Write-Host ""
Write-Host "==> Done. Quick start:"
Write-Host '    $env:ANTHROPIC_API_KEY = "sk-ant-..."   # your key'
Write-Host "    birkin                                   # start chatting"
Write-Host "    birkin web                               # open the dashboard"
Write-Host "    birkin daemon                            # nightly 04:00 self-improvement"
if (-not (Have "birkin")) {
  Write-Host ""
  Write-Host "Note: if 'birkin' is not found, add your Python/uv Scripts dir to PATH."
}
