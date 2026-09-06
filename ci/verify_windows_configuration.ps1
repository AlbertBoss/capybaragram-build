# SPDX-License-Identifier: MIT
param(
    [Parameter(Mandatory=$true)][string]$BuildDirectory,
    [Parameter(Mandatory=$true)][ValidateSet('Debug','Release')][string]$Configuration
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$cache = Get-Content -LiteralPath (Join-Path $BuildDirectory 'CMakeCache.txt') -Raw
# Never print the cache: it contains the owner's application credentials.
if ($cache -cnotmatch '(?m)^CMAKE_GENERATOR:INTERNAL=Ninja Multi-Config\r?$') {
    throw 'Expected Ninja Multi-Config generator.'
}
if ($cache -cnotmatch ('(?m)^CMAKE_CONFIGURATION_TYPES:STRING=' + $Configuration + '\r?$')) {
    throw 'Expected one explicitly typed build configuration; cache contents withheld.'
}
if (-not (Test-Path -LiteralPath (Join-Path $BuildDirectory "build-$Configuration.ninja") -PathType Leaf)) {
    throw 'Requested configuration has no generated Ninja build file.'
}
Write-Host "CAPY_BUILD_CONFIGURATION=PASS profile=$Configuration"
