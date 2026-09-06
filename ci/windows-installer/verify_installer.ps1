# SPDX-License-Identifier: MIT
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows') {
    throw 'This install/uninstall test runs only on the disposable Windows CI machine.'
}
$out = Join-Path $env:GITHUB_WORKSPACE 'ci\installer-results'
$setup = Join-Path $out 'CapybaraGram-Windows-x64-Setup.exe'
$build = Get-Content -LiteralPath (Join-Path $out 'BUILD-INFO.json') -Raw | ConvertFrom-Json
if ((Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant() -ne $build.setup_sha256) {
    throw 'Installer checksum differs.'
}
$runnerRoot = [IO.Path]::GetFullPath($env:RUNNER_TEMP).TrimEnd('\') + '\'
$install = [IO.Path]::GetFullPath((Join-Path $runnerRoot 'CapybaraGram install test'))
if (-not $install.StartsWith($runnerRoot, [StringComparison]::OrdinalIgnoreCase) -or (Test-Path -LiteralPath $install)) {
    throw 'Expected a new installation directory inside RUNNER_TEMP.'
}
$registry = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CapybaraGram.Desktop_is1'
$profile = Join-Path $env:APPDATA 'CapybaraGram Preview'
$shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'CapybaraGram Preview\CapybaraGram.lnk'
if ((Test-Path -LiteralPath $registry) -or (Test-Path -LiteralPath $profile) -or (Test-Path -LiteralPath $shortcut)) {
    throw 'Runner contains existing CapybaraGram data; refuse to touch it.'
}
New-Item -ItemType Directory -Path $profile | Out-Null
$profileMarker = Join-Path $profile 'installer-preservation-test.txt'
$markerContent = 'Synthetic CI data; never a user account or session.'
Set-Content -LiteralPath $profileMarker -Value $markerContent -Encoding utf8
$nestedProfile = Join-Path $profile 'tdata'
New-Item -ItemType Directory -Path $nestedProfile | Out-Null
$nestedMarker = Join-Path $nestedProfile 'capy-ci-preservation.txt'
Set-Content -LiteralPath $nestedMarker -Value $markerContent -Encoding utf8
$dataMarkers = @($profileMarker, $nestedMarker)
function Invoke-BoundedSetup([string]$Path, [string]$Arguments) {
    $process = Start-Process -FilePath $Path -ArgumentList $Arguments -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(180000)) { throw 'Installer timed out; runner cleanup will handle the process.' }
    if ($process.ExitCode -ne 0) { throw "Installer failed with exit code $($process.ExitCode)." }
}
function Assert-Payload {
    $exe = Join-Path $install 'CapybaraGram.exe'
    if ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant() -ne $build.native_sha256) {
        throw 'Installed executable differs from the verified native build.'
    }
    foreach ($name in 'LICENSE','LEGAL','SOURCE.txt','INSTALL-NOTES.txt') {
        if (-not (Test-Path -LiteralPath (Join-Path $install $name))) { throw "Installed notice missing: $name" }
    }
    $entry = Get-ItemProperty -LiteralPath $registry
    if ([IO.Path]::GetFullPath($entry.InstallLocation).TrimEnd('\') -ne $install) { throw 'Uninstall registration points elsewhere.' }
    $link = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcut)
    if ($link.TargetPath -ne $exe -or $link.WorkingDirectory -ne $install) { throw 'Start menu shortcut points elsewhere.' }
    $shell = New-Object -ComObject Shell.Application
    $item = $shell.NameSpace((Split-Path $shortcut)).ParseName((Split-Path $shortcut -Leaf))
    if ($item.ExtendedProperty('System.AppUserModel.ID') -ne 'CapybaraGram.Preview') { throw 'Shortcut notification identity differs.' }
    foreach ($marker in $dataMarkers) {
        if ((Get-Content -LiteralPath $marker -Raw).Trim() -ne $markerContent) { throw 'Application data marker changed.' }
    }
}
$options = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /LANG=russian /DIR="' + $install + '"'
Invoke-BoundedSetup $setup ($options + ' /LOG="' + (Join-Path $out 'install.log') + '"')
Assert-Payload
$extraFile = Join-Path $install 'preserve-unowned-file.txt'
Set-Content -LiteralPath $extraFile -Value $markerContent -Encoding utf8
# A different installed payload proves reinstall actually replaces bytes.
# This synthetic modified EXE is never launched; reinstall must restore its hash.
$installedExe = Join-Path $install 'CapybaraGram.exe'
$stream = [IO.File]::Open($installedExe, [IO.FileMode]::Append, [IO.FileAccess]::Write)
try { $stream.WriteByte(0) } finally { $stream.Dispose() }
if ((Get-FileHash -LiteralPath $installedExe -Algorithm SHA256).Hash.ToLowerInvariant() -eq $build.native_sha256) {
    throw 'Synthetic replacement fixture did not alter the executable.'
}
Invoke-BoundedSetup $setup ($options + ' /LOG="' + (Join-Path $out 'reinstall.log') + '"')
Assert-Payload
if ((Get-Content -LiteralPath $extraFile -Raw).Trim() -ne $markerContent) { throw 'Reinstallation removed an unowned file.' }

# Launch only the installed, checksum-verified client in the empty disposable profile.
# No phone, QR approval, messages or account sessions are supplied.
$exe = Join-Path $install 'CapybaraGram.exe'
$app = Start-Process -FilePath $exe -WorkingDirectory $install -WindowStyle Hidden -PassThru
$uiNames = @()
$uiProof = 'PENDING: native process launch only'
$uiFailure = $null
$uiaRetries = 0
try {
    Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
    # MainWindowHandle is zero for a hidden process. Inspect windows belonging
    # to the exact launched PID instead; never target another application.
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class CapyTestWindows {
    public delegate bool Visitor(IntPtr window, IntPtr data);
    [DllImport("user32.dll")] static extern bool EnumWindows(Visitor visitor, IntPtr data);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint owner);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr window, StringBuilder text, int size);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
    public static IntPtr[] ForProcess(uint process) {
        var result = new List<IntPtr>();
        EnumWindows((window, unused) => { uint owner; GetWindowThreadProcessId(window, out owner); if (owner == process) result.Add(window); return true; }, IntPtr.Zero);
        return result.ToArray();
    }
    public static string Title(IntPtr window) { var text = new StringBuilder(1024); GetWindowText(window, text, text.Capacity); return text.ToString(); }
}
'@
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Seconds 2
        $app.Refresh()
        if ($app.HasExited) { throw "Installed application exited before pre-auth check: $($app.ExitCode)." }
        foreach ($handle in [CapyTestWindows]::ForProcess([uint32]$app.Id)) {
            try {
            $element = [System.Windows.Automation.AutomationElement]::FromHandle($handle)
            if ($element) {
                $nodes = $element.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
                $uiNames = @()
                foreach ($node in $nodes) {
                    if ($node -isnot [System.Windows.Automation.AutomationElement]) { throw 'Unexpected accessibility collection member.' }
                    $name = $node.Current.Name
                    if ($name) { $uiNames += $name }
                }
                if (@($uiNames | Where-Object { $_ -match 'Start Messaging|Начать общение' }).Count -gt 0) {
                    $uiProof = 'PASS: installed native pre-auth Start Messaging control observed; no login attempted'
                    break
                }
            }
            } catch {
                $cause = $_.Exception
                while ($cause.InnerException) { $cause = $cause.InnerException }
                if ($cause -is [System.Runtime.InteropServices.COMException] -or $cause -is [System.Windows.Automation.ElementNotAvailableException]) {
                    # Providers can disappear during startup; the outer deadline
                    # remains binding and Start Messaging is still required.
                    $uiaRetries++
                    continue
                }
                throw
            }
        }
        if ($uiProof.StartsWith('PASS')) { break }
    }
    [ordered]@{ process_id = $app.Id; session_id = $app.SessionId; user_interactive = [Environment]::UserInteractive
        windows = @([CapyTestWindows]::ForProcess([uint32]$app.Id) | ForEach-Object {
            @{ handle = $_.ToInt64(); title = [CapyTestWindows]::Title($_); visible = [CapyTestWindows]::IsWindowVisible($_) }
        })
        accessibility_names = $uiNames
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $out 'preauth-diagnostics.json') -Encoding utf8
    $uiNames | Set-Content -LiteralPath (Join-Path $out 'preauth-accessibility.txt') -Encoding utf8
    if (-not $uiProof.StartsWith('PASS')) { throw 'Installed process did not expose the expected pre-auth UI within 60 seconds.' }
} catch {
    $uiFailure = $_.Exception.Message
    $uiProof = 'FAILED: ' + $uiFailure
} finally {
    $app.Refresh()
    if (-not $app.HasExited) {
        [void]$app.CloseMainWindow()
        if (-not $app.WaitForExit(15000)) {
            # Only the process handle returned for this verified executable is stopped.
            Stop-Process -Id $app.Id -Force
            [void]$app.WaitForExit(10000)
        }
    }
}

$uninstaller = [IO.Path]::GetFullPath((Join-Path $install 'unins000.exe'))
if (-not $uninstaller.StartsWith($install + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Uninstaller escaped test installation.' }
Invoke-BoundedSetup $uninstaller ('/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG="' + (Join-Path $out 'uninstall.log') + '"')
if ((Test-Path -LiteralPath $exe) -or (Test-Path -LiteralPath $registry) -or (Test-Path -LiteralPath $shortcut)) {
    throw 'Uninstall did not remove the executable, registration or Start menu shortcut.'
}
foreach ($marker in ($dataMarkers + @($extraFile))) {
    if ((Get-Content -LiteralPath $marker -Raw).Trim() -ne $markerContent) { throw 'Uninstall changed an unowned data marker.' }
}
[ordered]@{
    installation = 'PASS'; repeated_installation = 'PASS'; installed_exe_hash = 'PASS'
    user_start_menu_shortcut = 'PASS'; shortcut_notification_identity = 'PASS'; uninstall = 'PASS'
    appdata_and_unowned_file_preservation = 'PASS'; native_preauth = $uiProof
    changed_executable_replacement = 'PASS'; nested_profile_marker_preservation = 'PASS'; uia_retry_count = $uiaRetries
    account_session_preservation = 'NOT TESTED: synthetic files only; no real authorization supplied'
    native_sha256 = $build.native_sha256; setup_sha256 = $build.setup_sha256
    real_login = $false; logged_in_features = $false; visual_review = 'PENDING'
    final_release = $false; platform = 'Disposable GitHub Windows Server 2025 runner'
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $out 'verification.json') -Encoding utf8
if ($uiFailure) { throw $uiFailure }
Write-Host 'PASS: exact native payload installed, reinstalled, launched to pre-auth and uninstalled; synthetic local data preserved.'
