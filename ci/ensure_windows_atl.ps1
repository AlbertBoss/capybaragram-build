# SPDX-License-Identifier: MIT
param([Parameter(Mandatory=$true)][string]$InstallationPath,
      [Parameter(Mandatory=$true)][string]$ToolsetPath)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows') { throw 'Disposable Windows CI only.' }
$installation = (Resolve-Path -LiteralPath $InstallationPath).Path
$toolset = (Resolve-Path -LiteralPath $ToolsetPath).Path
if (-not $toolset.StartsWith(($installation.TrimEnd('\') + '\VC\Tools\MSVC\'),[StringComparison]::OrdinalIgnoreCase)) { throw 'Toolset outside selected Visual Studio instance.' }
if ((Split-Path -Leaf $toolset) -notlike '14.44.*') { throw 'Expected reviewed MSVC14.44 toolset.' }
$headers = @('atlbase.h','atlcomcli.h')
$missing = @($headers | Where-Object { -not (Test-Path -LiteralPath (Join-Path $toolset "atlmfc\include\$_")) })
if ($missing.Count) {
    $installer = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\setup.exe'
    if (-not (Test-Path -LiteralPath $installer)) { throw 'Official Visual Studio installer is missing.' }
    Write-Host 'Adding Microsoft ATL14.44 component for release symbol tooling on disposable CI.'
    $arguments = 'modify --installPath "' + $installation + '" --add Microsoft.VisualStudio.Component.VC.14.44.17.14.ATL --quiet --norestart --nocache'
    $process = Start-Process -FilePath $installer -ArgumentList $arguments -WindowStyle Hidden -PassThru -Wait
    if ($process.ExitCode -notin @(0,3010)) { throw "ATL component installation failed with code $($process.ExitCode)." }
}
foreach ($header in $headers) {
    if (-not (Test-Path -LiteralPath (Join-Path $toolset "atlmfc\include\$header"))) { throw "Required ATL14.44 header remains absent: $header" }
}
Write-Host 'CAPY_ATL_HEADERS=PASS (atlbase.h and atlcomcli.h, exact selected toolset)'
