# SPDX-License-Identifier: MIT
# Adapted by Codex after review of Fable BUILD-001-WIN. Not yet build-validated.
param([Parameter(Mandatory=$true)][ValidateSet('Preflight','Build','Collect')][string]$Phase)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$sdk = '10.0.26100.0'
$toolset = '14.44'
if (-not $env:GITHUB_WORKSPACE -or -not $env:RUNNER_TEMP) { throw 'Run only on the disposable GitHub runner.' }
$root = Join-Path $env:GITHUB_WORKSPACE 'TBuild'
$src = Join-Path $root 'tdesktop'

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
call "tdesktop\Telegram\build\prepare\win.bat" skip-release silent qt6
if errorlevel 1 (echo [CAPY] Dependency preparation failed with %errorlevel% & exit /b 104)
cd /d "%GITHUB_WORKSPACE%\TBuild\tdesktop\Telegram"
if errorlevel 1 (echo [CAPY] Telegram directory unavailable & exit /b 105)
echo [CAPY] Configuring Ninja build
call configure.bat -G "Ninja Multi-Config" qt6 -D TDESKTOP_API_TEST=ON -D CMAKE_CONFIGURATION_TYPES=Debug -D CMAKE_MSVC_DEBUG_INFORMATION_FORMAT= -D DESKTOP_APP_DISABLE_AUTOUPDATE=ON -D DESKTOP_APP_DISABLE_CRASH_REPORTS=ON
if errorlevel 1 (echo [CAPY] CMake configuration failed with %errorlevel% & exit /b 106)
exit /b 0
'@ | Set-Content -LiteralPath $batch -Encoding ascii
    & $batch
    if ($LASTEXITCODE -ne 0) { throw "Preparation batch failed with stage code $LASTEXITCODE; see the preceding CAPY message." }
    $cache = Get-Content -LiteralPath (Join-Path $src 'out\CMakeCache.txt') -Raw
    foreach ($key in 'TDESKTOP_API_TEST','DESKTOP_APP_DISABLE_AUTOUPDATE','DESKTOP_APP_DISABLE_CRASH_REPORTS') {
        if ($cache -notmatch ('(?m)^' + $key + ':BOOL=ON\r?$')) { throw "Configuration did not accept $key." }
    }
    @'
@echo off
call "%CAPY_VSDEVCMD%" -no_logo -arch=x64 -host_arch=x64 -winsdk=10.0.26100.0 -vcvars_ver=14.44
if errorlevel 1 exit /b 1
if /i not "%VSCMD_ARG_TGT_ARCH%"=="x64" exit /b 102
set "Platform=%VSCMD_ARG_TGT_ARCH%"
cmake --build "%GITHUB_WORKSPACE%\TBuild\tdesktop\out" --target Telegram --config Debug --parallel 2
if errorlevel 1 exit /b 1
exit /b 0
'@ | Set-Content -LiteralPath $batch -Encoding ascii
    & $batch
    if ($LASTEXITCODE -ne 0) { throw 'Telegram compilation failed.' }
    exit 0
}

$exe = Join-Path $src 'out\Debug\Telegram.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw 'Expected executable is missing.' }
$bytes = [IO.File]::ReadAllBytes($exe)
if ($bytes.Length -lt 64 -or $bytes[0] -ne 0x4d -or $bytes[1] -ne 0x5a) { throw 'Invalid executable header.' }
$pe = [BitConverter]::ToInt32($bytes, 0x3c)
if ($pe -lt 0 -or $pe -gt ($bytes.Length - 6) -or [BitConverter]::ToUInt32($bytes,$pe) -ne 0x00004550 -or [BitConverter]::ToUInt16($bytes,$pe+4) -ne 0x8664) { throw 'Expected Windows PE x64 executable.' }
$stage = Join-Path $env:GITHUB_WORKSPACE 'artifact-stage'
New-Item -ItemType Directory -Force -Path $stage | Out-Null
Copy-Item -LiteralPath $exe -Destination (Join-Path $stage 'Telegram.exe')
$hash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash *Telegram.exe" | Set-Content -LiteralPath (Join-Path $stage 'SHA256SUMS.txt') -Encoding ascii
@"
TEST BASELINE ONLY, not a CapybaraGram release. Do not log into real accounts.
Source: telegramdesktop/tdesktop @ $($env:TDESKTOP_SHA)
API_TEST selects upstream restricted test credentials; it does NOT force test data centers or disable networking.
Auto-update and crash reports disabled. No Updater packaged. UI launch, networking and DLL requirements unverified.
Run: $($env:GITHUB_RUN_ID)
"@ | Set-Content -LiteralPath (Join-Path $stage 'BUILD-INFO.txt') -Encoding utf8
foreach ($name in 'LICENSE','LEGAL') {
    $notice = Join-Path $src $name
    if (Test-Path -LiteralPath $notice) { Copy-Item -LiteralPath $notice -Destination (Join-Path $stage $name) }
}
