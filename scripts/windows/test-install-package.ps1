$ErrorActionPreference = "Stop"
$root = Join-Path $env:TEMP "birkin-package-selftest-$([guid]::NewGuid().ToString('N'))"
$install = Join-Path $root "install"
$previousExecutable = [Environment]::GetEnvironmentVariable("BIRKIN_EXECUTABLE", "User")
function New-FakePackage([string]$Version, [string]$Reported) {
  $package = Join-Path $root "package-$Version-$Reported"
  New-Item -ItemType Directory -Force -Path (Join-Path $package "app") | Out-Null
  Set-Content -LiteralPath (Join-Path $package "app\Birkin.Native.App.exe") -Value "fixture"
  "@echo off`necho birkin $Reported" | Set-Content -LiteralPath (Join-Path $package "birkin.cmd") -Encoding ascii
  @{ product_version = $Version; protocol_version = 1; signed = $false } | ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $package "manifest.json") -Encoding utf8
  $hashes = [ordered]@{}
  Get-ChildItem $package -File -Recurse | ForEach-Object {
    $hashes[[IO.Path]::GetRelativePath($package, $_.FullName)] = (Get-FileHash $_.FullName -Algorithm SHA256).Hash
  }
  $hashes | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $package "SHA256SUMS.json") -Encoding utf8
  New-Item -ItemType File -Path (Join-Path $package "package.cat") | Out-Null
  return $package
}
try {
  $v1 = New-FakePackage "1.0.0" "1.0.0"
  $unsignedRejected = $false
  try { & (Join-Path $PSScriptRoot "install-package.ps1") -PackageRoot $v1 -InstallRoot $install } catch { $unsignedRejected = $true }
  if (-not $unsignedRejected) { throw "unsigned customer install was accepted" }
  & (Join-Path $PSScriptRoot "install-package.ps1") -PackageRoot $v1 -InstallRoot $install -AllowUnsignedDevelopment
  & (Join-Path $install "current\birkin.cmd") --version | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "restart probe failed" }
  $bad = New-FakePackage "2.0.0" "9.9.9"
  try { & (Join-Path $PSScriptRoot "install-package.ps1") -PackageRoot $bad -InstallRoot $install -AllowUnsignedDevelopment } catch {}
  $state = Get-Content (Join-Path $install "install-state.json") -Raw | ConvertFrom-Json
  if ($state.status -ne "failed_previous_preserved" -or -not (Test-Path (Join-Path $install "current\birkin.cmd"))) {
    throw "failed update did not preserve the installed version"
  }
  $v2 = New-FakePackage "2.0.0" "2.0.0"
  try { & (Join-Path $PSScriptRoot "install-package.ps1") -PackageRoot $v2 -InstallRoot $install -AllowUnsignedDevelopment -TestFailAfterPreviousMove } catch {}
  $state = Get-Content (Join-Path $install "install-state.json") -Raw | ConvertFrom-Json
  $reported = (& (Join-Path $install "current\birkin.cmd") --version | Out-String).Trim()
  if ($state.status -ne "failed_previous_restored" -or $reported -notmatch "1.0.0") {
    throw "failed swap did not restore the previous installation"
  }
  Write-Output "windows-package-selftest=PASS"
} finally {
  [Environment]::SetEnvironmentVariable("BIRKIN_EXECUTABLE", $previousExecutable, "User")
  $resolvedRoot = [IO.Path]::GetFullPath($root)
  $resolvedTemp = [IO.Path]::GetFullPath($env:TEMP).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
  if ($resolvedRoot.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $resolvedRoot)) {
    Remove-Item -LiteralPath $resolvedRoot -Recurse -Force
  }
}
