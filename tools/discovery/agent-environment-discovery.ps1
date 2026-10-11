#requires -Version 5.1
<#
.SYNOPSIS
    Read-only Windows development-environment fingerprint for humans and AI agents.

.DESCRIPTION
    Emits the JSON schema documented in SCHEMA.md (shared with the bash twin).
    Nothing is installed or modified, and no secret values are collected.
    PowerShell is the supported automation shell on Windows; on Linux use the
    bash script.

.PARAMETER Format
    Console (default), Json, or Both.

.PARAMETER Audience
    Human, Agent, or All (default).

.PARAMETER Targets
    Auto (default), Go, Wails, Python, PowerShell, Bash, or All. Auto infers
    targets from project files and never falls back to a stack.

.PARAMETER OutputPath
    JSON output path. With -Format Both and no path, agent-environment.json is
    written to the current directory.

.PARAMETER IncludeHostDoc
    Adds a HostDocumentation section.

.PARAMETER HostDocPath
    Writes a host-documentation Markdown draft; implies -IncludeHostDoc.

.PARAMETER ProjectPath
    Project directory to inspect. Default: current directory.

.PARAMETER SkipPackageInventory
    Skip pip package enumeration.

.PARAMETER TestProjectWriteAccess
    Opt-in create/delete write test in ProjectPath.

.EXAMPLE
    .\agent-environment-discovery.ps1

.EXAMPLE
    .\agent-environment-discovery.ps1 -Format Json -Targets Go,Wails,Python

.EXAMPLE
    .\agent-environment-discovery.ps1 -Format Both -OutputPath .\host.json
#>
[CmdletBinding()]
param(
    [ValidateSet('Console', 'Json', 'Both')]
    [string]$Format = 'Console',

    [ValidateSet('Human', 'Agent', 'All')]
    [string]$Audience = 'All',

    [ValidateSet('Auto', 'Go', 'Wails', 'Python', 'PowerShell', 'Bash', 'All')]
    [string[]]$Targets = @('Auto'),

    [string]$OutputPath,
    [string]$HostDocPath,
    [switch]$IncludeHostDoc,

    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Container })]
    [string]$ProjectPath = (Get-Location).Path,

    [version]$MinimumPythonVersion = '3.10',
    [version]$MinimumGoVersion = '1.21',
    [version]$MinimumBashVersion = '4.4',
    [version]$MinimumPesterVersion = '5.0',
    [version]$MinimumPSScriptAnalyzerVersion = '1.20',

    [switch]$SkipPackageInventory,
    [switch]$TestProjectWriteAccess
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$Audience = (Get-Culture).TextInfo.ToTitleCase($Audience.ToLowerInvariant())
$script:DiscoveryScriptName = $MyInvocation.MyCommand.Name
$script:IsWindowsHost = ($env:OS -eq 'Windows_NT')
$script:ProjectRoot = (Resolve-Path -LiteralPath $ProjectPath).Path

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
function New-Record {
    param([System.Collections.IDictionary]$Properties)
    [pscustomobject]$Properties
}

function Get-CommandInfoSafe {
    param([Parameter(Mandatory)][string]$Name)
    try {
        $cmd = Get-Command -Name $Name -ErrorAction Stop | Select-Object -First 1
        New-Record ([ordered]@{
            Found = $true; Name = $cmd.Name
            Path = if ($cmd.Path) { $cmd.Path } else { $cmd.Source }
            Type = [string]$cmd.CommandType
        })
    }
    catch {
        New-Record ([ordered]@{ Found = $false; Name = $Name; Path = $null; Type = $null })
    }
}

function Invoke-ExternalSafe {
    param([Parameter(Mandatory)][string]$Command, [string[]]$Arguments = @())
    $info = Get-CommandInfoSafe $Command
    if (-not $info.Found) {
        return New-Record ([ordered]@{ Succeeded = $false; ExitCode = $null; Output = $null; Error = 'Command not found' })
    }
    $oldPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $lines = & $info.Path @Arguments 2>&1
        $exit = $LASTEXITCODE
        New-Record ([ordered]@{
            Succeeded = ($exit -eq 0); ExitCode = $exit
            Output = (($lines | ForEach-Object { [string]$_ }) -join [Environment]::NewLine).Trim()
            Error = if ($exit -eq 0) { $null } else { "Command exited with code $exit" }
        })
    }
    catch {
        New-Record ([ordered]@{ Succeeded = $false; ExitCode = $null; Output = $null; Error = $_.Exception.Message })
    }
    finally { $ErrorActionPreference = $oldPreference }
}

function ConvertTo-VersionSafe {
    param([string]$Text)
    if ($Text -match '(\d+\.\d+(?:\.\d+){0,2})') { try { return [version]$Matches[1] } catch { return $null } }
    $null
}

function Test-VersionAtLeast {
    param([string]$Actual, [version]$Minimum)
    $parsed = ConvertTo-VersionSafe $Actual
    ($null -ne $parsed -and $parsed -ge $Minimum)
}

function New-Check {
    param(
        [Parameter(Mandatory)][string]$Area,
        [Parameter(Mandatory)][string]$Requirement,
        [Parameter(Mandatory)][ValidateSet('PASS', 'WARN', 'FAIL', 'N/A', 'UNKNOWN')][string]$Status,
        [Parameter(Mandatory)][string]$Evidence,
        [string]$Remediation
    )
    New-Record ([ordered]@{ Area = $Area; Requirement = $Requirement; Status = $Status; Evidence = $Evidence; Remediation = $Remediation })
}

function New-Capability {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][ValidateSet('READY', 'READY_WITH_WARNINGS', 'INSTALLABLE', 'BLOCKED', 'UNKNOWN')][string]$Status,
        [Parameter(Mandatory)][string]$Summary,
        [string[]]$Missing = @()
    )
    New-Record ([ordered]@{ Name = $Name; Status = $Status; Summary = $Summary; Missing = @($Missing | Where-Object { $_ }) })
}

function Format-BytesHuman {
    param([AllowNull()][Nullable[UInt64]]$Bytes)
    if ($null -eq $Bytes) { return $null }
    $value = [double]$Bytes
    foreach ($unit in @('B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB')) {
        if ($value -lt 1024 -or $unit -eq 'PiB') { return ('{0:N1} {1}' -f $value, $unit) }
        $value /= 1024
    }
}

function Get-ToolVersion {
    param([Parameter(Mandatory)][string]$Name)
    $args = switch ($Name) {
        'wails' { @('version') }
        'makensis' { @('/VERSION') }
        'java' { @('-version') }
        'javac' { @('-version') }
        default { @('--version') }
    }
    $run = Invoke-ExternalSafe $Name $args
    if ($Name -eq 'wails' -and $run.Output -match 'v\d+\.\d+\.\d+') { return $Matches[0] }
    if ($run.Output) { return ($run.Output -split '[\r\n]+' | Select-Object -First 1) }
    $null
}

# -----------------------------------------------------------------------------
# Inventories
# -----------------------------------------------------------------------------
function Get-ParentProcessChain {
    $result = @()
    try {
        $pidToFind = $PID
        for ($i = 0; $i -lt 5 -and $pidToFind; $i++) {
            $p = Get-CimInstance Win32_Process -Filter "ProcessId=$pidToFind" -ErrorAction Stop
            $result += New-Record ([ordered]@{ Id = [int]$p.ProcessId; Name = $p.Name; Command = $p.CommandLine })
            $pidToFind = [int]$p.ParentProcessId
        }
    } catch { }
    @($result)
}

function Get-OSInventory {
    $os = $null
    try { $os = Get-CimInstance Win32_OperatingSystem } catch { }
    $isAdmin = $false
    try {
        $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
        $isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch { }
    New-Record ([ordered]@{
        Platform = 'Windows'
        Details = New-Record ([ordered]@{
            Caption = if ($os) { $os.Caption } else { $null }
            Version = if ($os) { $os.Version } else { $null }
            BuildNumber = if ($os) { $os.BuildNumber } else { $null }
        })
        MachineName = [Environment]::MachineName
        UserName = [Environment]::UserName
        OSArchitecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
        IsElevated = $isAdmin
        TimeZone = [TimeZoneInfo]::Local.Id
        CurrentDirectory = (Get-Location).Path
        ProjectPath = $script:ProjectRoot
    })
}

function Get-PowerShellInventory {
    $modules = @(Get-Module -ListAvailable | Sort-Object Name, Version | ForEach-Object {
        New-Record ([ordered]@{ Name = $_.Name; Version = [string]$_.Version; Path = $_.Path })
    })
    $policies = @()
    try { $policies = @(Get-ExecutionPolicy -List | ForEach-Object { New-Record ([ordered]@{ Scope = [string]$_.Scope; Policy = [string]$_.ExecutionPolicy }) }) } catch { }
    $effective = 'Unknown'
    try { $effective = [string](Get-ExecutionPolicy -ErrorAction Stop) } catch { }
    # Not named $psEdition: variable names are case-insensitive and $PSEdition is automatic in PS 7.
    $detectedEdition = if ($PSVersionTable.ContainsKey('PSEdition')) { $PSVersionTable['PSEdition'] } else { 'Desktop' }
    New-Record ([ordered]@{
        Version = [string]$PSVersionTable.PSVersion
        Edition = $detectedEdition
        Host = New-Record ([ordered]@{ Name = $Host.Name; Version = [string]$Host.Version })
        LanguageMode = [string]$ExecutionContext.SessionState.LanguageMode
        ExecutionPolicies = @($policies)
        EffectiveExecutionPolicy = $effective
        ModuleCount = $modules.Count
        QualityTools = New-Record ([ordered]@{
            Pester = @($modules | Where-Object Name -eq 'Pester')
            PSScriptAnalyzer = @($modules | Where-Object Name -eq 'PSScriptAnalyzer')
        })
    })
}

function Get-PythonInventory {
    $found = @(); $seen = @{}
    $probe = 'import json,platform,site,sys,sysconfig; print(json.dumps({"executable":sys.executable,"version":platform.python_version(),"implementation":platform.python_implementation(),"prefix":sys.prefix,"base_prefix":sys.base_prefix,"is_venv":sys.prefix!=sys.base_prefix,"architecture":platform.architecture()[0],"platform":platform.platform(),"user_site":site.getusersitepackages(),"soabi":sysconfig.get_config_var("SOABI")}))'
    foreach ($launcher in @('python', 'python3', 'py')) {
        $cmd = Get-CommandInfoSafe $launcher
        if (-not $cmd.Found) { continue }
        $pre = if ($launcher -eq 'py') { @('-3') } else { @() }
        $run = Invoke-ExternalSafe $launcher ($pre + @('-c', $probe))
        if (-not $run.Succeeded) { continue }   # includes the Microsoft Store stub
        try {
            $data = $run.Output | ConvertFrom-Json
            $key = ([string]$data.executable).ToLowerInvariant()
            if ($seen.ContainsKey($key)) { continue }
            $seen[$key] = $true
            $pip = Invoke-ExternalSafe $launcher ($pre + @('-m', 'pip', '--version'))
            $packages = @()
            if (-not $SkipPackageInventory -and $pip.Succeeded) {
                $list = Invoke-ExternalSafe $launcher ($pre + @('-m', 'pip', 'list', '--format=json', '--disable-pip-version-check'))
                if ($list.Succeeded) { try { $packages = @($list.Output | ConvertFrom-Json | Sort-Object name) } catch { } }
            }
            $found += New-Record ([ordered]@{
                Launcher = $launcher; CommandPath = $cmd.Path; Executable = $data.executable
                Version = $data.version; Implementation = $data.implementation
                Prefix = $data.prefix; BasePrefix = $data.base_prefix; IsVirtualEnvironment = $data.is_venv
                Architecture = $data.architecture; Platform = $data.platform; UserSite = $data.user_site; SOABI = $data.soabi
                Pip = New-Record ([ordered]@{ Available = $pip.Succeeded; VersionOutput = $pip.Output; Packages = @($packages) })
            })
        } catch { }
    }
    $managers = [ordered]@{}
    foreach ($name in @('conda', 'mamba', 'micromamba', 'poetry', 'pipenv', 'uv', 'pyenv', 'virtualenv', 'pdm', 'hatch')) {
        $cmd = Get-CommandInfoSafe $name
        $managers[$name] = New-Record ([ordered]@{
            Found = $cmd.Found; Path = $cmd.Path
            Version = if ($cmd.Found) { (Invoke-ExternalSafe $name @('--version')).Output } else { $null }
        })
    }
    $markers = @('pyproject.toml', 'poetry.lock', 'uv.lock', 'Pipfile', 'requirements.txt', 'environment.yml', '.python-version')
    New-Record ([ordered]@{
        Interpreters = @($found)
        Managers = New-Record $managers
        ActiveEnvironment = New-Record ([ordered]@{
            VIRTUAL_ENV = $env:VIRTUAL_ENV; CONDA_PREFIX = $env:CONDA_PREFIX; CONDA_DEFAULT_ENV = $env:CONDA_DEFAULT_ENV
            PYENV_VERSION = $env:PYENV_VERSION; POETRY_ACTIVE = $env:POETRY_ACTIVE
        })
        ProjectFiles = @($markers | Where-Object { Test-Path -LiteralPath (Join-Path $script:ProjectRoot $_) })
    })
}

function Get-GoInventory {
    $goCmd = Get-CommandInfoSafe 'go'
    $goMod = Join-Path $script:ProjectRoot 'go.mod'
    $module = $null; $wailsVersion = $null
    if (Test-Path -LiteralPath $goMod) {
        $modText = Get-Content -LiteralPath $goMod -Raw
        if ($modText -match '(?m)^module\s+(\S+)') { $module = $Matches[1] }
        if ($modText -match '(?m)^\s*github\.com/wailsapp/wails/v2\s+(\S+)') { $wailsVersion = $Matches[1] }
    }
    $script:ProjectWailsVersion = $wailsVersion
    $project = New-Record ([ordered]@{
        HasGoMod = (Test-Path -LiteralPath $goMod); Module = $module
        HasGoWork = (Test-Path -LiteralPath (Join-Path $script:ProjectRoot 'go.work'))
        HasVendor = (Test-Path -LiteralPath (Join-Path $script:ProjectRoot 'vendor'))
    })
    if (-not $goCmd.Found) {
        return New-Record ([ordered]@{ Found = $false; Command = New-Record ([ordered]@{ Found = $false; Path = $null }); Version = $null; Environment = $null; Project = $project })
    }
    $versionRun = Invoke-ExternalSafe 'go' @('version')
    $goEnv = $null
    $envRun = Invoke-ExternalSafe 'go' @('env', '-json')
    if ($envRun.Succeeded) {
        try {
            $safe = [ordered]@{}
            foreach ($property in ($envRun.Output | ConvertFrom-Json).PSObject.Properties) {
                if ($property.Name -match '(?i)(AUTH|TOKEN|PASSWORD|SECRET|CREDENTIAL)') { $safe[$property.Name] = '<redacted>' }
                elseif ($property.Value -is [string] -and $property.Value -match '^[a-z][a-z0-9+.-]*://[^/@:]+:[^/@]+@') {
                    $safe[$property.Name] = ($property.Value -replace '(^[a-z][a-z0-9+.-]*://)[^/@]+@', '$1<redacted>@')
                }
                else { $safe[$property.Name] = $property.Value }
            }
            $goEnv = New-Record $safe
        } catch { }
    }
    New-Record ([ordered]@{
        Found = $true; Command = New-Record ([ordered]@{ Found = $true; Path = $goCmd.Path })
        Version = $versionRun.Output; Environment = $goEnv; Project = $project
    })
}

function Get-WebView2Version {
    foreach ($key in @(
            'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
            'HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
            'HKCU:\Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}')) {
        try { $v = (Get-ItemProperty -LiteralPath $key -ErrorAction Stop).pv; if ($v) { return [string]$v } } catch { }
    }
    $null
}

function Get-ToolInventory {
    $tools = [ordered]@{}
    $names = @('git', 'docker', 'podman', 'node', 'npm', 'gcc', 'clang', 'cc', 'cl', 'make', 'cmake', 'pkg-config', 'curl', 'jq', 'ssh',
        'shellcheck', 'shfmt', 'bats', 'bash', 'wails', 'makensis', 'osslsigncode', 'pwsh', 'code', 'wsl', 'winget', 'choco', 'scoop')
    foreach ($name in $names) {
        $cmd = Get-CommandInfoSafe $name
        $tools[$name] = New-Record ([ordered]@{
            Found = $cmd.Found; Path = $cmd.Path
            Version = if ($cmd.Found -and $name -notin @('cl', 'wsl')) { Get-ToolVersion $name } else { $null }
        })
    }
    New-Record ([ordered]@{
        Commands = New-Record $tools
        ProxyConfigured = [bool]($env:HTTP_PROXY -or $env:HTTPS_PROXY -or $env:ALL_PROXY)
        CIIndicators = @(@('CI', 'GITHUB_ACTIONS', 'GITLAB_CI', 'TF_BUILD', 'JENKINS_URL', 'TEAMCITY_VERSION') | Where-Object { [Environment]::GetEnvironmentVariable($_) })
    })
}

function Get-ProjectInventory {
    $root = $script:ProjectRoot
    $item = Get-Item -LiteralPath $root
    $isNetwork = $root.StartsWith('\\')
    $driveType = $null
    try {
        $psDrive = $item.PSDrive
        $logical = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$($psDrive.Name):'" -ErrorAction SilentlyContinue
        if ($logical) {
            $driveType = @{ 2 = 'Removable'; 3 = 'LocalDisk'; 4 = 'NetworkDrive'; 6 = 'RamDisk' }[[int]$logical.DriveType]
            if ([int]$logical.DriveType -eq 4) { $isNetwork = $true }
        }
        if ($psDrive.DisplayRoot -and ([string]$psDrive.DisplayRoot).StartsWith('\\')) { $isNetwork = $true }
    } catch { }

    $markers = @('AGENTS.md', 'CLAUDE.md', 'README.md', '.editorconfig', '.gitattributes', '.gitignore', 'go.mod', 'go.work', 'wails.json',
        'pyproject.toml', 'requirements.txt', 'poetry.lock', 'uv.lock', 'Pipfile', 'environment.yml', '.python-version',
        'package.json', '.node-version', '.shellcheckrc', 'Makefile', 'CMakeLists.txt', 'Dockerfile', 'docker-compose.yml', 'compose.yml')
    $files = @($markers | Where-Object { Test-Path -LiteralPath (Join-Path $root $_) })
    $source = @(Get-ChildItem -LiteralPath $root -File -ErrorAction SilentlyContinue |
        Where-Object Extension -in @('.ps1', '.psm1', '.psd1', '.py', '.go', '.sh') |
        Where-Object Name -ne $script:DiscoveryScriptName | Select-Object -ExpandProperty Name)
    $files = @($files + $source | Sort-Object -Unique)

    $writeAccess = 'UNKNOWN (not tested; use -TestProjectWriteAccess)'
    if ($TestProjectWriteAccess) {
        $testPath = Join-Path $root ('.agent-env-write-test-{0}.tmp' -f [guid]::NewGuid().ToString('N'))
        try { [IO.File]::WriteAllText($testPath, ''); $writeAccess = 'PASS' }
        catch { $writeAccess = "FAIL: $($_.Exception.Message)" }
        finally {
            if (Test-Path -LiteralPath $testPath) { Remove-Item -LiteralPath $testPath -Force -ErrorAction SilentlyContinue }
            if (Test-Path -LiteralPath $testPath) { $writeAccess = "WARN: write succeeded but cleanup failed; temporary file remains at $testPath" }
        }
    }

    $git = [ordered]@{
        IsRepository = $false; Root = $null; Branch = $null; Commit = $null; Dirty = $null; ChangedFiles = @(); Remotes = @(); Error = $null
        DetectionStatus = 'GIT_NOT_FOUND'; AccessStatus = 'UNAVAILABLE'; SafeDirectoryCommand = $null; SecurityRecommendation = $null
    }
    if ((Get-CommandInfoSafe 'git').Found) {
        $rootRun = Invoke-ExternalSafe 'git' @('-C', $root, 'rev-parse', '--show-toplevel')
        if ($rootRun.Succeeded) {
            $git.IsRepository = $true; $git.Root = $rootRun.Output; $git.DetectionStatus = 'DETECTED'; $git.AccessStatus = 'READY'
            $b = Invoke-ExternalSafe 'git' @('-C', $root, 'branch', '--show-current'); if ($b.Succeeded) { $git.Branch = $b.Output }
            $c = Invoke-ExternalSafe 'git' @('-C', $root, 'rev-parse', 'HEAD'); if ($c.Succeeded) { $git.Commit = $c.Output }
            $s = Invoke-ExternalSafe 'git' @('--no-optional-locks', '-C', $root, 'status', '--porcelain=v1')
            if ($s.Succeeded) { $git.ChangedFiles = @($s.Output -split '[\r\n]+' | Where-Object { $_ }); $git.Dirty = ($git.ChangedFiles.Count -gt 0) }
            $r = Invoke-ExternalSafe 'git' @('-C', $root, 'remote', '-v')
            if ($r.Succeeded) { $git.Remotes = @($r.Output -split '[\r\n]+' | Where-Object { $_ } | ForEach-Object { $_ -replace '(^\S+\s+[a-z][a-z0-9+.-]*://)[^/@\s]+@', '$1<redacted>@' }) }
        }
        else {
            $git.Error = if ($rootRun.Output) { $rootRun.Output } else { 'The project path is not inside a Git work tree.' }
            $git.DetectionStatus = 'NOT_DETECTED'; $git.AccessStatus = 'NOT_APPLICABLE'
            if ($git.Error -match 'detected dubious ownership in repository at\s+[''"]([^''"\r\n]+)[''"]') {
                $git.IsRepository = $true; $git.Root = $Matches[1]
                $git.DetectionStatus = 'DETECTED_UNTRUSTED'; $git.AccessStatus = 'BLOCKED_SAFE_DIRECTORY'
                $git.SafeDirectoryCommand = "git config --global --add safe.directory '$($git.Root -replace "'", "''")'"
                $git.SecurityRecommendation = 'Only add this safe.directory exception if you trust the repository and its network location.'
            }
        }
    }
    New-Record ([ordered]@{
        Path = $root; Files = @($files)
        Filesystem = New-Record ([ordered]@{ Type = $driveType; Source = $item.PSDrive.Name; IsNetworkBacked = $isNetwork; WriteAccess = $writeAccess })
        Git = New-Record $git
    })
}

function Get-HostDocumentationInventory {
    $unknown = '<not discoverable automatically>'
    $computer = $null; $os = $null
    try { $computer = Get-CimInstance Win32_ComputerSystem } catch { }
    try { $os = Get-CimInstance Win32_OperatingSystem } catch { }
    $disks = @((Get-CimInstance Win32_DiskDrive -ErrorAction SilentlyContinue) | Sort-Object Index | ForEach-Object {
        New-Record ([ordered]@{ Index = $_.Index; Model = $_.Model; Size = Format-BytesHuman ([UInt64]$_.Size); Interface = $_.InterfaceType })
    })
    $nics = @()
    try {
        $nics = @(Get-NetAdapter -Physical -ErrorAction Stop | ForEach-Object {
            New-Record ([ordered]@{ Name = $_.Name; Description = $_.InterfaceDescription; Status = [string]$_.Status; LinkSpeed = [string]$_.LinkSpeed })
        })
    } catch { }
    $ips = @()
    try { $ips = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop | Where-Object { $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '127.0.0.1' } | ForEach-Object IPAddress) } catch { }
    $services = @()
    foreach ($svcName in @('sshd', 'LanmanServer', 'vmms', 'W3SVC', 'docker')) {
        $svc = Get-Service -Name $svcName -ErrorAction SilentlyContinue
        if ($svc) { $services += "${svcName}: $($svc.Status)" }
    }
    New-Record ([ordered]@{
        HostName = [Environment]::MachineName
        Summary = New-Record ([ordered]@{ Role = if ($os -and [int]$os.ProductType -eq 1) { 'Workstation' } else { 'Server' }; Site = $unknown; Status = $unknown; Contacts = $unknown })
        Hardware = New-Record ([ordered]@{
            System = if ($computer) { "$($computer.Manufacturer) $($computer.Model)".Trim() } else { $unknown }
            CPU = @((Get-CimInstance Win32_Processor -ErrorAction SilentlyContinue) | ForEach-Object { "$($_.Name.Trim()) ($($_.NumberOfCores) cores / $($_.NumberOfLogicalProcessors) threads)" })
            RAMTotal = if ($computer -and $computer.TotalPhysicalMemory) { Format-BytesHuman ([UInt64]$computer.TotalPhysicalMemory) } else { $unknown }
            Video = @((Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue) | ForEach-Object Name | Where-Object { $_ } | Sort-Object -Unique)
            Disks = @($disks); NICs = @($nics)
        })
        OS = New-Record ([ordered]@{
            DistroVersion = if ($os) { "$($os.Caption) $($os.Version) (build $($os.BuildNumber))" } else { 'Windows' }
            Kernel = if ($os) { "Windows NT $($os.Version)" } else { $unknown }
        })
        Network = New-Record ([ordered]@{ HostIPs = @($ips | Sort-Object -Unique); DNSNames = @([Environment]::MachineName) })
        Services = @($services)
        Backups = New-Record ([ordered]@{ What = $unknown; Where = $unknown; Schedule = $unknown; HealthChecks = $unknown })
        BuildRestore = @($unknown)
        HistoricalNotes = New-Record ([ordered]@{ PurchaseDates = $unknown; Why = $unknown; PreviousOwnersOrUses = $unknown; ChangeHistory = $unknown })
    })
}

function ConvertTo-HostDocumentationMarkdown {
    param([Parameter(Mandatory)]$HostDoc)
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("# $($HostDoc.HostName)"); $lines.Add('')
    $lines.Add('## Summary'); $lines.Add("- Role: $($HostDoc.Summary.Role)"); $lines.Add("- Site: $($HostDoc.Summary.Site)"); $lines.Add('')
    $lines.Add('## Hardware')
    $lines.Add("- System: $($HostDoc.Hardware.System)")
    $lines.Add("- CPU: $(@($HostDoc.Hardware.CPU) -join '; ')")
    $lines.Add("- RAM: $($HostDoc.Hardware.RAMTotal)")
    $lines.Add("- Video: $(@($HostDoc.Hardware.Video) -join '; ')")
    foreach ($d in @($HostDoc.Hardware.Disks)) { $lines.Add("- Disk $($d.Index): $($d.Model) | $($d.Size) | $($d.Interface)") }
    $lines.Add('')
    $lines.Add('## OS'); $lines.Add("- Version: $($HostDoc.OS.DistroVersion)"); $lines.Add("- Kernel: $($HostDoc.OS.Kernel)"); $lines.Add('')
    $lines.Add('## Network'); $lines.Add("- Host IP(s): $(@($HostDoc.Network.HostIPs) -join '; ')"); $lines.Add('')
    $lines.Add('## Services')
    foreach ($svc in @($HostDoc.Services)) { $lines.Add("- $svc") }
    $lines.Add('')
    $lines.Add('## Change Log'); $lines.Add("- $([DateTime]::Now.ToString('yyyy-MM-dd')) - Discovery draft generated by $script:DiscoveryScriptName")
    $lines -join [Environment]::NewLine
}

# -----------------------------------------------------------------------------
# Targets and assessment
# -----------------------------------------------------------------------------
function Resolve-DevelopmentTargets {
    $requested = @($Targets | ForEach-Object { $_.ToLowerInvariant() } | Sort-Object -Unique)
    if ($requested -contains 'all') { return @('Go', 'Wails', 'Python', 'PowerShell', 'Bash') }
    $resolved = @()
    foreach ($t in $requested) {
        switch ($t) {
            'go' { $resolved += 'Go' }
            'wails' { $resolved += @('Go', 'Wails') }
            'python' { $resolved += 'Python' }
            'powershell' { $resolved += 'PowerShell' }
            'bash' { $resolved += 'Bash' }
            'auto' {
                $names = @($script:ProjectInfo.Files)
                if ($names | Where-Object { $_ -match '\.go$' -or $_ -in @('go.mod', 'go.work') }) { $resolved += 'Go' }
                if (($names -contains 'wails.json') -or $script:ProjectWailsVersion) { $resolved += @('Go', 'Wails') }
                if ($names | Where-Object { $_ -match '\.py$' -or $_ -in @('pyproject.toml', 'requirements.txt', 'poetry.lock', 'uv.lock', 'Pipfile', 'environment.yml') }) { $resolved += 'Python' }
                if ($names | Where-Object { $_ -match '\.(ps1|psm1|psd1)$' }) { $resolved += 'PowerShell' }
                if ($names | Where-Object { $_ -match '\.sh$' }) { $resolved += 'Bash' }
            }
        }
    }
    @($resolved | Sort-Object -Unique)
}

function Test-DevelopmentTarget { param([Parameter(Mandatory)][string]$Name) $script:ResolvedTargets -contains $Name }

function Build-Assessments {
    $checks = @(); $caps = @()
    $cmds = $script:ToolInfo.Commands
    $toolOk = { param($n) [bool]$cmds.PSObject.Properties[$n].Value.Found }

    $python = @($script:PythonInfo.Interpreters | Select-Object -First 1)
    $pythonOK = ($python.Count -gt 0 -and (Test-VersionAtLeast $python[0].Version $MinimumPythonVersion))
    $goOK = ($script:GoInfo.Found -and (Test-VersionAtLeast $script:GoInfo.Version $MinimumGoVersion))

    if (Test-DevelopmentTarget 'Go') {
        $checks += New-Check 'Go' "Go >= $MinimumGoVersion" $(if ($goOK) { 'PASS' } else { 'FAIL' }) $(if ($script:GoInfo.Found) { $script:GoInfo.Version } else { 'Go not found' }) "Install Go $MinimumGoVersion or newer"
        $caps += New-Capability 'Go applications' $(if ($goOK) { 'READY' } else { 'INSTALLABLE' }) $(if ($goOK) { 'Go toolchain meets policy.' } else { 'Install the Go toolchain to enable this stack.' }) @($(if (-not $goOK) { "Go >= $MinimumGoVersion" }))
    }

    if (Test-DevelopmentTarget 'Wails') {
        $missing = @()
        if (-not $goOK) { $missing += "Go >= $MinimumGoVersion" }
        if (& $toolOk 'wails') { $checks += New-Check 'Wails' 'Wails CLI' 'PASS' "$($cmds.wails.Version) at $($cmds.wails.Path)" }
        else { $checks += New-Check 'Wails' 'Wails CLI' 'FAIL' 'wails not found on PATH' 'go install github.com/wailsapp/wails/v2/cmd/wails@<pinned version>'; $missing += 'Wails CLI' }
        if ((& $toolOk 'node') -and (& $toolOk 'npm')) { $checks += New-Check 'Wails' 'Node and npm (frontend)' 'PASS' "node $($cmds.node.Version), npm $($cmds.npm.Version)" }
        else { $checks += New-Check 'Wails' 'Node and npm (frontend)' 'FAIL' 'node or npm not found' 'Install a Node LTS release'; $missing += 'Node/npm' }
        $wv2 = Get-WebView2Version
        $script:WebView2 = $wv2
        if ($wv2) { $checks += New-Check 'Wails' 'WebView2 runtime' 'PASS' "WebView2 $wv2" }
        else { $checks += New-Check 'Wails' 'WebView2 runtime' 'FAIL' 'WebView2 runtime not found' 'winget install Microsoft.EdgeWebView2Runtime'; $missing += 'WebView2 runtime' }
        $compiler = @('gcc', 'clang', 'cc', 'cl') | Where-Object { & $toolOk $_ } | Select-Object -First 1
        if ($compiler) { $checks += New-Check 'Wails' 'C compiler (cgo, if used)' 'PASS' $compiler }
        else { $checks += New-Check 'Wails' 'C compiler (cgo, if used)' 'WARN' 'No gcc, clang or cl found; Wails itself does not need one on Windows' 'Install MSYS2 MinGW64 only if your Go dependencies use cgo' }
        if (& $toolOk 'makensis') { $checks += New-Check 'Wails' 'NSIS (installers)' 'PASS' $cmds.makensis.Version }
        else { $checks += New-Check 'Wails' 'NSIS (installers)' 'WARN' 'makensis not found' 'winget install NSIS.NSIS to build installers' }
        $caps += New-Capability 'Wails desktop applications' $(if ($missing.Count) { 'INSTALLABLE' } else { 'READY' }) $(if ($missing.Count) { 'Install the missing Wails prerequisites.' } else { 'Wails prerequisites detected on Windows.' }) $missing
    }

    if (Test-DevelopmentTarget 'Python') {
        $checks += New-Check 'Python' "Python >= $MinimumPythonVersion" $(if ($pythonOK) { 'PASS' } else { 'FAIL' }) $(if ($python.Count) { "Python $($python[0].Version) at $($python[0].Executable)" } else { 'No usable Python interpreter found' }) "Install Python $MinimumPythonVersion or newer"
        if ($pythonOK) {
            $checks += New-Check 'Python' 'pip available' $(if ($python[0].Pip.Available) { 'PASS' } else { 'WARN' }) $(if ($python[0].Pip.Available) { $python[0].Pip.VersionOutput } else { 'pip not detected' }) 'Bootstrap pip for the selected interpreter'
            $mgr = @($script:PythonInfo.Managers.PSObject.Properties | Where-Object { $_.Value.Found } | ForEach-Object Name)
            $checks += New-Check 'Python' 'Environment/project manager' $(if ($mgr.Count) { 'PASS' } else { 'WARN' }) $(if ($mgr.Count) { $mgr -join ', ' } else { 'None found; stdlib venv remains available' }) 'Install uv, Poetry or conda'
        }
        $caps += New-Capability 'Python applications' $(if ($pythonOK) { 'READY' } else { 'INSTALLABLE' }) $(if ($pythonOK) { "Python $($python[0].Version) is available." } else { 'Install a policy-compliant Python interpreter to enable this stack.' }) @($(if (-not $pythonOK) { "Python >= $MinimumPythonVersion" }))
    }

    if (Test-DevelopmentTarget 'PowerShell') {
        $pester = @($script:PSInfo.QualityTools.Pester | Sort-Object { [version]$_.Version } -Descending | Select-Object -First 1)
        $analyzer = @($script:PSInfo.QualityTools.PSScriptAnalyzer | Sort-Object { [version]$_.Version } -Descending | Select-Object -First 1)
        $pesterOK = ($pester.Count -gt 0 -and (Test-VersionAtLeast $pester[0].Version $MinimumPesterVersion))
        $analyzerOK = ($analyzer.Count -gt 0 -and (Test-VersionAtLeast $analyzer[0].Version $MinimumPSScriptAnalyzerVersion))
        $checks += New-Check 'PowerShell' 'PowerShell 5.1 or newer' 'PASS' "PowerShell $($script:PSInfo.Version) $($script:PSInfo.Edition)"
        $checks += New-Check 'PowerShell' "Pester >= $MinimumPesterVersion" $(if ($pesterOK) { 'PASS' } else { 'WARN' }) $(if ($pester.Count) { "Installed: $($pester[0].Version)" } else { 'Not installed' }) "Install-Module Pester -MinimumVersion $MinimumPesterVersion -Scope CurrentUser"
        $checks += New-Check 'PowerShell' "PSScriptAnalyzer >= $MinimumPSScriptAnalyzerVersion" $(if ($analyzerOK) { 'PASS' } else { 'WARN' }) $(if ($analyzer.Count) { "Installed: $($analyzer[0].Version)" } else { 'Not installed' }) "Install-Module PSScriptAnalyzer -MinimumVersion $MinimumPSScriptAnalyzerVersion -Scope CurrentUser"
        $gaps = @(); if (-not $pesterOK) { $gaps += 'Pester' }; if (-not $analyzerOK) { $gaps += 'PSScriptAnalyzer' }
        $caps += New-Capability 'PowerShell automation' $(if ($gaps.Count) { 'READY_WITH_WARNINGS' } else { 'READY' }) $(if ($gaps.Count) { 'PowerShell is ready; quality tools are missing.' } else { 'PowerShell and quality tools detected.' }) $gaps
    }

    if (Test-DevelopmentTarget 'Bash') {
        $bash = Get-CommandInfoSafe 'bash'
        $wsl = $cmds.wsl.Found
        if ($bash.Found) { $checks += New-Check 'Bash' "Bash >= $MinimumBashVersion" $(if (Test-VersionAtLeast $cmds.bash.Version $MinimumBashVersion) { 'PASS' } else { 'WARN' }) "$($cmds.bash.Version) at $($bash.Path)" "Install Bash $MinimumBashVersion or newer (Git for Windows ships a current one)" }
        else { $checks += New-Check 'Bash' "Bash >= $MinimumBashVersion" 'WARN' 'No bash on PATH' 'Install Git for Windows (Git Bash) or WSL' }
        $checks += New-Check 'Bash' 'WSL' 'N/A' $(if ($wsl) { 'wsl present' } else { 'wsl not found' }) ''
        $caps += New-Capability 'Bash automation' $(if ($bash.Found) { 'READY_WITH_WARNINGS' } else { 'INSTALLABLE' }) $(if ($bash.Found) { 'Bash is present; run the bash discovery script inside it to assess quality tools.' } else { 'Install Git Bash or WSL to enable Bash on this host.' }) @($(if (-not $bash.Found) { 'Bash' }))
    }
    New-Record ([ordered]@{ Checks = @($checks); Capabilities = @($caps) })
}

function Get-HumanView {
    param([Parameter(Mandatory)]$Assessment)
    $ready = @($Assessment.Capabilities | Where-Object { $_.Status -in @('READY', 'READY_WITH_WARNINGS') })
    $notReady = @($Assessment.Capabilities | Where-Object { $_.Status -notin @('READY', 'READY_WITH_WARNINGS') })
    $actions = @($Assessment.Checks | Where-Object { $_.Status -in @('FAIL', 'WARN') -and $_.Remediation })
    $warnings = @()
    $process = @($script:PSInfo.ExecutionPolicies | Where-Object Scope -eq 'Process' | Select-Object -First 1)
    if ($process.Count -and $process[0].Policy -eq 'Bypass') { $warnings += 'Process execution policy is Bypass; that exception ends when this process closes.' }
    if ($script:ProjectInfo.Filesystem.IsNetworkBacked) { $warnings += 'The project is on a network-backed filesystem; builds, watchers, locks and symlinks may behave differently.' }
    if ($script:ProjectInfo.Git.DetectionStatus -eq 'DETECTED_UNTRUSTED') { $warnings += 'Git detected the repository but refuses to operate because of ownership (safe.directory).' }
    $conclusion = if ($Assessment.Capabilities.Count -eq 0) { 'No stack targets were selected or inferred; only host facts were collected. Use -Targets to assess a stack.' }
    else { "$($ready.Count) selected capabilities are ready or ready with warnings; $($notReady.Count) require installation or are blocked." }
    New-Record ([ordered]@{
        Conclusion = $conclusion
        NotReady = @($notReady | ForEach-Object { New-Record ([ordered]@{ Name = $_.Name; Status = $_.Status; Missing = @($_.Missing) }) })
        EnvironmentWarnings = @($warnings)
        RecommendedActions = @($actions | ForEach-Object { New-Record ([ordered]@{ Status = $_.Status; Area = $_.Area; Requirement = $_.Requirement; Remediation = $_.Remediation }) })
    })
}

function Get-AgentView {
    $validation = @()
    if (Test-DevelopmentTarget 'Go') { $validation += @('go test ./...', 'go vet ./...') }
    if (Test-DevelopmentTarget 'Wails') { $validation += 'wails doctor' }
    if (Test-DevelopmentTarget 'Python') { $validation += 'python -m pip check' }
    if (Test-DevelopmentTarget 'PowerShell') { $validation += @('Invoke-Pester', 'Invoke-ScriptAnalyzer -Path <path> -Recurse') }
    if (Test-DevelopmentTarget 'Bash') { $validation += @('shellcheck <file>', 'shfmt -d <file>') }
    $validation += 'git status --short'
    New-Record ([ordered]@{
        Project = $script:ProjectInfo
        Constraints = New-Record ([ordered]@{
            ProjectIsNetworkBacked = $script:ProjectInfo.Filesystem.IsNetworkBacked
            ProjectWriteAccess = $script:ProjectInfo.Filesystem.WriteAccess
            IsElevated = $script:OSInfo.IsElevated
            IsWSL = $false
            Shell = 'PowerShell'
            EffectiveExecutionPolicy = $script:PSInfo.EffectiveExecutionPolicy
            LanguageMode = $script:PSInfo.LanguageMode
        })
        SuggestedValidationCommands = @($validation)
        Limitations = @(
            'Discovery does not intentionally modify projects and does not prove project-directory write access.',
            'Tool presence does not prove that a clean build or package restore succeeds.',
            'Commands installed outside PATH may not be detected.',
            'No secret environment-variable values are collected.'
        )
    })
}

function Write-ConsoleReport {
    param([Parameter(Mandatory)]$Report)
    Write-Host 'Development Environment Fingerprint'
    Write-Host "Generated: $($Report.Metadata.GeneratedAt)"
    Write-Host "Host: $($Report.OS.MachineName) | OS: $($Report.OS.Platform) ($($Report.OS.Details.Caption)) | Architecture: $($Report.OS.OSArchitecture)"
    Write-Host "Shell: PowerShell $($Report.Runtime.ShellVersion)"
    Write-Host "Project: $($Report.OS.ProjectPath)"
    Write-Host "Audience: $($Report.Metadata.Audience)"
    Write-Host "Targets: $($Report.Metadata.ResolvedTargets -join ', ')"
    if ($Report.PSObject.Properties['Human']) {
        Write-Host "`nHUMAN SUMMARY"; Write-Host $Report.Human.Conclusion
        if ($Report.Assessment.Capabilities.Count) {
            Write-Host "`nCAPABILITY SUMMARY"
            $Report.Assessment.Capabilities | Select-Object Status, Name, Summary | Format-Table -AutoSize -Wrap | Out-Host
        }
        if ($Report.Human.EnvironmentWarnings.Count) { Write-Host 'ENVIRONMENT WARNINGS'; $Report.Human.EnvironmentWarnings | ForEach-Object { Write-Host "  - $_" } }
        if ($Report.Human.RecommendedActions.Count) {
            Write-Host "`nRECOMMENDED NEXT ACTIONS"
            $Report.Human.RecommendedActions | Select-Object Status, Area, Requirement, Remediation | Format-Table -AutoSize -Wrap | Out-Host
        }
    }
    if ($Report.PSObject.Properties['Agent']) {
        $g = $Report.Agent.Project.Git
        Write-Host "`nAGENT HANDOFF SUMMARY"
        Write-Host "  Repository: $(if ($g.Root) { $g.Root } else { 'not detected' })"
        Write-Host "  Branch: $(if ($g.Branch) { $g.Branch } else { 'n/a' })"
        Write-Host "  Working tree dirty: $(if ($null -ne $g.Dirty) { $g.Dirty } else { 'unknown' })"
        Write-Host "  Network-backed project: $($Report.Agent.Constraints.ProjectIsNetworkBacked)"
        Write-Host "  Project write access: $($Report.Agent.Constraints.ProjectWriteAccess)"
        Write-Host "  Elevated: $($Report.Agent.Constraints.IsElevated)"
        if ($Format -eq 'Console') { Write-Host '  Use -Format Both to save the complete agent handoff as JSON.' }
    }
}

# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------
if ($HostDocPath) { $IncludeHostDoc = $true }

$script:ProjectWailsVersion = $null
$script:OSInfo = Get-OSInventory
$script:PSInfo = Get-PowerShellInventory
$script:PythonInfo = Get-PythonInventory
$script:GoInfo = Get-GoInventory
$script:ToolInfo = Get-ToolInventory
$script:ProjectInfo = Get-ProjectInventory
$script:ResolvedTargets = @(Resolve-DevelopmentTargets)
$script:WebView2 = $null
$assessment = Build-Assessments
if (-not $script:WebView2) { $script:WebView2 = Get-WebView2Version }
$hostDoc = if ($IncludeHostDoc) { Get-HostDocumentationInventory } else { $null }

$cmds = $script:ToolInfo.Commands
$p = [ordered]@{
    SchemaVersion = '2.0'
    Metadata = New-Record ([ordered]@{
        GeneratedAt = [DateTimeOffset]::Now.ToString('o')
        ScriptName = $script:DiscoveryScriptName
        ScriptVersion = '2.0.0'
        Audience = $Audience
        RequestedTargets = @($Targets)
        ResolvedTargets = @($script:ResolvedTargets)
        ReadOnlyDiscovery = -not [bool]$TestProjectWriteAccess
        ProjectWriteTestRequested = [bool]$TestProjectWriteAccess
        PackageInventorySkipped = [bool]$SkipPackageInventory
        Policy = New-Record ([ordered]@{
            MinimumPythonVersion = [string]$MinimumPythonVersion
            MinimumGoVersion = [string]$MinimumGoVersion
            MinimumBashVersion = [string]$MinimumBashVersion
            MinimumPesterVersion = [string]$MinimumPesterVersion
            MinimumPSScriptAnalyzerVersion = [string]$MinimumPSScriptAnalyzerVersion
        })
        Notes = @(
            'PASS means prerequisites were detected, not that a sample build was compiled.',
            'WARN means usable with limitations or that runtime validation is still required.',
            'No project files are intentionally modified; first-run tool probes may initialize tool-local user caches.',
            'No secret environment-variable values are collected.'
        )
    })
    OS = $script:OSInfo
    Runtime = New-Record ([ordered]@{
        Shell = 'PowerShell'; ShellVersion = $script:PSInfo.Version
        EffectiveExecutionPolicy = $script:PSInfo.EffectiveExecutionPolicy
    })
    Assessment = $assessment
}
if ($Audience -in @('Human', 'All')) { $p['Human'] = Get-HumanView $assessment }
if ($hostDoc) { $p['HostDocumentation'] = $hostDoc }
if ($Audience -in @('Agent', 'All')) {
    $p['Agent'] = Get-AgentView
    $p['Shell'] = New-Record ([ordered]@{
        Current = 'PowerShell'
        Executable = (Get-Process -Id $PID).Path
        Version = $script:PSInfo.Version
        ParentProcessChain = @(Get-ParentProcessChain)
        EnvironmentHints = New-Record ([ordered]@{ SHELL = $env:SHELL; TERM = $env:TERM; ComSpec = $env:ComSpec; WT_SESSION_Present = [bool]$env:WT_SESSION })
    })
    $p['Python'] = $script:PythonInfo
    $p['Go'] = $script:GoInfo
    $p['Wails'] = New-Record ([ordered]@{
        CLI = New-Record ([ordered]@{ Found = $cmds.wails.Found; Path = $cmds.wails.Path; Version = $cmds.wails.Version })
        Project = New-Record ([ordered]@{ HasWailsJson = (Test-Path -LiteralPath (Join-Path $script:ProjectRoot 'wails.json')); ModuleVersion = $script:ProjectWailsVersion })
        Windows = New-Record ([ordered]@{ WebView2 = $script:WebView2 })
        Frontend = New-Record ([ordered]@{ Node = $cmds.node.Version; Npm = $cmds.npm.Version })
        Packaging = New-Record ([ordered]@{ Nsis = $cmds.makensis.Version; Osslsigncode = $cmds.osslsigncode.Version })
    })
    $p['PowerShell'] = $script:PSInfo
    $p['Bash'] = New-Record ([ordered]@{
        Version = $cmds.bash.Version
        QualityTools = New-Record ([ordered]@{ shellcheck = $cmds.shellcheck.Version; shfmt = $cmds.shfmt.Version; bats = $cmds.bats.Version })
    })
    $p['Tools'] = $script:ToolInfo
    $p['Project'] = $script:ProjectInfo
}
$report = New-Record $p

$json = $report | ConvertTo-Json -Depth 14
if ($Format -in @('Console', 'Both')) {
    Write-ConsoleReport $report
    if ($hostDoc) {
        Write-Host "`nHOST DOCUMENTATION DISCOVERY"
        Write-Host "  CPU: $(@($hostDoc.Hardware.CPU) -join '; ')"
        Write-Host "  RAM: $($hostDoc.Hardware.RAMTotal)"
        Write-Host "  IPs: $(@($hostDoc.Network.HostIPs) -join ', ')"
        Write-Host '  Historical/intent fields are intentionally left as not discoverable.'
    }
}
if ($HostDocPath) {
    ConvertTo-HostDocumentationMarkdown $hostDoc | Set-Content -LiteralPath $HostDocPath -Encoding UTF8
    if ($Format -ne 'Json') { Write-Host "`nHost documentation draft written to: $HostDocPath" }
}
if ($Format -eq 'Json') { $json }
if ($Format -eq 'Both' -and -not $OutputPath) { $OutputPath = Join-Path (Get-Location).Path 'agent-environment.json' }
if ($OutputPath) {
    $json | Set-Content -LiteralPath $OutputPath -Encoding UTF8
    if ($Format -ne 'Json') { Write-Host "`nJSON report written to: $OutputPath" }
}
