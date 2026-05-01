<#
.SYNOPSIS
  Wrapper for the nightly graphify delta refresh task.

.DESCRIPTION
  Run by Windows Task Scheduler every other day at 3am (registered by
  scripts/install_graphify_task.ps1). Pulls latest main, invokes
  `claude -p /refresh-graph` to run the refresh under the user's Claude
  Code subscription (no separate Anthropic API key), then commits +
  force-pushes-with-lease to a graphify/auto-refresh branch and opens
  (or updates) a single rolling PR.

  Prerequisites:
    - Claude Code CLI installed and logged in (`claude auth login` once).
    - Graphify venv at ~/graphify-trial-2026-04-29/venv with `graphifyy`
      installed (note the double-y package name).
    - gh CLI installed and logged in.

  Exit codes:
    0  refresh applied (commit/PR pushed)
    1  no diff since last run (clean exit)
    2  error (logged, task scheduler shows failure)

.PARAMETER RepoRoot
  Override the project root. Defaults to the parent of this script.

.PARAMETER ClaudeBin
  Path to the claude CLI. Defaults to `claude` on PATH.

.PARAMETER CodeOnly
  Skip the slash command and run the AST-only path locally via the
  graphify venv. Free, no subscription usage. Useful as a smoke test.

.PARAMETER NoCommit
  Run the refresh but skip the git push / PR step.

.PARAMETER DryRun
  Run refresh_delta in --dry-run mode. No writes, no push, no PR.

.PARAMETER AllowDirty
  Pass --allow-dirty to refresh_delta. Use only for ad-hoc testing.
#>
[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$ClaudeBin = "claude",
    [switch]$CodeOnly,
    [switch]$NoCommit,
    [switch]$DryRun,
    [switch]$AllowDirty
)

$ErrorActionPreference = "Stop"

# ---------- paths ----------
$LogDir = Join-Path $env:LOCALAPPDATA "graphify-nightly"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$Today = (Get-Date -Format "yyyy-MM-dd")
$LogPath = Join-Path $LogDir ("{0}.log" -f $Today)

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $stamp = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK")
    $line = "[$stamp] [$Level] $Message"
    $line | Tee-Object -FilePath $LogPath -Append | Out-Null
    Write-Host $line
}

# Native commands write to stderr even on success (e.g. `git pull`'s "From ..."
# line). With $ErrorActionPreference=Stop, PowerShell wraps those lines as
# ErrorRecords and aborts the script. This helper isolates stderr-merging so
# success-path stderr just gets logged, and errors are detected via exit code.
function Invoke-Native {
    param(
        [Parameter(Mandatory=$true)] [string]$Exe,
        [Parameter(ValueFromRemainingArguments=$true)] [string[]]$Args
    )
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $merged = & $Exe @Args 2>&1
        $exit = $LASTEXITCODE
        foreach ($entry in $merged) { Write-Log ("  " + $entry) }
        return [pscustomobject]@{ ExitCode = $exit; Output = ($merged | Out-String) }
    } finally {
        $ErrorActionPreference = $prevEap
    }
}

# ---------- resolve repo root ----------
if (-not $RepoRoot) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $RepoRoot = Resolve-Path (Join-Path $ScriptDir "..") | Select-Object -ExpandProperty Path
}
if (-not (Test-Path (Join-Path $RepoRoot ".git"))) {
    Write-Log "RepoRoot $RepoRoot is not a git repo" "ERROR"
    exit 2
}
Write-Log "starting refresh; repo=$RepoRoot"

Push-Location $RepoRoot
try {
    $env:GRAPHIFY_PROJECT_ROOT = $RepoRoot

    # ---------- clean tree guard ----------
    if (-not $AllowDirty) {
        $r = Invoke-Native git status --porcelain
        if ($r.ExitCode -ne 0) { Write-Log "git status failed" "ERROR"; exit 2 }
        if ($r.Output.Trim()) {
            Write-Log "working tree is dirty; aborting" "ERROR"
            exit 2
        }
    }

    # ---------- fetch + ff-only ----------
    Write-Log "git fetch origin"
    $r = Invoke-Native git fetch origin
    if ($r.ExitCode -ne 0) { Write-Log "git fetch failed" "ERROR"; exit 2 }

    $r = Invoke-Native git rev-parse --abbrev-ref HEAD
    $branch = $r.Output.Trim()
    if ($branch -eq "main") {
        Write-Log "git pull --ff-only origin main"
        $r = Invoke-Native git pull --ff-only origin main
        if ($r.ExitCode -ne 0) { Write-Log "fast-forward pull failed; investigate" "ERROR"; exit 2 }
    } else {
        Write-Log "current branch is $branch (not main); skipping fast-forward"
    }

    # ---------- run refresh ----------
    if ($DryRun -or $CodeOnly) {
        # Free path: run refresh_delta directly via the graphify venv.
        $venvPy = Join-Path $env:USERPROFILE "graphify-trial-2026-04-29\venv\Scripts\python.exe"
        if (-not (Test-Path $venvPy)) {
            Write-Log "graphify venv python not found at $venvPy" "ERROR"
            exit 2
        }
        $pyArgs = @("tools/graphify/refresh_delta.py")
        if ($DryRun)     { $pyArgs += "--dry-run" }
        elseif ($CodeOnly) { $pyArgs += "--code-only" }
        if ($NoCommit)   { $pyArgs += "--no-commit" }
        if ($AllowDirty) { $pyArgs += "--allow-dirty" }
        Write-Log ("running (free): " + $venvPy + " " + ($pyArgs -join " "))
        $r = Invoke-Native $venvPy @pyArgs
        $refreshExit = $r.ExitCode
    } else {
        # Subscription path: dispatch via /refresh-graph slash command.
        # `--dangerously-skip-permissions` is required for unattended runs so
        # the agent can Bash + Write without prompting. The slash command is
        # bounded to graphify operations under .graphify-refresh-cache and
        # docs/audits/graphify-current/, plus staging via `git add`.
        $claudeArgs = @("-p", "/refresh-graph", "--dangerously-skip-permissions")
        Write-Log ("running (subscription): " + $ClaudeBin + " " + ($claudeArgs -join " "))
        $r = Invoke-Native $ClaudeBin @claudeArgs
        $refreshExit = $r.ExitCode
    }
    Write-Log "refresh exit code: $refreshExit"

    if ($refreshExit -eq 1) {
        Write-Log "no diff since last refresh; nothing to commit"
        exit 1
    }
    if ($refreshExit -ne 0) {
        Write-Log "refresh failed" "ERROR"
        exit 2
    }
    if ($DryRun -or $NoCommit) {
        Write-Log "exit 0 (dry-run / no-commit; skipping push + PR)"
        exit 0
    }

    # ---------- commit + push ----------
    $rollingBranch = "graphify/auto-refresh"
    $stamp = (Get-Date -Format "yyyy-MM-dd")
    Write-Log "creating/updating branch $rollingBranch"

    $r = Invoke-Native git switch -C $rollingBranch
    if ($r.ExitCode -ne 0) { Write-Log "branch switch failed" "ERROR"; exit 2 }

    $r = Invoke-Native git diff --cached --name-only
    if (-not $r.Output.Trim()) {
        Write-Log "no staged changes after refresh (unexpected)" "WARN"
        exit 1
    }

    $modeLine = if ($CodeOnly) { "code-only" } else { "delta" }
    $commitMsg = @"
audit(graphify): rolling auto-refresh $stamp ($modeLine)

Auto-generated by scripts/graphify_nightly.ps1.
Skip-Docs-Check: scheduled graphify refresh
"@

    $tmp = New-TemporaryFile
    Set-Content -Path $tmp -Value $commitMsg -Encoding UTF8
    $r = Invoke-Native git commit --file=$tmp
    Remove-Item $tmp -Force
    if ($r.ExitCode -ne 0) { Write-Log "git commit failed" "ERROR"; exit 2 }

    Write-Log "git push --force-with-lease origin $rollingBranch"
    $r = Invoke-Native git push --force-with-lease -u origin $rollingBranch
    if ($r.ExitCode -ne 0) { Write-Log "git push failed" "ERROR"; exit 2 }

    # ---------- open or update PR ----------
    $r = Invoke-Native gh pr list --head $rollingBranch --state open --json "number,url" --limit 1
    $existing = @()
    if ($r.ExitCode -eq 0 -and $r.Output.Trim()) {
        try { $existing = $r.Output | ConvertFrom-Json } catch { $existing = @() }
    }
    if ($existing -and $existing.Count -gt 0) {
        Write-Log ("PR already open: " + $existing[0].url)
    } else {
        Write-Log "opening new PR"
        $prBody = @"
## Summary
Rolling graphify auto-refresh produced by scripts/graphify_nightly.ps1.

This PR is updated in place every other day. Merge when satisfied with the delta, or close to discard and let the next run rebuild.

## Test plan
- [ ] Inspect docs/audits/graphify-current/ for unexpected node/edge churn.
- [ ] Run ``python tools/graphify/query_local.py quality --graph docs/audits/graphify-current/graph.json``.
- [ ] Run ``python tools/graphify/query_local.py drift --min-confidence 0.85 --graph docs/audits/graphify-current/graph.json`` and confirm drift list is not growing.
"@
        $body = New-TemporaryFile
        Set-Content -Path $body -Value $prBody -Encoding UTF8
        $r = Invoke-Native gh pr create --title "audit(graphify): rolling auto-refresh" --body-file $body --base main --head $rollingBranch
        Remove-Item $body -Force
        if ($r.ExitCode -ne 0) { Write-Log "gh pr create failed" "ERROR"; exit 2 }
    }

    Write-Log "done"
    exit 0
}
finally {
    Pop-Location
}
