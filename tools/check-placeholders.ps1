#requires -Version 5.1
<#
.SYNOPSIS
    Lists unresolved <<REPLACE: ...>> markers left from the OneFoundry template.
.DESCRIPTION
    Exit 0 when none remain, 1 when some do (use -Warn to always exit 0).
.PARAMETER Warn
    Report but always exit 0.
.PARAMETER Path
    Repository root. Default: the git root of the current directory.
#>
[CmdletBinding()]
param([switch]$Warn, [string]$Path)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
if (-not $Path) { $Path = (git rev-parse --show-toplevel 2>$null); if (-not $Path) { $Path = (Get-Location).Path } }

Push-Location $Path
try {
    $hits = @(git ls-files | Where-Object { $_ -notlike 'tools/check-placeholders*' } |
        ForEach-Object { Select-String -LiteralPath $_ -Pattern '<<REPLACE' -ErrorAction SilentlyContinue })
}
finally { Pop-Location }

if (-not $hits.Count) { 'No unresolved <<REPLACE>> markers.'; exit 0 }
"$($hits.Count) unresolved <<REPLACE>> marker(s):"
$hits | ForEach-Object { "  $($_.Path.Substring($Path.Length).TrimStart('\','/')):$($_.LineNumber): $($_.Line.Trim())" }
if ($Warn) { exit 0 }
exit 1
