param(
  [Parameter(Mandatory)][string]$PackageRoot,
  [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "Birkin"),
  [switch]$AllowUnsignedDevelopment
)
$ErrorActionPreference = "Stop"

$package = (Resolve-Path -LiteralPath $PackageRoot).Path
$manifestPath = Join-Path $package "manifest.json"
$catalogPath = Join-Path $package "package.cat"
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.product_version -notmatch '^\d+\.\d+\.\d+$' -or $manifest.protocol_version -ne 1) {
  throw "Package manifest version contract is invalid."
}
if (-not $manifest.signed -and -not $AllowUnsignedDevelopment) {
  throw "Unsigned development packages are not customer-ready."
}
if ($manifest.signed) {
  $signature = Get-AuthenticodeSignature -LiteralPath $catalogPath
  $catalogStatus = Test-FileCatalog -CatalogFilePath $catalogPath -Path $package -FilesToSkip "package.cat"
  if ($signature.Status -ne "Valid" -or $catalogStatus -ne "Valid" -or
      -not [StringComparer]::OrdinalIgnoreCase.Equals($signature.SignerCertificate.Thumbprint, $manifest.signer_thumbprint)) {
    throw "Package signature is invalid."
  }
}
$hashes = Get-Content -LiteralPath (Join-Path $package "SHA256SUMS.json") -Raw | ConvertFrom-Json
foreach ($entry in $hashes.PSObject.Properties) {
  $file = Join-Path $package $entry.Name
  if (-not (Test-Path -LiteralPath $file -PathType Leaf) -or
      (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $entry.Value) {
    throw "Package file integrity failed: $($entry.Name)"
  }
}

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
$stage = Join-Path $InstallRoot ".stage-$([guid]::NewGuid().ToString('N'))"
$current = Join-Path $InstallRoot "current"
$backup = Join-Path $InstallRoot "previous"
$swapped = $false
try {
  Copy-Item -LiteralPath $package -Destination $stage -Recurse
  $reported = (& (Join-Path $stage "birkin.cmd") --version | Out-String).Trim()
  if ($LASTEXITCODE -ne 0 -or $reported -notmatch [regex]::Escape($manifest.product_version)) {
    throw "Bundled runtime version handshake failed."
  }
  if (-not (Test-Path -LiteralPath (Join-Path $stage "app\Birkin.Native.App.exe") -PathType Leaf)) {
    throw "Native app executable is missing."
  }
  if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force }
  if (Test-Path -LiteralPath $current) { Move-Item -LiteralPath $current -Destination $backup }
  Move-Item -LiteralPath $stage -Destination $current
  $swapped = $true
  [Environment]::SetEnvironmentVariable("BIRKIN_EXECUTABLE", (Join-Path $current "birkin.cmd"), "User")
  @{ version = $manifest.product_version; previous_available = (Test-Path -LiteralPath $backup); status = "ready" } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $InstallRoot "install-state.json") -Encoding utf8
} catch {
  if ($swapped -and (Test-Path -LiteralPath $backup)) {
    Remove-Item -LiteralPath $current -Recurse -Force -ErrorAction SilentlyContinue
    Move-Item -LiteralPath $backup -Destination $current
  }
  @{ version = $manifest.product_version; status = "failed_previous_preserved"; reason = $_.Exception.Message } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $InstallRoot "install-state.json") -Encoding utf8
  throw
} finally {
  if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
}
