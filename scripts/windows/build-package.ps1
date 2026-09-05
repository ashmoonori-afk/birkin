param(
  [Parameter(Mandatory)][string]$OutputDirectory,
  [string]$CertificateThumbprint = ""
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$output = [IO.Path]::GetFullPath($OutputDirectory)
if ((Test-Path -LiteralPath $output) -and (Get-ChildItem -LiteralPath $output -Force | Select-Object -First 1)) {
  throw "OutputDirectory must be absent or empty."
}
New-Item -ItemType Directory -Force -Path $output | Out-Null
$version = (& uv run python -c "import birkin; print(birkin.__version__)" | Out-String).Trim()

dotnet publish (Join-Path $root "windows\BirkinNativeApp\src\Birkin.Native.App\Birkin.Native.App.csproj") `
  -c Release -r win-x64 --self-contained true -o (Join-Path $output "app")
if ($LASTEXITCODE -ne 0) { throw "Native app publish failed." }
uv python install 3.13
if ($LASTEXITCODE -ne 0) { throw "Bundled Python installation failed." }
$python = (& uv python find --system 3.13 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $python)) { throw "Bundled Python was not found." }
Copy-Item -LiteralPath (Split-Path $python) -Destination (Join-Path $output "runtime") -Recurse
$bundledPython = Join-Path $output "runtime\python.exe"
uv pip install --python $bundledPython --target (Join-Path $output "runtime\Lib\site-packages") $root
if ($LASTEXITCODE -ne 0) { throw "Birkin runtime installation failed." }
@"
@echo off
set "PYTHONPATH=%~dp0runtime\Lib\site-packages"
"%~dp0runtime\python.exe" -m birkin %*
"@ | Set-Content -LiteralPath (Join-Path $output "birkin.cmd") -Encoding ascii
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "install-package.ps1") -Destination $output

$signed = -not [string]::IsNullOrWhiteSpace($CertificateThumbprint)
@{ product_version = $version; protocol_version = 1; runtime = "bundled-cpython-3.13"; signed = $signed;
   signer_thumbprint = $(if ($signed) { $CertificateThumbprint } else { $null }); channel = $(if ($signed) { "release" } else { "development" }) } |
  ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output "manifest.json") -Encoding utf8
$hashes = [ordered]@{}
Get-ChildItem -LiteralPath $output -File -Recurse | Where-Object Name -NotIn @("SHA256SUMS.json", "package.cat") | ForEach-Object {
  $relative = [IO.Path]::GetRelativePath($output, $_.FullName)
  $hashes[$relative] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
}
$hashes | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output "SHA256SUMS.json") -Encoding utf8
if ($signed) {
  New-FileCatalog -Path $output -CatalogFilePath (Join-Path $output "package.cat") -CatalogVersion 2.0 | Out-Null
  $certificate = Get-Item -LiteralPath "Cert:\CurrentUser\My\$CertificateThumbprint"
  $result = Set-AuthenticodeSignature -FilePath (Join-Path $output "package.cat") -Certificate $certificate -TimestampServer "http://timestamp.digicert.com"
  if ($result.Status -ne "Valid") { throw "Package catalog signing failed: $($result.Status)" }
} else {
  New-Item -ItemType File -Path (Join-Path $output "package.cat") | Out-Null
}
