# SPDX-License-Identifier: MIT
# Baseline build verified; online preview adds reviewed identity and owner API preparation.
param(
    [Parameter(Mandatory=$true)][ValidateSet('Preflight','Build','Collect')][string]$Phase,
    [ValidateSet('Baseline','Preview','Candidate')][string]$Profile = 'Baseline'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$sdk = '10.0.26100.0'
$toolset = '14.44'
if (-not $env:GITHUB_WORKSPACE -or -not $env:RUNNER_TEMP) { throw 'Run only on the disposable GitHub runner.' }
$root = Join-Path $env:GITHUB_WORKSPACE 'TBuild'
$src = Join-Path $root 'tdesktop'
$configuration = if ($Profile -eq 'Candidate') { 'Release' } else { 'Debug' }

if ($Phase -eq 'Preflight') {
    foreach ($name in 'git','cmake','ninja','python') {
        if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { throw "Missing required tool: $name" }
    }
    $os = Get-CimInstance Win32_OperatingSystem
    $drive = (Get-Item -LiteralPath $env:GITHUB_WORKSPACE).PSDrive
    Write-Host ('RAM {0:N1} GiB; workspace free disk {1:N1} GiB' -f ($os.TotalVisibleMemorySize / 1MB), ($drive.Free / 1GB))
    # Conservative heuristic; no claim that this amount will suffice for the complete build.
    if ($drive.Free -lt 45GB) { throw 'Less than 45 GiB free: aborting before download; no files deleted.' }
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $vswhere)) { throw 'vswhere is absent.' }
    $json = & $vswhere -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -format json
    if ($LASTEXITCODE -ne 0) { throw 'vswhere failed.' }
    $selected = $null
    foreach ($instance in @($json | ConvertFrom-Json)) {
        $vc = Join-Path $instance.installationPath 'VC\Tools\MSVC'
        $matches = @(Get-ChildItem -LiteralPath $vc -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "$toolset.*" })
        $dev = Join-Path $instance.installationPath 'Common7\Tools\VsDevCmd.bat'
        if ($matches.Count -gt 0 -and (Test-Path -LiteralPath $dev)) { $selected = $dev; break }
    }
    if (-not $selected) { throw 'Required VC 14.44 toolset not installed; no automatic VS installation.' }
    foreach ($tail in @("Include\$sdk\um\windows.h", "Lib\$sdk\um\x64\kernel32.lib")) {
        if (-not (Test-Path -LiteralPath (Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\$tail"))) { throw "SDK component absent: $tail" }
    }
    "CAPY_VSDEVCMD=$selected" | Out-File -LiteralPath $env:GITHUB_ENV -Append -Encoding utf8
    Write-Host "Selected VC $toolset, SDK $sdk; Ninja avoids reliance on the VS2026 solution generator. Actual compatibility requires a build."
    exit 0
}

if ($Phase -eq 'Build') {
    if (-not $env:CAPY_VSDEVCMD -or -not (Test-Path -LiteralPath $env:CAPY_VSDEVCMD)) { throw 'Toolchain preflight missing.' }
    $head = & git -C $src rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $head -ne $env:TDESKTOP_SHA) { throw 'Source SHA mismatch.' }
    $status = @(& git -C $src status --porcelain --ignore-submodules=none)
    if ($LASTEXITCODE -ne 0 -or $status.Count -ne 0) { throw 'Source checkout is not clean.' }
    $subs = @(& git -C $src submodule status --recursive)
    if ($LASTEXITCODE -ne 0 -or @($subs | Where-Object { $_ -match '^[-+U]' }).Count -ne 0) { throw 'Submodule checkout mismatch.' }
    $env:CAPY_WINDOWS_PROFILE = $Profile
    $env:CAPY_WINDOWS_CONFIGURATION = $configuration
    if ($Profile -ne 'Baseline') {
        & python (Join-Path $PSScriptRoot 'windows-notes/test_windows_notes.py') $src
        if ($LASTEXITCODE -ne 0) { throw 'Desktop notes/template source checks failed.' }
        & python (Join-Path $PSScriptRoot 'accounts/test_windows_accounts.py') $src
        if ($LASTEXITCODE -ne 0) { throw 'Desktop account source checks failed.' }
        & python (Join-Path $PSScriptRoot 'prepare_windows_online.py') $src
        if ($LASTEXITCODE -ne 0) { throw 'Windows identity preparation failed.' }
        & python (Join-Path $PSScriptRoot 'prepare_windows_online.py') $src --check
        if ($LASTEXITCODE -ne 0) { throw 'Windows identity verification failed.' }
        & python (Join-Path $PSScriptRoot 'accounts/windows_accounts_patch.py') $src
        if ($LASTEXITCODE -ne 0) { throw 'Desktop account preparation failed.' }
        & python (Join-Path $PSScriptRoot 'accounts/windows_accounts_patch.py') $src --check
        if ($LASTEXITCODE -ne 0) { throw 'Desktop account preparation verification failed.' }
        & python (Join-Path $PSScriptRoot 'windows-notes/windows_notes_patch.py') $src
        if ($LASTEXITCODE -ne 0) { throw 'Desktop notes/template preparation failed.' }
        & python (Join-Path $PSScriptRoot 'windows-notes/windows_notes_patch.py') $src --check
        if ($LASTEXITCODE -ne 0) { throw 'Desktop notes/template preparation verification failed.' }
        & python (Join-Path $PSScriptRoot 'folders/prepare_windows_folders.py') $src
        if ($LASTEXITCODE -ne 0) { throw 'Desktop folder response preparation failed.' }
        & python (Join-Path $PSScriptRoot 'folders/prepare_windows_folders.py') $src --check
        if ($LASTEXITCODE -ne 0) { throw 'Desktop folder response verification failed.' }
        & python (Join-Path $PSScriptRoot 'folders/prepare_windows_reconcile.py') $src
        if ($LASTEXITCODE -ne 0) { throw 'Desktop folder reconciliation preparation failed.' }
        & python (Join-Path $PSScriptRoot 'folders/prepare_windows_reconcile.py') $src --check
        if ($LASTEXITCODE -ne 0) { throw 'Desktop folder reconciliation verification failed.' }
        & python (Join-Path $PSScriptRoot 'windows-brand/prepare_windows_brand.py') $src
        if ($LASTEXITCODE -ne 0) { throw 'Desktop brand preparation failed.' }
        & python (Join-Path $PSScriptRoot 'windows-brand/prepare_windows_brand.py') $src --check
        if ($LASTEXITCODE -ne 0) { throw 'Desktop brand verification failed.' }
        $env:CAPY_WINDOWS_API_CACHE = Join-Path $env:RUNNER_TEMP 'capy-windows-owner-api.cmake'
        & python (Join-Path $PSScriptRoot 'api_credentials.py') --windows-cache $env:CAPY_WINDOWS_API_CACHE
        if ($LASTEXITCODE -ne 0) { throw 'Owner API cache creation failed.' }
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $root 'Libraries\win64'), (Join-Path $root 'ThirdParty') | Out-Null
    $batch = Join-Path $env:RUNNER_TEMP 'capy-windows-build.cmd'
    @'
@echo off
echo [CAPY] Initializing Visual Studio environment
call "%CAPY_VSDEVCMD%" -no_logo -arch=x64 -host_arch=x64 -winsdk=10.0.26100.0 -vcvars_ver=14.44
if errorlevel 1 (echo [CAPY] VsDevCmd failed with %errorlevel% & exit /b 101)
echo [CAPY] Platform="%Platform%"; target="%VSCMD_ARG_TGT_ARCH%"; host="%VSCMD_ARG_HOST_ARCH%"
if /i not "%VSCMD_ARG_TGT_ARCH%"=="x64" (echo [CAPY] Expected x64 target architecture & exit /b 102)
rem Current VsDevCmd can omit Platform; upstream prepare.py requires this legacy variable.
set "Platform=%VSCMD_ARG_TGT_ARCH%"
cd /d "%GITHUB_WORKSPACE%\TBuild"
if errorlevel 1 (echo [CAPY] Build directory unavailable & exit /b 103)
echo [CAPY] Preparing upstream dependencies
if /i "%CAPY_WINDOWS_PROFILE%"=="Candidate" (
    call "tdesktop\Telegram\build\prepare\win.bat" silent qt6
) else (
    call "tdesktop\Telegram\build\prepare\win.bat" skip-release silent qt6
)
if errorlevel 1 (echo [CAPY] Dependency preparation failed with %errorlevel% & exit /b 104)
cd /d "%GITHUB_WORKSPACE%\TBuild\tdesktop\Telegram"
if errorlevel 1 (echo [CAPY] Telegram directory unavailable & exit /b 105)
echo [CAPY] Configuring Ninja build
if /i not "%CAPY_WINDOWS_PROFILE%"=="Baseline" (
    call configure.bat -G "Ninja Multi-Config" qt6 -C "%CAPY_WINDOWS_API_CACHE%" -D CMAKE_CONFIGURATION_TYPES=%CAPY_WINDOWS_CONFIGURATION% -D CMAKE_MSVC_DEBUG_INFORMATION_FORMAT= -D DESKTOP_APP_DISABLE_AUTOUPDATE=ON -D DESKTOP_APP_DISABLE_CRASH_REPORTS=ON
) else (
    call configure.bat -G "Ninja Multi-Config" qt6 -D TDESKTOP_API_TEST=ON -D CMAKE_CONFIGURATION_TYPES=%CAPY_WINDOWS_CONFIGURATION% -D CMAKE_MSVC_DEBUG_INFORMATION_FORMAT= -D DESKTOP_APP_DISABLE_AUTOUPDATE=ON -D DESKTOP_APP_DISABLE_CRASH_REPORTS=ON
)
if errorlevel 1 (echo [CAPY] CMake configuration failed with %errorlevel% & exit /b 106)
exit /b 0
'@ | Set-Content -LiteralPath $batch -Encoding ascii
    & $batch
    if ($LASTEXITCODE -ne 0) { throw "Preparation batch failed with stage code $LASTEXITCODE; see the preceding CAPY message." }
    $cache = Get-Content -LiteralPath (Join-Path $src 'out\CMakeCache.txt') -Raw
    if ($cache -notmatch ('(?m)^CMAKE_CONFIGURATION_TYPES:STRING=' + $configuration + '\r?$')) {
        throw 'Configured build type differs from the requested profile.'
    }
    foreach ($key in 'DESKTOP_APP_DISABLE_AUTOUPDATE','DESKTOP_APP_DISABLE_CRASH_REPORTS') {
        if ($cache -notmatch ('(?m)^' + $key + ':BOOL=ON\r?$')) { throw "Configuration did not accept $key." }
    }
    if ($Profile -ne 'Baseline') {
        if ($cache -notmatch '(?m)^TDESKTOP_API_TEST:BOOL=OFF\r?$') { throw 'Owner build unexpectedly uses test API.' }
        foreach ($pair in @(@('TDESKTOP_API_ID', $env:CAPY_API_ID), @('TDESKTOP_API_HASH', $env:CAPY_API_HASH))) {
            if ([string]::IsNullOrEmpty($pair[1]) -or $cache -notmatch ('(?m)^' + $pair[0] + ':STRING=' + [regex]::Escape($pair[1]) + '\r?$')) {
                throw 'CMake cache did not accept owner application credentials.'
            }
        }
    } elseif ($cache -notmatch '(?m)^TDESKTOP_API_TEST:BOOL=ON\r?$') {
        throw 'Baseline configuration did not accept test API.'
    }
    @'
@echo off
call "%CAPY_VSDEVCMD%" -no_logo -arch=x64 -host_arch=x64 -winsdk=10.0.26100.0 -vcvars_ver=14.44
if errorlevel 1 exit /b 1
if /i not "%VSCMD_ARG_TGT_ARCH%"=="x64" exit /b 102
set "Platform=%VSCMD_ARG_TGT_ARCH%"
if /i not "%CAPY_WINDOWS_PROFILE%"=="Baseline" (
    cmake --build "%GITHUB_WORKSPACE%\TBuild\tdesktop\out" --target capy-auth-test --config %CAPY_WINDOWS_CONFIGURATION% --parallel 2
    if errorlevel 1 exit /b 1
    "%GITHUB_WORKSPACE%\TBuild\tdesktop\out\capy-tests\%CAPY_WINDOWS_CONFIGURATION%\capy-auth-test.exe" > "%RUNNER_TEMP%\capy-auth-runtime-result.txt"
    if errorlevel 1 exit /b 1
    type "%RUNNER_TEMP%\capy-auth-runtime-result.txt"
)
cmake --build "%GITHUB_WORKSPACE%\TBuild\tdesktop\out" --target Telegram --config %CAPY_WINDOWS_CONFIGURATION% --parallel 2
if errorlevel 1 exit /b 1
exit /b 0
'@ | Set-Content -LiteralPath $batch -Encoding ascii
    & $batch
    if ($LASTEXITCODE -ne 0) { throw 'Telegram compilation failed.' }
    exit 0
}

$exe = Join-Path $src ('out\' + $configuration + '\Telegram.exe')
if (-not (Test-Path -LiteralPath $exe)) { throw 'Expected executable is missing.' }
$bytes = [IO.File]::ReadAllBytes($exe)
if ($bytes.Length -lt 64 -or $bytes[0] -ne 0x4d -or $bytes[1] -ne 0x5a) { throw 'Invalid executable header.' }
$pe = [BitConverter]::ToInt32($bytes, 0x3c)
if ($pe -lt 0 -or $pe -gt ($bytes.Length - 6) -or [BitConverter]::ToUInt32($bytes,$pe) -ne 0x00004550 -or [BitConverter]::ToUInt16($bytes,$pe+4) -ne 0x8664) { throw 'Expected Windows PE x64 executable.' }
$stage = Join-Path $env:GITHUB_WORKSPACE 'artifact-stage'
New-Item -ItemType Directory -Force -Path $stage | Out-Null
if ($Profile -ne 'Baseline') {
    $authResult = Join-Path $env:RUNNER_TEMP 'capy-auth-runtime-result.txt'
    if (-not (Test-Path -LiteralPath $authResult) -or (Get-Content -LiteralPath $authResult -Raw) -notmatch '^CAPY_QT_AUTHORIZATION=PASS checks=[0-9]+\s*$') {
        throw 'Missing successful native authorization serialization check.'
    }
    Copy-Item -LiteralPath $authResult -Destination (Join-Path $stage 'AUTHORIZATION-TEST.txt')
}
$artifactName = if ($Profile -ne 'Baseline') { 'CapybaraGram.exe' } else { 'Telegram.exe' }
Copy-Item -LiteralPath $exe -Destination (Join-Path $stage $artifactName)
$hash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash *$artifactName" | Set-Content -LiteralPath (Join-Path $stage 'SHA256SUMS.txt') -Encoding ascii
if ($Profile -ne 'Baseline') {
    $buildLabel = if ($Profile -eq 'Candidate') { 'RELEASE CANDIDATE, not approved for final delivery.' } else { 'ONLINE PREVIEW, not a release.' }
    @"
$buildLabel Build configuration: $configuration.
Own Telegram application credentials; unsigned Windows executable.
Source: telegramdesktop/tdesktop @ $($env:TDESKTOP_SHA)
Changes: identity, accounts and windows-notes patches; profile: APPDATA/CapybaraGram Preview.
Ten local account slots without Premium; multi-account UI, login and notification isolation require runtime verification.
Native local chat/topic notes and response templates with preview/draft insertion. These features still require client runtime acceptance.
Own IPC, toast activator and shortcuts. No automatic legacy data migration or URL association changes.
Auto-update and crash reports disabled. No Updater packaged. UI launch, login and DLL requirements unverified.
Run: $($env:GITHUB_RUN_ID)
"@ | Set-Content -LiteralPath (Join-Path $stage 'BUILD-INFO.txt') -Encoding utf8
} else {
@"
TEST BASELINE ONLY, not a CapybaraGram release. Do not log into real accounts.
Source: telegramdesktop/tdesktop @ $($env:TDESKTOP_SHA)
API_TEST selects upstream restricted test credentials; it does NOT force test data centers or disable networking.
Auto-update and crash reports disabled. No Updater packaged. UI launch, networking and DLL requirements unverified.
Run: $($env:GITHUB_RUN_ID)
"@ | Set-Content -LiteralPath (Join-Path $stage 'BUILD-INFO.txt') -Encoding utf8
}
foreach ($name in 'LICENSE','LEGAL') {
    $notice = Join-Path $src $name
    if (Test-Path -LiteralPath $notice) { Copy-Item -LiteralPath $notice -Destination (Join-Path $stage $name) }
}
