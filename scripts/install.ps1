# birkin installer (Windows, PowerShell).
#
#   irm https://raw.githubusercontent.com/ashmoonori-afk/birkin/main/scripts/install.ps1 | iex
#
# Installs the `birkin` command using uv (preferred), pipx, or pip --user.
$ErrorActionPreference = "Stop"

$Repo = if ($env:BIRKIN_REPO) { $env:BIRKIN_REPO.TrimEnd("/") } else { "https://github.com/ashmoonori-afk/birkin" }
$Ref  = if ($env:BIRKIN_REF)  { $env:BIRKIN_REF }  else { "main" }
$Spec = "$Repo/archive/$Ref.zip"

Write-Host "==> Installing birkin from $Spec"

function Have($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

function HaveWorkingPython($name, $prefix) {
  if (-not (Have $name)) { return $false }
  try {
    $result = @(& $name @prefix -c 'import sys; sys.stdout.write("birkin-python-probe-v1" if sys.version_info >= (3, 10) else "")' 2>$null)
    return (
      $LASTEXITCODE -eq 0 -and
      $result.Count -eq 1 -and
      $result[0] -ceq "birkin-python-probe-v1"
    )
  } catch {
    return $false
  }
}

function PythonUserScripts($name, $prefix) {
  try {
    $result = @(& $name @prefix -c 'import pathlib, site; print(pathlib.Path(site.USER_BASE) / "Scripts")' 2>$null)
    if ($LASTEXITCODE -eq 0 -and $result.Count -eq 1) {
      return [string]$result[0]
    }
  } catch {
    return $null
  }
  return $null
}

function NormalizePathEntry($value) {
  if ([string]::IsNullOrWhiteSpace($value)) { return $null }
  $expanded = [Environment]::ExpandEnvironmentVariables($value.Trim())
  try {
    $full = [IO.Path]::GetFullPath($expanded)
  } catch {
    return $expanded
  }
  $root = [IO.Path]::GetPathRoot($full)
  if ($root -and $full.Length -gt $root.Length) {
    return $full.TrimEnd(
      [IO.Path]::DirectorySeparatorChar,
      [IO.Path]::AltDirectorySeparatorChar
    )
  }
  return $full
}

function HasPathEntry($entries, $candidate) {
  foreach ($entry in $entries) {
    if ([StringComparer]::OrdinalIgnoreCase.Equals($entry, $candidate)) {
      return $true
    }
  }
  return $false
}

function RegisterUserPath($directory) {
  if ([string]::IsNullOrWhiteSpace($directory)) { return }
  $normalized = NormalizePathEntry $directory
  $processEntries = @(
    $env:Path -split ";" |
      ForEach-Object { NormalizePathEntry $_ } |
      Where-Object { $_ }
  )
  if (-not (HasPathEntry $processEntries $normalized)) {
    $env:Path = if ([string]::IsNullOrWhiteSpace($env:Path)) {
      $normalized
    } else {
      "$normalized;$env:Path"
    }
  }

  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  $userEntries = @(
    $userPath -split ";" |
      ForEach-Object { NormalizePathEntry $_ } |
      Where-Object { $_ }
  )
  if (-not (HasPathEntry $userEntries $normalized)) {
    $updated = if ([string]::IsNullOrWhiteSpace($userPath)) {
      $normalized
    } else {
      "$userPath;$normalized"
    }
    [Environment]::SetEnvironmentVariable("Path", $updated, "User")
    Write-Host "    added $normalized to the user PATH"
  }
}

function VerifyBirkin {
  if (Have "birkin") {
    birkin --version
    if ($LASTEXITCODE -eq 0) { return $true }
  }
  if (HaveWorkingPython "python" @()) {
    python -m birkin --version
    if ($LASTEXITCODE -eq 0) { return $true }
  }
  if (HaveWorkingPython "py" @("-3")) {
    py -3 -m birkin --version
    if ($LASTEXITCODE -eq 0) { return $true }
  }
  return $false
}

$BirkinBinDir = $null
if (Have "uv") {
  Write-Host "    using uv"
  uv tool install --force $Spec
  $candidate = @(& uv tool dir --bin 2>$null)
  if ($LASTEXITCODE -eq 0 -and $candidate.Count -eq 1) {
    $BirkinBinDir = [string]$candidate[0]
  }
} elseif (Have "pipx") {
  Write-Host "    using pipx"
  pipx install --force $Spec
  $candidate = @(& pipx environment --value PIPX_BIN_DIR 2>$null)
  if ($LASTEXITCODE -eq 0 -and $candidate.Count -eq 1) {
    $BirkinBinDir = [string]$candidate[0]
  }
} elseif (HaveWorkingPython "python" @()) {
  Write-Host "    using pip (--user)"
  python -m pip install --user --upgrade $Spec
  $BirkinBinDir = PythonUserScripts "python" @()
} elseif (HaveWorkingPython "py" @("-3")) {
  Write-Host "    using pip (--user)"
  py -3 -m pip install --user --upgrade $Spec
  $BirkinBinDir = PythonUserScripts "py" @("-3")
} else {
  Write-Error "Need one of: uv, pipx, or python. Install Python 3.10+ first."
  exit 1
}

RegisterUserPath $BirkinBinDir
Write-Host "==> Verifying installation"
if (-not (VerifyBirkin)) {
  Write-Error "Installed birkin, but neither 'birkin --version' nor 'python -m birkin --version' succeeded. Open a new PowerShell window and check PATH."
  exit 1
}

Write-Host ""
Write-Host "==> Done. Quick start:"
Write-Host "    birkin setup    # choose and verify a provider"
Write-Host "    birkin chat     # start chatting"
Write-Host "    birkin web      # open the dashboard"
Write-Host "    birkin daemon   # run the 07:00 self-improvement scheduler"
