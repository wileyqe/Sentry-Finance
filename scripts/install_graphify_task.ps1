<#
.SYNOPSIS
  Register the "Graphify Nightly" Windows scheduled task.

.DESCRIPTION
  Runs scripts/graphify_nightly.ps1 every other day at 3am local with
  wake-from-sleep enabled. Idempotent — re-running unregisters and
  re-registers the task with the latest settings.

  Verify wake timer is allowed at the OS level after install:
    powercfg /waketimers
  If the task does not appear, enable RTC wake:
    powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
    powercfg /SETACTIVE SCHEME_CURRENT

  Tear down with:
    Unregister-ScheduledTask -TaskName "Graphify Nightly" -Confirm:$false
#>
[CmdletBinding()]
param(
    [string]$TaskName = "Graphify Nightly",
    [string]$StartTime = "03:00",
    [int]$DaysInterval = 2,
    [string]$WrapperPath
)

$ErrorActionPreference = "Stop"

if (-not $WrapperPath) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $WrapperPath = Join-Path $ScriptDir "graphify_nightly.ps1"
}
if (-not (Test-Path $WrapperPath)) {
    throw "Wrapper not found at $WrapperPath"
}
$WrapperPath = (Resolve-Path $WrapperPath).Path

# pwsh.exe is preferred (PowerShell 7+); fall back to powershell.exe.
$Pwsh = (Get-Command pwsh.exe -ErrorAction SilentlyContinue)
if (-not $Pwsh) { $Pwsh = (Get-Command powershell.exe) }
$PwshPath = $Pwsh.Source

$Arg = "-NoProfile -ExecutionPolicy Bypass -File `"$WrapperPath`""

$Action = New-ScheduledTaskAction -Execute $PwshPath -Argument $Arg

$Trigger = New-ScheduledTaskTrigger -Daily -At $StartTime -DaysInterval $DaysInterval

# Wake-from-sleep, run when missed, laptop-friendly, 1h kill-switch.
$Settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 30)

$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

# Idempotent: drop any prior version of the task before re-registering.
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task '$TaskName'"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName `
    -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal `
    -Description "Graphify nightly delta refresh. See scripts/graphify_nightly.ps1." | Out-Null

Write-Host "Registered task '$TaskName':"
Get-ScheduledTask -TaskName $TaskName | Format-List TaskName, State, Principal, Settings
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Confirm Claude Code is logged in (uses your subscription, not an API key):"
Write-Host "       claude auth status"
Write-Host "     If not logged in:  claude auth login"
Write-Host "  2. Confirm gh is logged in:  gh auth status"
Write-Host "  3. Verify wake timer registered:  powercfg /waketimers"
Write-Host "  4. Smoke test:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "     Logs: %LOCALAPPDATA%\graphify-nightly\<YYYY-MM-DD>.log"
