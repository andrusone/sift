#requires -Version 5.1
<#
.SYNOPSIS
    Configures what a GitHub template cannot copy: labels, repository settings,
    the Projects v2 board, branch protection and the sprint log issue.

.DESCRIPTION
    PowerShell twin of bootstrap.sh; reads the same ./config/*.tsv files.
    Safe by default: without -Apply it only READS from GitHub and prints the plan.
    Idempotent. Never deletes anything, and only touches a project whose title
    exactly matches -ProjectTitle.
    Requires gh authenticated with the repo, project and workflow scopes.

.PARAMETER Repo
    OWNER/NAME. Default: the repository of the current directory.
.PARAMETER ProjectTitle
    Projects v2 board title. Default: the repository name.
.PARAMETER Branch
    Branch to protect. Default: main.
.PARAMETER RequiredChecks
    CI check names required to merge. Default: none.
.PARAMETER Only
    Steps to run: labels, settings, project, protection, sprint-log. Default: all.
.PARAMETER Apply
    Make the changes.

.EXAMPLE
    .\bootstrap.ps1
.EXAMPLE
    .\bootstrap.ps1 -Only labels,project -Apply
.EXAMPLE
    .\bootstrap.ps1 -RequiredChecks windows,ubuntu -Only protection -Apply
#>
[CmdletBinding()]
param(
    [string]$Repo,
    [string]$ProjectTitle,
    [string]$Branch = 'main',
    [string[]]$RequiredChecks = @(),
    [ValidateSet('labels', 'settings', 'project', 'protection', 'sprint-log')]
    [string[]]$Only = @('labels', 'settings', 'project', 'protection', 'sprint-log'),
    [switch]$Apply,
    [switch]$AllowTemplate
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$ConfigDir = Join-Path $PSScriptRoot 'config'

function Log { param([string]$m) Write-Host "[github-bootstrap] $m" }
function Warn { param([string]$m) Write-Host "[github-bootstrap][WARN] $m" -ForegroundColor Yellow }
function Die { param([string]$m) Write-Host "[github-bootstrap][ERROR] $m" -ForegroundColor Red; exit 1 }

# Run gh and return its output lines; throws on a non-zero exit unless -AllowFail.
function Invoke-Gh {
    param([Parameter(Mandatory, ValueFromRemainingArguments)][string[]]$GhArgs, [switch]$AllowFail)
    $out = & gh @GhArgs 2>&1
    if ($LASTEXITCODE -ne 0 -and -not $AllowFail) { throw "gh $($GhArgs -join ' ') failed: $($out -join ' ')" }
    [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = @($out | ForEach-Object { [string]$_ }) }
}

# Run a mutating gh command, or print it in plan mode.
function Invoke-Change {
    param([Parameter(Mandatory, ValueFromRemainingArguments)][string[]]$GhArgs)
    if ($Apply) { (Invoke-Gh @GhArgs).Output }
    else { Write-Host ('  [plan] gh ' + (($GhArgs | ForEach-Object { if ($_ -match '\s') { "'$_'" } else { $_ } }) -join ' ')) }
}

function Read-Tsv {
    param([Parameter(Mandatory)][string]$Path)
    Get-Content -LiteralPath $Path | Where-Object { $_ -and -not $_.StartsWith('#') } | ForEach-Object { , ($_ -split "`t", 3) }
}

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { Die 'gh (GitHub CLI) is required' }
if ((Invoke-Gh auth status -AllowFail).ExitCode -ne 0) { Die 'gh is not authenticated; run: gh auth login' }

if (-not $Repo) {
    $r = Invoke-Gh repo view --json nameWithOwner -q .nameWithOwner -AllowFail
    if ($r.ExitCode -ne 0) { Die 'could not determine the repository; pass -Repo OWNER/NAME' }
    $Repo = $r.Output[0]
}
if ($Repo -notmatch '^[^/]+/[^/]+$') { Die '-Repo must be OWNER/NAME' }
$Owner, $Name = $Repo -split '/', 2
if (-not $ProjectTitle) { $ProjectTitle = $Name }
if ($ProjectTitle -match '["\\]') { Die '-ProjectTitle must not contain quotes or backslashes' }

$isTemplate = (Invoke-Gh repo view $Repo --json isTemplate -q .isTemplate -AllowFail).Output | Select-Object -First 1
if ($isTemplate -eq 'true' -and $Apply -and -not $AllowTemplate) {
    Die "$Repo is a template repository. Run the bootstrap against a repo created FROM the template, not the template itself (override: -AllowTemplate)."
}

if ($Apply) { Log "APPLY mode: changing $Repo" } else { Log "PLAN mode (no changes): $Repo. Re-run with -Apply to make them." }
Log "project title: '$ProjectTitle'  steps: $($Only -join ',')"

function Invoke-Labels {
    Log '== labels'
    $existing = (Invoke-Gh label list --repo $Repo --limit 200 --json 'name,color,description' -q '.[] | [.name, .color, .description] | @tsv').Output
    foreach ($row in Read-Tsv (Join-Path $ConfigDir 'labels.tsv')) {
        $name, $color, $desc = $row
        $cur = $existing | Where-Object { ($_ -split "`t")[0] -eq $name } | Select-Object -First 1
        if (-not $cur) { Log "label '$name': create" }
        elseif ($cur -eq "$name`t$color`t$desc") { Log "label '$name': ok"; continue }
        else { Log "label '$name': update" }
        Invoke-Change label create $name --repo $Repo --color $color --description $desc --force
    }
}

function Invoke-Settings {
    Log '== repository settings'
    Log 'squash merge only, delete branch on merge, wiki off, issues and projects on'
    Invoke-Change repo edit $Repo --enable-squash-merge '--enable-merge-commit=false' '--enable-rebase-merge=false' --delete-branch-on-merge '--enable-wiki=false' --enable-issues --enable-projects
}

function Invoke-Project {
    Log "== project '$ProjectTitle'"
    $number = (Invoke-Gh project list --owner $Owner --limit 100 --format json -q ".projects[] | select(.title == `"$ProjectTitle`") | .number").Output | Select-Object -First 1
    if ($number) { Log "project exists: #$number" }
    else {
        Log 'project does not exist: create'
        if ($Apply) {
            $number = (Invoke-Gh project create --owner $Owner --title $ProjectTitle --format json -q .number).Output[0]
            Log "created project #$number"
        }
        else { Invoke-Change project create --owner $Owner --title $ProjectTitle }
    }
    if ($number) { Invoke-Change project link $number --owner $Owner --repo $Repo }

    $fields = @()
    if ($number) { $fields = (Invoke-Gh project field-list $number --owner $Owner --format json -q '.fields[] | [.id, .name, .type] | @tsv').Output }

    # Status options
    $want = @(); $opts = @()
    foreach ($row in Read-Tsv (Join-Path $ConfigDir 'project-status.tsv')) {
        $n, $color, $desc = $row
        $want += $n
        $opts += "{name:`"$n`",color:$color,description:`"$desc`"}"
    }
    $wantText = $want -join ','
    $statusId = $fields | Where-Object { ($_ -split "`t")[1] -eq 'Status' } | ForEach-Object { ($_ -split "`t")[0] } | Select-Object -First 1
    if (-not $statusId) { Log "Status field: set options [$wantText] (after the project exists)" }
    else {
        $cur = (Invoke-Gh project field-list $number --owner $Owner --format json -q '.fields[] | select(.name == "Status") | [.options[].name] | join(",")').Output | Select-Object -First 1
        if ($cur -eq $wantText) { Log "Status field: ok [$wantText]" }
        else {
            Log "Status field: set options [$wantText] (currently [$cur])"
            $query = 'mutation($f: ID!) { updateProjectV2Field(input: {fieldId: $f, singleSelectOptions: [' + ($opts -join ',') + ']}) { projectV2Field { ... on ProjectV2SingleSelectField { id } } } }'
            Invoke-Change api graphql -f "f=$statusId" -f "query=$query"
        }
    }

    # Custom fields
    foreach ($row in Read-Tsv (Join-Path $ConfigDir 'project-fields.tsv')) {
        $n, $ftype, $fopts = $row
        if ($fields | Where-Object { ($_ -split "`t")[1] -eq $n }) { Log "field '$n': ok"; continue }
        Log "field '$n' ($ftype): create"
        $dtype = switch ($ftype) { 'single_select' { 'SINGLE_SELECT' } 'number' { 'NUMBER' } 'text' { 'TEXT' } 'date' { 'DATE' } default { Die "unknown field type '$ftype' for '$n'" } }
        $target = if ($number) { [string]$number } else { '<new project>' }
        if ($dtype -eq 'SINGLE_SELECT') { Invoke-Change project field-create $target --owner $Owner --name $n --data-type SINGLE_SELECT --single-select-options $fopts }
        else { Invoke-Change project field-create $target --owner $Owner --name $n --data-type $dtype }
    }
}

function Invoke-Protection {
    Log "== branch protection ($Branch)"
    $checks = $null
    if ($RequiredChecks.Count) { $checks = [ordered]@{ strict = $true; contexts = @($RequiredChecks) } }
    $body = [ordered]@{
        required_status_checks = $checks
        enforce_admins = $false
        required_pull_request_reviews = [ordered]@{ required_approving_review_count = 0; dismiss_stale_reviews = $true }
        restrictions = $null
        required_linear_history = $true
        allow_force_pushes = $false
        allow_deletions = $false
        required_conversation_resolution = $true
    } | ConvertTo-Json -Depth 6
    $checkText = if ($RequiredChecks.Count) { $RequiredChecks -join ',' } else { 'none' }
    Log "require PR, linear history, no force-push or deletion, resolved conversations; required checks: $checkText"
    if ($Apply) {
        $tmp = New-TemporaryFile
        try {
            Set-Content -LiteralPath $tmp -Value $body -Encoding utf8
            $r = Invoke-Gh api -X PUT "repos/$Repo/branches/$Branch/protection" --input $tmp.FullName -AllowFail
            if ($r.ExitCode -eq 0) { Log 'branch protection set' }
            elseif ($r.Output -join ' ' -match 'Upgrade to GitHub Pro or make this repository public') {
                Warn 'branch protection is unavailable: this repo is private on a plan without it.'
                Warn 'Make the repo public (or upgrade), then re-run: .\bootstrap.ps1 -Only protection -Apply'
            }
            else { Die "branch protection failed: $($r.Output -join ' ')" }
        }
        finally { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
    }
    else {
        Log "[plan] gh api -X PUT repos/$Repo/branches/$Branch/protection (body below)"
        $body -split '\r?\n' | ForEach-Object { "    $_" }
    }
}

function Invoke-SprintLog {
    Log '== sprint log issue'
    $n = (Invoke-Gh issue list --repo $Repo --label sprint-log --state all --limit 1 --json number -q '.[0].number // empty').Output | Select-Object -First 1
    if ($n) { Log "sprint log exists: #$n"; return }
    Log 'no sprint log: create and pin'
    if ($Apply) {
        $bodyText = "One check-in comment each time the architect looks, plus metrics.`n`nSee docs/OPERATING-MODEL.md."
        $url = (Invoke-Gh issue create --repo $Repo --title 'Sprint log' --label sprint-log --body $bodyText).Output | Select-Object -Last 1
        $num = ($url -split '/')[-1]
        $id = (Invoke-Gh issue view $num --repo $Repo --json id -q .id).Output[0]
        $r = Invoke-Gh api graphql -f "query=mutation { pinIssue(input: {issueId: `"$id`"}) { issue { number } } }" -AllowFail
        if ($r.ExitCode -ne 0) { Warn "could not pin issue #$num; pin it manually" }
        Log "created sprint log: $url"
    }
    else { Invoke-Change issue create --repo $Repo --title 'Sprint log' --label sprint-log }
}

if ($Only -contains 'labels') { Invoke-Labels }
if ($Only -contains 'settings') { Invoke-Settings }
if ($Only -contains 'project') { Invoke-Project }
if ($Only -contains 'protection') { Invoke-Protection }
if ($Only -contains 'sprint-log') { Invoke-SprintLog }

if ($Apply) { Log 'Done.' } else { Log 'Plan complete. Nothing was changed.' }
