# SPDX-License-Identifier: MIT
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows') { throw 'Disposable Windows CI only.' }
$out = Join-Path (Get-Location) 'ci/windows-client-results'
New-Item -ItemType Directory -Path $out -ErrorAction Stop | Out-Null
$inputRoot = Join-Path $env:RUNNER_TEMP 'windows-client-input'
$exe = Join-Path $inputRoot 'CapybaraGram.exe'
$expected = '24150fb9370a9473eef888e77ed4905df34866ffc7675d802a45f08f57e26a8a'
if ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'Unexpected native executable.' }
$profile = Join-Path $env:RUNNER_TEMP 'Capy preauth empty profile'
if (Test-Path -LiteralPath $profile) { throw 'Test profile already exists.' }
New-Item -ItemType Directory -Path $profile | Out-Null
$env:APPDATA = Join-Path $profile 'Roaming'
$env:LOCALAPPDATA = Join-Path $profile 'Local'
New-Item -ItemType Directory -Path $env:APPDATA,$env:LOCALAPPDATA | Out-Null
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type -AssemblyName System.Drawing
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
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr window, out Rect rect);
    public static IntPtr[] ForProcess(uint process) {
        var result = new List<IntPtr>();
        EnumWindows((window, unused) => { uint owner; GetWindowThreadProcessId(window, out owner); if (owner == process) result.Add(window); return true; }, IntPtr.Zero);
        return result.ToArray();
    }
    public static string Title(IntPtr window) { var text = new StringBuilder(1024); GetWindowText(window, text, text.Capacity); return text.ToString(); }
}
'@

$result = @{ source_run=34031740962; exe_sha256=$expected; login_tested=$false; phone_entered=$false; visual_review='NOT PERFORMED'; screenshots=@(); preauth='PENDING' }
$startupWatch = [Diagnostics.Stopwatch]::StartNew()
$result.uia_retry_count = 0
$app = Start-Process -FilePath $exe -WorkingDirectory $inputRoot -WindowStyle Hidden -PassThru
function Observe([string]$label) {
    $app.Refresh()
    if ($app.HasExited) { throw "Native client exited: $($app.ExitCode)" }
    $nodes = @()
    foreach ($handle in [CapyTestWindows]::ForProcess([uint32]$app.Id)) {
        try {
            $element = [System.Windows.Automation.AutomationElement]::FromHandle($handle)
            if ($element) {
                $found = $element.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
                foreach ($node in $found) {
                    if ($node -isnot [System.Windows.Automation.AutomationElement]) { throw 'Unexpected accessibility collection member.' }
                    $current = $node.Current
                    $controlType = $current.ControlType
                    if ($controlType -isnot [System.Windows.Automation.ControlType]) {
                        $result.uia_retry_count++
                        continue
                    }
                    # Snapshot properties while this provider is available. Keep the
                    # real element only for the later required Invoke/Value action.
                    $nodes += [pscustomobject]@{
                        Element = $node
                        Current = [pscustomobject]@{ Name=$current.Name; ControlType=$controlType; IsEnabled=$current.IsEnabled }
                    }
                }
            }
        } catch {
            $cause = $_.Exception
            while ($cause.InnerException) { $cause = $cause.InnerException }
            if ($cause -is [System.Runtime.InteropServices.COMException] -or $cause -is [System.Windows.Automation.ElementNotAvailableException]) {
                # Qt can replace a window/provider during startup. The outer bounded
                # observation loop retries; required controls still must be found.
                $result.uia_retry_count++
                continue
            }
            throw
        }
    }
    # Only names and control types from this exact fresh process; never session files.
    @($nodes | ForEach-Object { "$($_.Current.ControlType.ProgrammaticName): $($_.Current.Name)" }) | Set-Content -LiteralPath (Join-Path $out ($label+'.txt')) -Encoding utf8
    return $nodes
}
function Invoke-Named($nodes,[string]$name) {
    $matches = @($nodes | Where-Object { $_.Current.Name -ceq $name -and $_.Current.IsEnabled })
    if ($matches.Count -ne 1) { throw "Expected exactly one enabled control: $name" }
    $pattern = $null
    if (-not $matches[0].Element.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)) { throw "Control has no native InvokePattern: $name" }
    ([System.Windows.Automation.InvokePattern]$pattern).Invoke()
}
function Capture-OwnWindow([string]$name) {
    $null = [CapyTestWindows]::SetForegroundWindow($testWindow)
    Start-Sleep -Seconds 2
    if ([CapyTestWindows]::GetForegroundWindow() -ne $testWindow) { throw 'Own test window is not foreground for capture.' }
    $rect = [CapyTestWindows+Rect]::new()
    if (-not [CapyTestWindows]::GetWindowRect($testWindow,[ref]$rect)) { throw 'Test window bounds unavailable.' }
    $width = $rect.Right - $rect.Left
    $height = $rect.Bottom - $rect.Top
    if ($width -le 0 -or $height -le 0 -or $width -gt 3840 -or $height -gt 2160) { throw 'Unexpected test window bounds.' }
    $bitmap = [System.Drawing.Bitmap]::new($width,$height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen($rect.Left,$rect.Top,0,0,$bitmap.Size)
        $bitmap.Save((Join-Path $out $name),[System.Drawing.Imaging.ImageFormat]::Png)
        $result.screenshots += $name
        $result.visual_review = 'PENDING: captured native windows require visual review'
    } finally { $graphics.Dispose(); $bitmap.Dispose() }
}
try {
    $nodes = @()
    for ($attempt=0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Seconds 2
        $nodes = @(Observe '01-start')
        if (@($nodes | Where-Object { $_.Current.Name -ceq 'Start Messaging' }).Count -eq 1) {
            $startupWatch.Stop()
            $app.Refresh()
            $result.start_screen_observed_ms = $startupWatch.ElapsedMilliseconds
            $result.start_working_set_bytes = $app.WorkingSet64
            $result.timing_scope = 'Fresh profile on GitHub Windows runner; includes 2-second polling and accessibility observation. Not user-PC startup measurement.'
            break
        }
    }
    # The native transition hides its child controls until painting completes.
    # Display only the identified app window on this disposable CI desktop so
    # we can test actual interactive UI, rather than a permanently hidden tree.
    $shown = $false
    $testWindow = [IntPtr]::Zero
    foreach ($handle in [CapyTestWindows]::ForProcess([uint32]$app.Id)) {
        $element = [System.Windows.Automation.AutomationElement]::FromHandle($handle)
        if (-not $element) { continue }
        $startCondition = [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::NameProperty,'Start Messaging')
        if ($element.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$startCondition)) {
            $null = [CapyTestWindows]::ShowWindow($handle,9)
            $shown = [CapyTestWindows]::IsWindowVisible($handle)
            $testWindow = $handle
            break
        }
    }
    if (-not $shown) { throw 'Identified test window could not be displayed on CI desktop.' }
    Start-Sleep -Seconds 2
    $nodes = @(Observe '01-visible-start')
    if (@($nodes | Where-Object { $_.Current.Name -ceq 'Start Messaging' -and $_.Current.IsEnabled }).Count -ne 1) { throw 'Start screen not observed before capture.' }
    Capture-OwnWindow 'onboarding-screen.png'
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
    if (-not $phone[0].Element.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$value)) { throw 'Phone control has no readable native value.' }
    if (([System.Windows.Automation.ValuePattern]$value).Current.Value -ne '') { throw 'Phone input is not empty.' }
    # Capture only the observed empty phone screen, never a QR login token.
    Capture-OwnWindow 'phone-screen.png'
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
