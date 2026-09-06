# SPDX-License-Identifier: MIT
param([switch]$WithCMake)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Join-Path ([IO.Path]::GetTempPath()) ('capy-cmake-config-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root | Out-Null
$verifier = Join-Path $PSScriptRoot 'verify_windows_configuration.ps1'
$checks = 0
function Check-Cache([string]$Name, [string]$Cache, [string]$Requested, [bool]$Accept, [bool]$Manifest = $true) {
    $dir = Join-Path $root $Name
    New-Item -ItemType Directory -Path $dir | Out-Null
    $Cache | Set-Content -LiteralPath (Join-Path $dir 'CMakeCache.txt') -Encoding ascii
    if ($Manifest) { '' | Set-Content -LiteralPath (Join-Path $dir "build-$Requested.ninja") -Encoding ascii }
    $accepted = $false
    try { & $verifier -BuildDirectory $dir -Configuration $Requested; $accepted = $true } catch { }
    if ($accepted -ne $Accept) { throw "Unexpected result for $Name." }
    $script:checks++
}
$generator = "CMAKE_GENERATOR:INTERNAL=Ninja Multi-Config`n"
Check-Cache 'release' ($generator + 'CMAKE_CONFIGURATION_TYPES:STRING=Release') 'Release' $true
Check-Cache 'debug' ($generator + 'CMAKE_CONFIGURATION_TYPES:STRING=Debug') 'Debug' $true
Check-Cache 'wrong' ($generator + 'CMAKE_CONFIGURATION_TYPES:STRING=Debug') 'Release' $false
Check-Cache 'multi' ($generator + 'CMAKE_CONFIGURATION_TYPES:STRING=Debug;Release') 'Release' $false
Check-Cache 'untyped' ($generator + 'CMAKE_CONFIGURATION_TYPES:UNINITIALIZED=Release') 'Release' $false
Check-Cache 'missing' $generator 'Release' $false
Check-Cache 'single' "CMAKE_GENERATOR:INTERNAL=Ninja`nCMAKE_CONFIGURATION_TYPES:STRING=Release" 'Release' $false
Check-Cache 'no-manifest' ($generator + 'CMAKE_CONFIGURATION_TYPES:STRING=Release') 'Release' $false $false
if ($WithCMake) {
    $source = Join-Path $root 'source'
    New-Item -ItemType Directory -Path $source | Out-Null
    @'
cmake_minimum_required(VERSION 3.24)
project(CapyConfigurationProbe NONE)
add_custom_target(probe ALL COMMAND ${CMAKE_COMMAND} -E echo "CAPY_ACTUAL_CONFIGURATION=$<CONFIG>")
'@ | Set-Content -LiteralPath (Join-Path $source 'CMakeLists.txt') -Encoding ascii
    foreach ($configuration in 'Release','Debug') {
        $dir = Join-Path $root "actual-$configuration"
        & cmake -S $source -B $dir -G 'Ninja Multi-Config' "-DCMAKE_CONFIGURATION_TYPES:STRING=$configuration"
        if ($LASTEXITCODE -ne 0) { throw 'Probe configuration failed.' }
        & $verifier -BuildDirectory $dir -Configuration $configuration
        $output = & cmake --build $dir --config $configuration --target probe 2>&1
        if ($LASTEXITCODE -ne 0 -or ($output -join "`n") -cnotmatch "CAPY_ACTUAL_CONFIGURATION=$configuration") {
            throw 'Probe built a different configuration.'
        }
        $checks++
    }
    $dir = Join-Path $root 'actual-untyped'
    & cmake -S $source -B $dir -G 'Ninja Multi-Config' '-DCMAKE_CONFIGURATION_TYPES=Release'
    if ($LASTEXITCODE -ne 0) { throw 'Untyped reproduction failed.' }
    $line = Get-Content -LiteralPath (Join-Path $dir 'CMakeCache.txt') | Where-Object { $_ -match '^CMAKE_CONFIGURATION_TYPES:' }
    Write-Host "CAPY_UNTYPED_REPRODUCTION=$line"
}
Write-Host "CAPY_CONFIGURATION_TESTS=PASS checks=$checks"
