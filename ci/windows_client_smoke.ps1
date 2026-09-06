# SPDX-License-Identifier: MIT
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows') { throw 'Disposable Windows CI only.' }
$out = Join-Path (Get-Location) 'ci/windows-client-results'
New-Item -ItemType Directory -Path $out -ErrorAction Stop | Out-Null
$inputRoot = Join-Path $env:RUNNER_TEMP 'windows-client-input'
$exe = Join-Path $inputRoot 'CapybaraGram.exe'
$expected = 'f19082ad7bf0bd2e8ce24a71fff138b85228b0ec968dded44cdb96383a41ddb2'
if ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'Unexpected native executable.' }
$profile = Join-Path $env:RUNNER_TEMP 'Capy preauth empty profile'
if (Test-Path -LiteralPath $profile) { throw 'Test profile already exists.' }
New-Item -ItemType Directory -Path $profile | Out-Null
$env:APPDATA = Join-Path $profile 'Roaming'
$env:LOCALAPPDATA = Join-Path $profile 'Local'
New-Item -ItemType Directory -Path $env:APPDATA,$env:LOCALAPPDATA | Out-Null
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
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
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr window, int command);
    public static IntPtr[] ForProcess(uint process) {
        var result = new List<IntPtr>();
        EnumWindows((window, unused) => { uint owner; GetWindowThreadProcessId(window, out owner); if (owner == process) result.Add(window); return true; }, IntPtr.Zero);
        return result.ToArray();
    }
    public static string Title(IntPtr window) { var text = new StringBuilder(1024); GetWindowText(window, text, text.Capacity); return text.ToString(); }
}
'@

$result = @{ source_run=34001919263; exe_sha256=$expected; login_tested=$false; phone_entered=$false; visual_review='NOT PERFORMED: accessibility observation only'; preauth='PENDING' }
$app = Start-Process -FilePath $exe -WorkingDirectory $inputRoot -WindowStyle Hidden -PassThru
function Observe([string]$label) {
    $app.Refresh()
    if ($app.HasExited) { throw "Native client exited: $($app.ExitCode)" }
    $nodes = @()
    foreach ($handle in [CapyTestWindows]::ForProcess([uint32]$app.Id)) {
        $element = [System.Windows.Automation.AutomationElement]::FromHandle($handle)
        if ($element) { $nodes += @($element.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)) }
    }
    # Only names and control types from this exact fresh process; never session files.
    @($nodes | ForEach-Object { "$($_.Current.ControlType.ProgrammaticName): $($_.Current.Name)" }) | Set-Content -LiteralPath (Join-Path $out ($label+'.txt')) -Encoding utf8
    return $nodes
}
function Invoke-Named($nodes,[string]$name) {
    $matches = @($nodes | Where-Object { $_.Current.Name -ceq $name -and $_.Current.IsEnabled })
    if ($matches.Count -ne 1) { throw "Expected exactly one enabled control: $name" }
    $pattern = $null
    if (-not $matches[0].TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)) { throw "Control has no native InvokePattern: $name" }
    ([System.Windows.Automation.InvokePattern]$pattern).Invoke()
}
try {
    $nodes = @()
    for ($attempt=0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Seconds 2
        $nodes = @(Observe '01-start')
        if (@($nodes | Where-Object { $_.Current.Name -ceq 'Start Messaging' }).Count -eq 1) { break }
    }
    # The native transition hides its child controls until painting completes.
    # Display only the identified app window on this disposable CI desktop so
    # we can test actual interactive UI, rather than a permanently hidden tree.
    $shown = $false
    foreach ($handle in [CapyTestWindows]::ForProcess([uint32]$app.Id)) {
        $element = [System.Windows.Automation.AutomationElement]::FromHandle($handle)
        if (-not $element) { continue }
        $startCondition = [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::NameProperty,'Start Messaging')
        if ($element.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$startCondition)) {
            $null = [CapyTestWindows]::ShowWindow($handle,9)
            $shown = [CapyTestWindows]::IsWindowVisible($handle)
            break
        }
    }
    if (-not $shown) { throw 'Identified test window could not be displayed on CI desktop.' }
    Start-Sleep -Seconds 2
    $nodes = @(Observe '01-visible-start')
    Invoke-Named $nodes 'Start Messaging'
    Start-Sleep -Seconds 5
    $nodes = @(Observe '02-after-start')
    if (@($nodes | Where-Object { $_.Current.Name -ceq 'Log in using phone number' }).Count -eq 1) {
        Invoke-Named $nodes 'Log in using phone number'
        Start-Sleep -Seconds 3
        $nodes = @(Observe '03-phone')
    }
    $phone = @($nodes | Where-Object { $_.Current.Name -ceq 'Phone number' -and $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit })
    if ($phone.Count -ne 1) { throw 'Native phone input was not observed.' }
    $value = $null
    if (-not $phone[0].TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$value)) { throw 'Phone control has no readable native value.' }
    if (([System.Windows.Automation.ValuePattern]$value).Current.Value -ne '') { throw 'Phone input is not empty.' }
    $result.preauth = 'PASS: native Start Messaging and phone navigation invoked; empty accessible phone input observed'
    Write-Output 'CAPY_WINDOWS_PREAUTH_NAVIGATION=PASS'
} finally {
    $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $out 'verification.json') -Encoding utf8
    $app.Refresh()
    if (-not $app.HasExited) {
        $null = $app.CloseMainWindow()
        if (-not $app.WaitForExit(5000)) { $app.Kill(); $app.WaitForExit() }
    }
}
