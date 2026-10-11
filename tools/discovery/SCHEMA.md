# Discovery report schema 2.0

Both `agent-environment-discovery.sh` and `agent-environment-discovery.ps1` emit this document. Property names are PascalCase in both. A consumer must not care which script ran.

Discovery is read-only. It never installs or modifies anything, and never records secret values (environment variables are not enumerated; URLs with credentials are redacted).

## Targets

`Go`, `Wails`, `Python`, `PowerShell`, `Bash`. `Auto` infers them from project files:

| Target | Inferred from |
|---|---|
| Go | `go.mod`, `go.work`, `*.go` |
| Wails | `wails.json` or `github.com/wailsapp/wails/v2` in `go.mod` (implies Go) |
| Python | `pyproject.toml`, `requirements.txt`, `Pipfile`, `uv.lock`, `poetry.lock`, `environment.yml`, `*.py` |
| PowerShell | `*.ps1`, `*.psm1`, `*.psd1` |
| Bash | `*.sh` |

`All` selects every target. With nothing inferable, `Auto` selects nothing and reports only host facts; it never falls back to a stack.

PowerShell on Linux is not a supported target: the bash script reports it as `N/A`.

## Top level

```
SchemaVersion        "2.0"
Metadata             GeneratedAt, ScriptName, ScriptVersion, Audience,
                     RequestedTargets[], ResolvedTargets[],
                     ReadOnlyDiscovery, ProjectWriteTestRequested, PackageInventorySkipped,
                     Policy{ MinimumPythonVersion, MinimumGoVersion, MinimumBashVersion,
                             MinimumPesterVersion, MinimumPSScriptAnalyzerVersion },
                     Notes[]
OS                   Platform, Details, MachineName, UserName, OSArchitecture,
                     IsElevated, TimeZone, CurrentDirectory, ProjectPath
Runtime              Shell, ShellVersion, EffectiveExecutionPolicy (PowerShell only)
Assessment           Checks[], Capabilities[]
Human                (Audience Human|All) Conclusion, NotReady[], EnvironmentWarnings[], RecommendedActions[]
HostDocumentation    (only with host-doc option)
Agent                (Audience Agent|All) Project, Constraints, SuggestedValidationCommands[], Limitations[]
Shell                Current, Executable, Version, ParentProcessChain[], EnvironmentHints
Python               Interpreters[], Managers{}, ActiveEnvironment{}, ProjectFiles[]
Go                   Found, Command, Version, Environment, Project{ HasGoMod, Module, HasGoWork, HasVendor }
Wails                CLI{ Found, Path, Version }, Project{ HasWailsJson, ModuleVersion },
                     Linux{ Gtk3, WebKit41, WebKit40, SuggestedBuildTag }   (bash script),
                     Windows{ WebView2 }                                     (PowerShell script),
                     Frontend{ Node, Npm }, Packaging{ Nsis, Osslsigncode }
PowerShell           (PowerShell target) Version, Edition, Modules, QualityTools{ Pester, PSScriptAnalyzer }
Bash                 (Bash target) Version, QualityTools{ shellcheck, shfmt, bats }
Tools                Commands{ name: { Found, Path, Version } }, ProxyConfigured, CIIndicators[]
Project              Path, Files[], Filesystem{ Type, Source, IsNetworkBacked, WriteAccess }, Git{ ... }
```

The `Agent`-only sections (`Shell`, `Python`, `Go`, `Wails`, `PowerShell`, `Bash`, `Tools`, `Project`) appear when Audience is `Agent` or `All`.

## Checks and capabilities

A **check** is one requirement: `Area`, `Requirement`, `Status` (`PASS` `WARN` `FAIL` `N/A` `UNKNOWN`), `Evidence`, `Remediation`.

A **capability** is what the host can do: `Name`, `Status` (`READY` `READY_WITH_WARNINGS` `INSTALLABLE` `BLOCKED` `UNKNOWN`), `Summary`, `Missing[]`.

`PASS` and `READY` mean prerequisites were detected, not that a build was run.

## Capability names (stable)

`Go applications`, `Wails desktop applications`, `Python applications`, `Bash automation`, `PowerShell automation`.

## Console output

Console output is for people and may differ between scripts. Only the JSON is a contract.
