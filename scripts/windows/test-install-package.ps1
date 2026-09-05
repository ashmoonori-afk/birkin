$ErrorActionPreference = "Stop"
$root = Join-Path $env:TEMP "birkin-package-selftest-$([guid]::NewGuid().ToString('N'))"
$install = Join-Path $root "install"
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
  Write-Output "windows-package-selftest=PASS"
} finally {
  if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
}
