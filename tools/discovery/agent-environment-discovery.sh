#!/usr/bin/env bash
# agent-environment-discovery.sh
# Read-only Linux/macOS development-environment fingerprint for humans and AI agents.
# Emits the JSON schema documented in SCHEMA.md (shared with the PowerShell twin).
# Bash 4.4+ required. No jq or Python dependency for the script itself.

set -u
set -o pipefail

SCRIPT_NAME=${0##*/}
SCRIPT_VERSION="2.0.0"
SCHEMA_VERSION="2.0"
FORMAT="Console"
AUDIENCE="All"
TARGETS_RAW="Auto"
OUTPUT_PATH=""
HOST_DOC_PATH=""
INCLUDE_HOST_DOC=0
PROJECT_PATH="$PWD"
MIN_PYTHON_VERSION="3.10"
MIN_GO_VERSION="1.21"
MIN_BASH_VERSION="4.4"
SKIP_PACKAGE_INVENTORY=0
TEST_PROJECT_WRITE_ACCESS=0

usage() {
  cat <<'EOF'
Usage: agent-environment-discovery.sh [options]

Produces a read-only development-environment fingerprint for AI agents and humans.
Nothing is installed or modified. See SCHEMA.md for the JSON schema.

Options:
  --format Console|Json|Both        Output mode (default: Console)
  --audience Human|Agent|All        Report audience (default: All)
  --targets LIST                    Comma-separated: Auto,Go,Wails,Python,PowerShell,Bash,All
                                    (default: Auto, inferred from project files)
  --output-path PATH                JSON output path
  --include-host-doc                Include host-documentation discovery
  --host-doc-path PATH              Write host-documentation Markdown; implies above
  --project-path PATH               Project directory (default: current directory)
  --minimum-python-version VERSION  Policy minimum (default: 3.10)
  --minimum-go-version VERSION      Policy minimum (default: 1.21)
  --minimum-bash-version VERSION    Policy minimum (default: 4.4)
  --skip-package-inventory          Skip pip package inventory
  --test-project-write-access       Opt-in create/delete write test in project path
  -h, --help                        Show this help

Examples:
  ./agent-environment-discovery.sh
  ./agent-environment-discovery.sh --format Both --output-path ./host.json
  ./agent-environment-discovery.sh --audience Agent --format Json
  ./agent-environment-discovery.sh --targets Go,Wails,Python
EOF
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 2
}

while (($#)); do
  case "$1" in
  --format | --audience | --targets | --output-path | --host-doc-path | --project-path | \
    --minimum-python-version | --minimum-go-version | --minimum-bash-version)
    [[ $# -ge 2 ]] || die "$1 requires a value"
    case "$1" in
    --format) FORMAT=$2 ;;
    --audience) AUDIENCE=$2 ;;
    --targets) TARGETS_RAW=$2 ;;
    --output-path) OUTPUT_PATH=$2 ;;
    --host-doc-path)
      HOST_DOC_PATH=$2
      INCLUDE_HOST_DOC=1
      ;;
    --project-path) PROJECT_PATH=$2 ;;
    --minimum-python-version) MIN_PYTHON_VERSION=$2 ;;
    --minimum-go-version) MIN_GO_VERSION=$2 ;;
    --minimum-bash-version) MIN_BASH_VERSION=$2 ;;
    esac
    shift 2
    ;;
  --include-host-doc)
    INCLUDE_HOST_DOC=1
    shift
    ;;
  --skip-package-inventory)
    SKIP_PACKAGE_INVENTORY=1
    shift
    ;;
  --test-project-write-access)
    TEST_PROJECT_WRITE_ACCESS=1
    shift
    ;;
  -h | --help)
    usage
    exit 0
    ;;
  *) die "unknown argument: $1" ;;
  esac
done

((BASH_VERSINFO[0] > 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] >= 4))) ||
  die "Bash 4.4+ is required (this is $BASH_VERSION). On macOS: brew install bash"

case "${FORMAT,,}" in console) FORMAT=Console ;; json) FORMAT=Json ;; both) FORMAT=Both ;; *) die "invalid --format: $FORMAT" ;; esac
case "${AUDIENCE,,}" in human) AUDIENCE=Human ;; agent) AUDIENCE=Agent ;; all) AUDIENCE=All ;; *) die "invalid --audience: $AUDIENCE" ;; esac
[[ -d "$PROJECT_PATH" ]] || die "project path is not a directory: $PROJECT_PATH"
PROJECT_PATH=$(cd "$PROJECT_PATH" 2>/dev/null && pwd -P) || die "cannot resolve project path"

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
json_escape() {
  local s=${1-}
  s=${s//\\/\\\\}
  s=${s//\"/\\\"}
  s=${s//$'\n'/\\n}
  s=${s//$'\r'/\\r}
  s=${s//$'\t'/\\t}
  printf '%s' "$s"
}
jstr() { printf '"%s"' "$(json_escape "${1-}")"; }
jnull_or_str() { if [[ -n "${1-}" ]]; then jstr "$1"; else printf 'null'; fi; }
jbool() { if [[ "${1:-0}" == 1 || "${1:-}" == true ]]; then printf 'true'; else printf 'false'; fi; }
json_array_strings() {
  local first=1 x
  printf '['
  for x in "$@"; do
    ((first)) || printf ','
    first=0
    jstr "$x"
  done
  printf ']'
}

command_path() { command -v "$1" 2>/dev/null || true; }
command_found() { command -v "$1" >/dev/null 2>&1; }

# First line(s) of a tool's version output. Never fails.
command_version() {
  local cmd=$1 out=""
  case "$cmd" in
  java | javac) out=$("$cmd" -version 2>&1 | head -n 2) ;;
  makensis) out=$(makensis -VERSION 2>&1 | head -n 1) ;;
  wails) out=$(wails version 2>&1 | grep -Eo 'v[0-9]+\.[0-9]+\.[0-9]+' | head -n 1) ;;
  pwsh) out=$(pwsh -NoLogo -NoProfile -Command '$PSVersionTable.PSVersion.ToString()' 2>/dev/null | head -n 1) ;;
  *) out=$("$cmd" --version 2>&1 | head -n 3) ;;
  esac
  printf '%s' "$out"
}

version_ge() {
  # Numeric dotted-version comparison; ignores suffixes.
  local a=${1//[^0-9.]/} b=${2//[^0-9.]/} i
  local -a aa bb
  IFS=. read -r -a aa <<<"$a"
  IFS=. read -r -a bb <<<"$b"
  local n=${#aa[@]}
  ((${#bb[@]} > n)) && n=${#bb[@]}
  for ((i = 0; i < n; i++)); do
    local av=${aa[i]:-0} bv=${bb[i]:-0}
    ((10#$av > 10#$bv)) && return 0
    ((10#$av < 10#$bv)) && return 1
  done
  return 0
}

trim() {
  local v=${1-}
  v="${v#"${v%%[![:space:]]*}"}"
  v="${v%"${v##*[![:space:]]}"}"
  printf '%s' "$v"
}
join_by() {
  local d=$1
  shift
  local first=1 x
  for x in "$@"; do
    ((first)) || printf '%s' "$d"
    first=0
    printf '%s' "$x"
  done
}

# -----------------------------------------------------------------------------
# OS / runtime
# -----------------------------------------------------------------------------
UNAME_S=$(uname -s 2>/dev/null || printf Unknown)
case "$UNAME_S" in
Linux) PLATFORM=Linux ;;
Darwin) PLATFORM=macOS ;;
MINGW* | MSYS* | CYGWIN*) PLATFORM=Windows ;;
*) PLATFORM="Linux/Unix" ;;
esac
MACHINE_NAME=$(hostname 2>/dev/null || uname -n 2>/dev/null || printf unknown)
USER_NAME=$(id -un 2>/dev/null || printf '%s' "${USER:-unknown}")
OS_ARCH=$(uname -m 2>/dev/null || printf unknown)
IS_ELEVATED=0
[[ $(id -u 2>/dev/null || echo 1) == 0 ]] && IS_ELEVATED=1
TIMEZONE=$(readlink /etc/localtime 2>/dev/null | sed 's#^.*/zoneinfo/##' || true)
[[ -n "$TIMEZONE" ]] || TIMEZONE=$(date +%Z 2>/dev/null || printf unknown)
KERNEL=$(uname -r 2>/dev/null || true)
UNAME_A=$(uname -a 2>/dev/null || true)
PRETTY_NAME=""
if [[ -r /etc/os-release ]]; then
  PRETTY_NAME=$(awk -F= '$1=="PRETTY_NAME" {v=$2; gsub(/^"|"$/,"",v); print v; exit}' /etc/os-release)
elif [[ "$PLATFORM" == macOS ]] && command_found sw_vers; then
  PRETTY_NAME="macOS $(sw_vers -productVersion 2>/dev/null)"
fi
[[ -n "$PRETTY_NAME" ]] || PRETTY_NAME=$PLATFORM
IS_WSL=0
[[ -r /proc/version ]] && grep -qi microsoft /proc/version 2>/dev/null && IS_WSL=1

BASH_VERSION_TEXT=${BASH_VERSION:-unknown}
CURRENT_SHELL=${SHELL:-$(ps -p $$ -o comm= 2>/dev/null | xargs || echo bash)}
PARENT_CHAIN_JSON='[]'
{
  pid=$$
  pc='['
  first=1
  for _ in 1 2 3 4 5; do
    [[ "$pid" =~ ^[0-9]+$ ]] || break
    name=$(ps -p "$pid" -o comm= 2>/dev/null | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)
    args=$(ps -p "$pid" -o args= 2>/dev/null | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)
    ppid=$(ps -p "$pid" -o ppid= 2>/dev/null | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)
    ((first)) || pc+=','
    first=0
    pc+="{\"Id\":$pid,\"Name\":$(jstr "$name"),\"Command\":$(jstr "$args")}"
    [[ -n "$ppid" && "$ppid" != 0 && "$ppid" != "$pid" ]] || break
    pid=$ppid
  done
  pc+=']'
  PARENT_CHAIN_JSON=$pc
}

# -----------------------------------------------------------------------------
# Tool inventory
# -----------------------------------------------------------------------------
TOOLS=(git docker podman node npm gcc clang cc make cmake pkg-config curl wget jq ssh rsync tar unzip
  shellcheck shfmt bats wails makensis osslsigncode pwsh code
  systemctl lspci lsblk findmnt ip)
declare -A TOOL_FOUND TOOL_PATH TOOL_VERSION
for t in "${TOOLS[@]}"; do
  if command_found "$t"; then
    TOOL_FOUND[$t]=1
    TOOL_PATH[$t]=$(command_path "$t")
    TOOL_VERSION[$t]=$(command_version "$t")
  else
    TOOL_FOUND[$t]=0
    TOOL_PATH[$t]=''
    TOOL_VERSION[$t]=''
  fi
done

# -----------------------------------------------------------------------------
# Python
# -----------------------------------------------------------------------------
PY_INTERPRETERS_JSON='[]'
PYTHON_PRIMARY_VERSION=''
PYTHON_PRIMARY_EXE=''
PYTHON_PRIMARY_PIP=0
PY_MANAGERS=(conda mamba micromamba poetry pipenv uv pyenv virtualenv pdm hatch)
declare -A PY_MANAGER_FOUND PY_MANAGER_PATH PY_MANAGER_VERSION
for t in "${PY_MANAGERS[@]}"; do
  if command_found "$t"; then
    PY_MANAGER_FOUND[$t]=1
    PY_MANAGER_PATH[$t]=$(command_path "$t")
    PY_MANAGER_VERSION[$t]=$("$t" --version 2>&1 | head -n1)
  else
    PY_MANAGER_FOUND[$t]=0
    PY_MANAGER_PATH[$t]=''
    PY_MANAGER_VERSION[$t]=''
  fi
done

declare -A SEEN_PY
py_entries=()
for launcher in python3 python; do
  command_found "$launcher" || continue
  probe=$(
    "$launcher" - <<'PY' 2>/dev/null || true
import platform, site, sys, sysconfig
vals = [
 sys.executable, platform.python_version(), platform.python_implementation(), sys.prefix,
 sys.base_prefix, "true" if sys.prefix != sys.base_prefix else "false",
 platform.architecture()[0], platform.platform(), site.getusersitepackages(),
 sysconfig.get_config_var("SOABI") or ""
]
print("\x1f".join(str(x).replace("\x1f", "") for x in vals))
PY
  )
  [[ -n "$probe" ]] || continue
  IFS=$'\x1f' read -r pyexe pyver pyimpl pyprefix pybase pyvenv pyarch pyplat pyusersite pysoabi <<<"$probe"
  [[ -n "$pyexe" ]] || continue
  [[ -z "${SEEN_PY[$pyexe]+x}" ]] || continue
  SEEN_PY[$pyexe]=1
  if [[ -z "$PYTHON_PRIMARY_VERSION" ]]; then
    PYTHON_PRIMARY_VERSION=$pyver
    PYTHON_PRIMARY_EXE=$pyexe
  fi
  pip_available=0
  pip_output=''
  packages_json='[]'
  if "$launcher" -m pip --version >/dev/null 2>&1; then
    pip_available=1
    pip_output=$("$launcher" -m pip --version 2>&1 | head -n1)
    [[ "$PYTHON_PRIMARY_EXE" == "$pyexe" ]] && PYTHON_PRIMARY_PIP=1
    if ((!SKIP_PACKAGE_INVENTORY)); then
      packages_json=$("$launcher" -m pip list --format=json --disable-pip-version-check 2>/dev/null || printf '[]')
      [[ "$packages_json" == \[* ]] || packages_json='[]'
    fi
  fi
  py_entries+=("{\"Launcher\":$(jstr "$launcher"),\"CommandPath\":$(jstr "$(command_path "$launcher")"),\"Executable\":$(jstr "$pyexe"),\"Version\":$(jstr "$pyver"),\"Implementation\":$(jstr "$pyimpl"),\"Prefix\":$(jstr "$pyprefix"),\"BasePrefix\":$(jstr "$pybase"),\"IsVirtualEnvironment\":$pyvenv,\"Architecture\":$(jstr "$pyarch"),\"Platform\":$(jstr "$pyplat"),\"UserSite\":$(jstr "$pyusersite"),\"SOABI\":$(jstr "$pysoabi"),\"Pip\":{\"Available\":$(jbool "$pip_available"),\"VersionOutput\":$(jstr "$pip_output"),\"Packages\":$packages_json}}")
done
if ((${#py_entries[@]})); then PY_INTERPRETERS_JSON="[$(join_by , "${py_entries[@]}")]"; fi

PY_MANAGERS_JSON='{'
pf=1
for t in "${PY_MANAGERS[@]}"; do
  ((pf)) || PY_MANAGERS_JSON+=','
  pf=0
  PY_MANAGERS_JSON+="$(jstr "$t"):{\"Found\":$(jbool "${PY_MANAGER_FOUND[$t]}"),\"Path\":$(jnull_or_str "${PY_MANAGER_PATH[$t]}"),\"Version\":$(jnull_or_str "${PY_MANAGER_VERSION[$t]}")}"
done
PY_MANAGERS_JSON+='}'

# -----------------------------------------------------------------------------
# Go
# -----------------------------------------------------------------------------
GO_FOUND=0
GO_PATH=''
GO_VERSION_OUTPUT=''
GO_VERSION_NUM=''
GO_ENV_JSON='null'
if command_found go; then
  GO_FOUND=1
  GO_PATH=$(command_path go)
  GO_VERSION_OUTPUT=$(go version 2>&1)
  GO_VERSION_NUM=$(awk '{for(i=1;i<=NF;i++) if($i ~ /^go[0-9]/){sub(/^go/,"",$i); print $i; exit}}' <<<"$GO_VERSION_OUTPUT")
  GO_ENV_JSON=$(go env -json 2>/dev/null || printf 'null')
  # Redact credentials embedded in URLs.
  GO_ENV_JSON=$(printf '%s' "$GO_ENV_JSON" | sed -E 's#(https?://)[^/@" ]+@#\1<redacted>@#g')
fi
PROJECT_GO_MODULE=''
PROJECT_WAILS_VERSION=''
if [[ -f "$PROJECT_PATH/go.mod" ]]; then
  PROJECT_GO_MODULE=$(awk '$1=="module"{print $2; exit}' "$PROJECT_PATH/go.mod")
  PROJECT_WAILS_VERSION=$(awk '$1=="github.com/wailsapp/wails/v2"{print $2; exit}' "$PROJECT_PATH/go.mod")
fi

# -----------------------------------------------------------------------------
# Wails
# -----------------------------------------------------------------------------
HAS_WAILS_JSON=0
[[ -f "$PROJECT_PATH/wails.json" ]] && HAS_WAILS_JSON=1
PKG_GTK3='' PKG_WEBKIT41='' PKG_WEBKIT40=''
if [[ "$PLATFORM" == Linux ]] && command_found pkg-config; then
  PKG_GTK3=$(pkg-config --modversion gtk+-3.0 2>/dev/null || true)
  PKG_WEBKIT41=$(pkg-config --modversion webkit2gtk-4.1 2>/dev/null || true)
  PKG_WEBKIT40=$(pkg-config --modversion webkit2gtk-4.0 2>/dev/null || true)
fi
WAILS_SUGGESTED_TAG=''
[[ -n "$PKG_WEBKIT41" && -z "$PKG_WEBKIT40" ]] && WAILS_SUGGESTED_TAG=webkit2_41

# -----------------------------------------------------------------------------
# Project inventory
# -----------------------------------------------------------------------------
PROJECT_FILES=()
for f in AGENTS.md CLAUDE.md README.md .editorconfig .gitattributes .gitignore go.mod go.work wails.json \
  pyproject.toml requirements.txt poetry.lock uv.lock Pipfile environment.yml .python-version \
  package.json .node-version .shellcheckrc Makefile CMakeLists.txt Dockerfile docker-compose.yml compose.yml; do
  [[ -e "$PROJECT_PATH/$f" ]] && PROJECT_FILES+=("$f")
done
while IFS= read -r -d '' f; do PROJECT_FILES+=("${f##*/}"); done < <(find "$PROJECT_PATH" -maxdepth 1 -type f \( -name '*.sh' -o -name '*.ps1' -o -name '*.psm1' -o -name '*.psd1' -o -name '*.py' -o -name '*.go' \) ! -name "$SCRIPT_NAME" -print0 2>/dev/null)
mapfile -t PROJECT_FILES < <(printf '%s\n' "${PROJECT_FILES[@]}" | sed '/^$/d' | sort -u)

PROJECT_WRITE_ACCESS='UNKNOWN (not tested; use --test-project-write-access)'
if ((TEST_PROJECT_WRITE_ACCESS)); then
  test_file="$PROJECT_PATH/.agent-env-write-test-$$-$RANDOM.tmp"
  if : >"$test_file" 2>/dev/null; then
    if rm -f "$test_file" 2>/dev/null; then
      PROJECT_WRITE_ACCESS=PASS
    else
      PROJECT_WRITE_ACCESS="WARN: write succeeded but cleanup failed; temporary file remains at $test_file"
    fi
  else
    PROJECT_WRITE_ACCESS='FAIL: unable to create test file'
  fi
fi

MOUNT_SOURCE=$(df -P "$PROJECT_PATH" 2>/dev/null | awk 'NR==2{print $1}')
FS_TYPE=$(stat -f -c %T "$PROJECT_PATH" 2>/dev/null || stat -f %T "$PROJECT_PATH" 2>/dev/null || true)
PROJECT_NETWORK_BACKED=0
case "$FS_TYPE" in nfs* | cifs | smb* | fuse.sshfs | 9p) PROJECT_NETWORK_BACKED=1 ;; esac
case "$MOUNT_SOURCE" in //* | *:*/*) PROJECT_NETWORK_BACKED=1 ;; esac

GIT_IS_REPO=0 GIT_ROOT='' GIT_BRANCH='' GIT_COMMIT=''
GIT_DIRTY_JSON='null' GIT_CHANGED_JSON='[]' GIT_REMOTES_JSON='[]'
GIT_ERROR='' GIT_DETECTION='GIT_NOT_FOUND' GIT_ACCESS='UNAVAILABLE'
GIT_SAFE_CMD='' GIT_SECURITY=''
if [[ ${TOOL_FOUND[git]:-0} == 1 ]]; then
  git_err=$(mktemp)
  git_root_out=$(git -C "$PROJECT_PATH" rev-parse --show-toplevel 2>"$git_err" || true)
  git_error_text=$(cat "$git_err")
  rm -f "$git_err"
  if [[ -n "$git_root_out" ]]; then
    GIT_IS_REPO=1
    GIT_ROOT=$git_root_out
    GIT_DETECTION=DETECTED
    GIT_ACCESS=READY
    GIT_BRANCH=$(git -C "$PROJECT_PATH" branch --show-current 2>/dev/null || true)
    GIT_COMMIT=$(git -C "$PROJECT_PATH" rev-parse HEAD 2>/dev/null || true)
    mapfile -t git_changed < <(git --no-optional-locks -C "$PROJECT_PATH" status --porcelain=v1 2>/dev/null || true)
    if ((${#git_changed[@]})); then GIT_DIRTY_JSON=true; else GIT_DIRTY_JSON=false; fi
    GIT_CHANGED_JSON=$(json_array_strings "${git_changed[@]}")
    mapfile -t git_remotes < <(git -C "$PROJECT_PATH" remote -v 2>/dev/null | sed -E 's#(https?://)[^/@[:space:]]+@#\1<redacted>@#g' || true)
    GIT_REMOTES_JSON=$(json_array_strings "${git_remotes[@]}")
  else
    GIT_ERROR=$git_error_text
    GIT_DETECTION=NOT_DETECTED
    GIT_ACCESS=NOT_APPLICABLE
    if grep -qi 'dubious ownership' <<<"$git_error_text"; then
      GIT_IS_REPO=1
      GIT_DETECTION=DETECTED_UNTRUSTED
      GIT_ACCESS=BLOCKED_SAFE_DIRECTORY
      GIT_ROOT=$(sed -nE "s/.*repository at ['\"]([^'\"]+)['\"].*/\1/p" <<<"$git_error_text" | head -n1)
      GIT_SAFE_CMD="git config --global --add safe.directory '$GIT_ROOT'"
      GIT_SECURITY='Only add this safe.directory exception if you trust the repository and its network location.'
    fi
  fi
fi

# -----------------------------------------------------------------------------
# Targets
# -----------------------------------------------------------------------------
valid_target() { case "${1,,}" in auto | go | wails | python | powershell | bash | all) return 0 ;; *) return 1 ;; esac }
IFS=',' read -r -a requested_targets <<<"$TARGETS_RAW"
for i in "${!requested_targets[@]}"; do
  requested_targets[i]=$(trim "${requested_targets[$i]}")
  valid_target "${requested_targets[$i]}" || die "invalid target: ${requested_targets[$i]} (valid: Auto,Go,Wails,Python,PowerShell,Bash,All)"
done
RESOLVED_TARGETS=()
add_target() {
  local v=$1 x
  for x in "${RESOLVED_TARGETS[@]}"; do [[ "$x" == "$v" ]] && return 0; done
  RESOLVED_TARGETS+=("$v")
}
has_file() { local x; for x in "${PROJECT_FILES[@]}"; do [[ "$x" == "$1" ]] && return 0; done; return 1; }
has_ext() { local x; for x in "${PROJECT_FILES[@]}"; do [[ "$x" == *".$1" ]] && return 0; done; return 1; }
for target in "${requested_targets[@]}"; do
  case "${target,,}" in
  all) for x in Go Wails Python PowerShell Bash; do add_target "$x"; done ;;
  auto)
    if has_file go.mod || has_file go.work || has_ext go; then add_target Go; fi
    if has_file wails.json || [[ -n "$PROJECT_WAILS_VERSION" ]]; then
      add_target Go
      add_target Wails
    fi
    for pf in pyproject.toml requirements.txt Pipfile uv.lock poetry.lock environment.yml; do has_file "$pf" && add_target Python; done
    has_ext py && add_target Python
    for e in ps1 psm1 psd1; do has_ext "$e" && add_target PowerShell; done
    has_ext sh && add_target Bash
    ;;
  go) add_target Go ;;
  wails)
    add_target Go
    add_target Wails
    ;;
  python) add_target Python ;;
  powershell) add_target PowerShell ;;
  bash) add_target Bash ;;
  esac
done
has_target() {
  local t=$1 x
  for x in "${RESOLVED_TARGETS[@]}"; do [[ "$x" == "$t" ]] && return 0; done
  return 1
}

# -----------------------------------------------------------------------------
# Assessment
# -----------------------------------------------------------------------------
CHECKS_JSON=()
CAPS_JSON=()
HUMAN_NOT_READY=()
HUMAN_ACTIONS=()
WARNINGS=()
add_check() {
  local area=$1 req=$2 status=$3 evidence=$4 remediation=${5-}
  CHECKS_JSON+=("{\"Area\":$(jstr "$area"),\"Requirement\":$(jstr "$req"),\"Status\":$(jstr "$status"),\"Evidence\":$(jstr "$evidence"),\"Remediation\":$(jstr "$remediation")}")
  if [[ "$status" == FAIL || "$status" == WARN ]]; then HUMAN_ACTIONS+=("$status|$area|$req|$remediation"); fi
  return 0
}
add_cap() {
  local name=$1 status=$2 summary=$3
  shift 3
  CAPS_JSON+=("{\"Name\":$(jstr "$name"),\"Status\":$(jstr "$status"),\"Summary\":$(jstr "$summary"),\"Missing\":$(json_array_strings "$@")}")
  if [[ "$status" != READY && "$status" != READY_WITH_WARNINGS ]]; then HUMAN_NOT_READY+=("$name|$status|$(join_by ", " "$@")"); fi
  return 0
}
tool_ok() { [[ ${TOOL_FOUND[$1]:-0} == 1 ]]; }

compiler=''
for c in gcc clang cc; do
  if tool_ok "$c"; then
    compiler=$c
    break
  fi
done

GO_OK=0
if ((GO_FOUND)) && [[ -n "$GO_VERSION_NUM" ]] && version_ge "$GO_VERSION_NUM" "$MIN_GO_VERSION"; then GO_OK=1; fi
PYTHON_OK=0
if [[ -n "$PYTHON_PRIMARY_VERSION" ]] && version_ge "$PYTHON_PRIMARY_VERSION" "$MIN_PYTHON_VERSION"; then PYTHON_OK=1; fi

if has_target Go; then
  if ((GO_OK)); then
    add_check Go "Go >= $MIN_GO_VERSION" PASS "$GO_VERSION_OUTPUT" ''
    add_cap 'Go applications' READY 'Go toolchain meets policy.'
  else
    add_check Go "Go >= $MIN_GO_VERSION" FAIL "${GO_VERSION_OUTPUT:-Go not found}" "Install Go $MIN_GO_VERSION or newer"
    add_cap 'Go applications' INSTALLABLE 'Install the Go toolchain to enable this stack.' "Go >= $MIN_GO_VERSION"
  fi
fi

if has_target Wails; then
  wmissing=()
  ((GO_OK)) || wmissing+=("Go >= $MIN_GO_VERSION")
  if tool_ok wails; then
    add_check Wails 'Wails CLI' PASS "${TOOL_VERSION[wails]:-present} at ${TOOL_PATH[wails]}" ''
  else
    add_check Wails 'Wails CLI' FAIL 'wails not found on PATH' 'go install github.com/wailsapp/wails/v2/cmd/wails@<pinned version>'
    wmissing+=('Wails CLI')
  fi
  if tool_ok node && tool_ok npm; then
    add_check Wails 'Node and npm (frontend)' PASS "node ${TOOL_VERSION[node]}, npm ${TOOL_VERSION[npm]}" ''
  else
    add_check Wails 'Node and npm (frontend)' FAIL 'node or npm not found' 'Install a Node LTS release'
    wmissing+=('Node/npm')
  fi
  if [[ "$PLATFORM" == Linux ]]; then
    if [[ -n "$compiler" ]]; then
      add_check Wails 'C compiler' PASS "$compiler" ''
    else
      add_check Wails 'C compiler' FAIL 'No gcc, clang or cc found' 'Install build-essential'
      wmissing+=('C compiler')
    fi
    if [[ -n "$PKG_GTK3" ]]; then
      add_check Wails 'GTK3 development files' PASS "gtk+-3.0 $PKG_GTK3" ''
    else
      add_check Wails 'GTK3 development files' FAIL 'gtk+-3.0 not found via pkg-config' 'Install libgtk-3-dev'
      wmissing+=('GTK3 dev files')
    fi
    if [[ -n "$PKG_WEBKIT41" || -n "$PKG_WEBKIT40" ]]; then
      add_check Wails 'WebKitGTK development files' PASS "webkit2gtk-4.1=${PKG_WEBKIT41:-none} webkit2gtk-4.0=${PKG_WEBKIT40:-none}${WAILS_SUGGESTED_TAG:+; build with -tags $WAILS_SUGGESTED_TAG}" ''
    else
      add_check Wails 'WebKitGTK development files' FAIL 'No webkit2gtk-4.1 or 4.0 found via pkg-config' 'Install libwebkit2gtk-4.1-dev'
      wmissing+=('WebKitGTK dev files')
    fi
    if tool_ok makensis; then add_check Wails 'NSIS (Windows installers)' PASS "${TOOL_VERSION[makensis]}" ''; else add_check Wails 'NSIS (Windows installers)' WARN 'makensis not found' 'Install nsis to build Windows installers from Linux'; fi
  else
    add_check Wails "Platform prerequisites ($PLATFORM)" 'N/A' 'Platform-specific checks are implemented for Linux only; use the PowerShell script on Windows' ''
  fi
  if ((${#wmissing[@]} == 0)); then
    add_cap 'Wails desktop applications' READY "Wails prerequisites detected on $PLATFORM."
  else
    add_cap 'Wails desktop applications' INSTALLABLE 'Install the missing Wails prerequisites.' "${wmissing[@]}"
  fi
fi

if has_target Python; then
  if ((PYTHON_OK)); then
    add_check Python "Python >= $MIN_PYTHON_VERSION" PASS "Python $PYTHON_PRIMARY_VERSION at $PYTHON_PRIMARY_EXE" ''
    if ((PYTHON_PRIMARY_PIP)); then
      add_check Python 'pip available' PASS 'pip detected for primary interpreter' ''
    else
      add_check Python 'pip available' WARN 'pip not detected for primary interpreter' 'Bootstrap pip if package installation is required.'
    fi
    mgrs=()
    for t in "${PY_MANAGERS[@]}"; do [[ "${PY_MANAGER_FOUND[$t]}" == 1 ]] && mgrs+=("$t"); done
    if ((${#mgrs[@]})); then
      add_check Python 'Environment/project manager' PASS "${mgrs[*]}" ''
    else
      add_check Python 'Environment/project manager' WARN 'None found; stdlib venv remains available' 'Install uv, Poetry or conda'
    fi
    add_cap 'Python applications' READY "Python $PYTHON_PRIMARY_VERSION is available."
  else
    add_check Python "Python >= $MIN_PYTHON_VERSION" FAIL "${PYTHON_PRIMARY_VERSION:+Python $PYTHON_PRIMARY_VERSION detected; }policy requires $MIN_PYTHON_VERSION+" "Install Python $MIN_PYTHON_VERSION or newer"
    add_cap 'Python applications' INSTALLABLE 'Install a policy-compliant Python interpreter to enable this stack.' "Python >= $MIN_PYTHON_VERSION"
  fi
fi

if has_target Bash; then
  bmissing=()
  if version_ge "${BASH_VERSINFO[0]}.${BASH_VERSINFO[1]}" "$MIN_BASH_VERSION"; then
    add_check Bash "Bash >= $MIN_BASH_VERSION" PASS "Bash $BASH_VERSION_TEXT" ''
  else
    add_check Bash "Bash >= $MIN_BASH_VERSION" FAIL "Bash $BASH_VERSION_TEXT" "Install Bash $MIN_BASH_VERSION or newer"
    bmissing+=("Bash >= $MIN_BASH_VERSION")
  fi
  if tool_ok shellcheck; then add_check Bash shellcheck PASS "${TOOL_VERSION[shellcheck]%%$'\n'*}" ''; else add_check Bash shellcheck WARN 'not installed' 'Install shellcheck'; fi
  if tool_ok shfmt; then add_check Bash shfmt PASS "${TOOL_VERSION[shfmt]%%$'\n'*}" ''; else add_check Bash shfmt WARN 'not installed' 'Install shfmt'; fi
  if tool_ok bats; then add_check Bash bats PASS "${TOOL_VERSION[bats]%%$'\n'*}" ''; else add_check Bash bats WARN 'not installed (optional test runner)' 'Install bats'; fi
  if ((${#bmissing[@]})); then
    add_cap 'Bash automation' INSTALLABLE 'Install a newer Bash.' "${bmissing[@]}"
  elif tool_ok shellcheck && tool_ok shfmt; then
    add_cap 'Bash automation' READY 'Bash and quality tools (shellcheck, shfmt) detected.'
  else
    bgaps=()
    tool_ok shellcheck || bgaps+=(shellcheck)
    tool_ok shfmt || bgaps+=(shfmt)
    add_cap 'Bash automation' READY_WITH_WARNINGS 'Bash is ready; quality tools are missing.' "${bgaps[@]}"
  fi
fi

if has_target PowerShell; then
  if [[ "$PLATFORM" == Windows ]]; then
    add_check PowerShell 'PowerShell automation' 'N/A' 'Running under a POSIX shell on Windows; run agent-environment-discovery.ps1 to assess PowerShell' ''
    add_cap 'PowerShell automation' UNKNOWN 'Not assessed by the bash script; run the PowerShell script.'
  else
    add_check PowerShell 'PowerShell automation' 'N/A' 'PowerShell is not a supported automation target on Linux/macOS; use Bash' ''
    add_cap 'PowerShell automation' BLOCKED 'PowerShell automation is supported on Windows only.' 'Windows host'
  fi
fi

if [[ "$PROJECT_NETWORK_BACKED" == 1 ]]; then
  WARNINGS+=("Project path appears network-backed ($FS_TYPE on $MOUNT_SOURCE); locking, permissions, and Git ownership may behave differently.")
fi
[[ "$GIT_ACCESS" == BLOCKED_SAFE_DIRECTORY ]] && WARNINGS+=("Git detected the repository but blocked it because of safe.directory ownership protection.")
((IS_WSL)) && WARNINGS+=("Running under WSL; Windows drives (/mnt/c) are slow and have different permissions.")

# -----------------------------------------------------------------------------
# Host documentation (optional)
# -----------------------------------------------------------------------------
UNKNOWN='<not discoverable automatically>'
if ((INCLUDE_HOST_DOC)); then
  CPU_TEXT=$(lscpu 2>/dev/null | awk -F: '$1 ~ /^Model name/ {sub(/^[ \t]+/,"",$2); print $2; exit}' || true)
  [[ -n "$CPU_TEXT" ]] || CPU_TEXT=$(sysctl -n machdep.cpu.brand_string 2>/dev/null || true)
  RAM_TEXT=$(free -h 2>/dev/null | awk '/^Mem:/ {print $2}' || true)
  [[ -n "$RAM_TEXT" ]] || RAM_TEXT=$(sysctl -n hw.memsize 2>/dev/null | awk '{printf "%.1f GiB",$1/1073741824}' || true)
  HOST_IPS=()
  if command_found hostname; then read -r -a HOST_IPS <<<"$(hostname -I 2>/dev/null || true)"; fi
  if ((${#HOST_IPS[@]} == 0)) && tool_ok ip; then mapfile -t HOST_IPS < <(ip -o -4 addr show scope global 2>/dev/null | awk '{split($4,a,"/");print a[1]}'); fi
  FQDN=$(hostname -f 2>/dev/null || true)
  DNS_NAMES=("$MACHINE_NAME")
  [[ -n "$FQDN" && "$FQDN" != "$MACHINE_NAME" ]] && DNS_NAMES+=("$FQDN")
  SERVICES=()
  for s in ssh sshd docker podman NetworkManager systemd-resolved chronyd chrony; do
    if tool_ok systemctl && systemctl list-unit-files "$s.service" >/dev/null 2>&1; then
      SERVICES+=("$s: $(systemctl is-active "$s.service" 2>/dev/null || true)")
    fi
  done
  SSH_SERVER=false
  if tool_ok systemctl && { systemctl list-unit-files ssh.service >/dev/null 2>&1 || systemctl list-unit-files sshd.service >/dev/null 2>&1; }; then SSH_SERVER=true; fi
  SSH_KEYS_EXISTS=false
  [[ -f "$HOME/.ssh/authorized_keys" ]] && SSH_KEYS_EXISTS=true
  LOCAL_USERS=()
  while IFS=: read -r name _ uid _ _ _ shell; do
    [[ "$uid" =~ ^[0-9]+$ ]] && ((uid >= 1000)) && [[ "$shell" != */nologin && "$shell" != */false ]] && LOCAL_USERS+=("$name")
  done </etc/passwd 2>/dev/null || true
  FILESYSTEMS=()
  if tool_ok findmnt; then mapfile -t FILESYSTEMS < <(findmnt -rn -o TARGET,FSTYPE,SOURCE 2>/dev/null || true); else mapfile -t FILESYSTEMS < <(mount 2>/dev/null || true); fi
  DISKS_TEXT=''
  tool_ok lsblk && DISKS_TEXT=$(lsblk -o NAME,MODEL,SERIAL,SIZE,TYPE,FSTYPE,MOUNTPOINTS -J 2>/dev/null || true)
  NIC_LINES=()
  if tool_ok ip; then mapfile -t NIC_LINES < <(ip -o link show 2>/dev/null | awk -F': ' '{name=$2; sub(/@.*/,"",name); print name}' 2>/dev/null || true); fi

  HOST_DOC_JSON="{\"HostName\":$(jstr "$MACHINE_NAME"),\"Summary\":{\"Role\":$(jstr 'Server/Workstation (not safely inferable)'),\"Site\":$(jstr "$UNKNOWN"),\"Status\":$(jstr "$UNKNOWN"),\"Contacts\":$(jstr "$UNKNOWN")},\"Hardware\":{\"System\":$(jstr "$UNKNOWN"),\"Chassis\":$(jstr "$UNKNOWN"),\"CPU\":$(json_array_strings "$CPU_TEXT"),\"RAMTotal\":$(jstr "${RAM_TEXT:-$UNKNOWN}"),\"RAMModules\":[],\"Motherboard\":$(jstr "$UNKNOWN"),\"Video\":[],\"Disks\":$(jstr "${DISKS_TEXT:-$UNKNOWN}"),\"BMC\":$(jstr "$UNKNOWN"),\"NICs\":$(json_array_strings "${NIC_LINES[@]}")},\"Storage\":{\"Boot\":$(jstr "$UNKNOWN"),\"PoolsArrays\":[],\"CacheLog\":$(jstr "$UNKNOWN"),\"Volumes\":[]},\"OS\":{\"DistroVersion\":$(jstr "$PRETTY_NAME"),\"Kernel\":$(jstr "$KERNEL"),\"Filesystems\":$(json_array_strings "${FILESYSTEMS[@]}"),\"Encryption\":$(jstr "$UNKNOWN"),\"BootMediaUUIDs\":[]},\"Network\":{\"MgmtIP\":$(jstr "$UNKNOWN"),\"HostIPs\":$(json_array_strings "${HOST_IPS[@]}"),\"VLANs\":$(jstr "$UNKNOWN"),\"DNSNames\":$(json_array_strings "${DNS_NAMES[@]}"),\"Interfaces\":[]},\"Services\":$(json_array_strings "${SERVICES[@]}"),\"Backups\":{\"What\":$(jstr "$UNKNOWN"),\"Where\":$(jstr "$UNKNOWN"),\"Schedule\":$(jstr "$UNKNOWN"),\"HealthChecks\":$(jstr "$UNKNOWN")},\"Access\":{\"SSH\":{\"ServerDetected\":$SSH_SERVER,\"UserAuthorizedKeys\":{\"Path\":$(jstr "$HOME/.ssh/authorized_keys"),\"Exists\":$SSH_KEYS_EXISTS}},\"LocalUsers\":$(json_array_strings "${LOCAL_USERS[@]}"),\"BreakGlass\":$(jstr "$UNKNOWN")},\"BuildRestore\":[$(jstr "$UNKNOWN")],\"HistoricalNotes\":{\"PurchaseDates\":$(jstr "$UNKNOWN"),\"Why\":$(jstr "$UNKNOWN"),\"PreviousOwnersOrUses\":$(jstr "$UNKNOWN"),\"ChangeHistory\":$(jstr "$UNKNOWN")}}"
fi

write_host_doc() {
  local path=$1
  {
    printf '# %s\n\n' "$MACHINE_NAME"
    printf '## Summary\n- Role: Server/Workstation (not safely inferable)\n- Site: %s\n- Status: %s\n- Contacts: %s\n\n' "$UNKNOWN" "$UNKNOWN" "$UNKNOWN"
    printf '## Hardware\n- System: %s\n- Chassis: %s\n- CPU: %s\n- RAM: %s\n- BMC/IPMI: %s\n\n' "$UNKNOWN" "$UNKNOWN" "${CPU_TEXT:-$UNKNOWN}" "${RAM_TEXT:-$UNKNOWN}" "$UNKNOWN"
    printf '## OS\n- Distro/Version: %s\n- Kernel: %s\n- Filesystem: %s\n- Encryption: %s\n\n' "$PRETTY_NAME" "$KERNEL" "$(join_by '; ' "${FILESYSTEMS[@]}")" "$UNKNOWN"
    printf '## Network\n- Mgmt IP (BMC): %s\n- Host IP(s): %s\n- VLANs: %s\n- DNS name(s): %s\n\n' "$UNKNOWN" "$(join_by '; ' "${HOST_IPS[@]}")" "$UNKNOWN" "$(join_by '; ' "${DNS_NAMES[@]}")"
    printf '## Services\n'
    if ((${#SERVICES[@]})); then printf -- '- %s\n' "${SERVICES[@]}"; else printf -- '- <no selected platform services detected>\n'; fi
    printf '\n## Backups\n- What: %s\n- Where: %s\n- Schedule: %s\n- Health checks: %s\n\n' "$UNKNOWN" "$UNKNOWN" "$UNKNOWN" "$UNKNOWN"
    printf '## Access\n- SSH: server detected=%s; user authorized_keys=%s\n- Break-glass: %s\n- Local users: %s\n\n' "$SSH_SERVER" "$SSH_KEYS_EXISTS" "$UNKNOWN" "$(join_by ', ' "${LOCAL_USERS[@]}")"
    printf '## Build/Restore (TL;DR)\n1. %s\n\n## Config / Historical Notes\n- Purchase dates: %s\n- Why / design intent: %s\n- Previous owners/uses: %s\n\n' "$UNKNOWN" "$UNKNOWN" "$UNKNOWN" "$UNKNOWN"
    printf '## Change Log\n- %s - Discovery draft generated by %s\n' "$(date +%F)" "$SCRIPT_NAME"
  } >"$path"
}

# -----------------------------------------------------------------------------
# JSON assembly
# -----------------------------------------------------------------------------
TOOLS_JSON='{'
tf=1
for t in "${TOOLS[@]}"; do
  ((tf)) || TOOLS_JSON+=','
  tf=0
  TOOLS_JSON+="$(jstr "$t"):{\"Found\":$(jbool "${TOOL_FOUND[$t]:-0}"),\"Path\":$(jnull_or_str "${TOOL_PATH[$t]:-}"),\"Version\":$(jnull_or_str "${TOOL_VERSION[$t]:-}")}"
done
TOOLS_JSON+='}'

CI_INDICATORS=()
for v in CI GITHUB_ACTIONS GITLAB_CI TF_BUILD JENKINS_URL TEAMCITY_VERSION; do [[ -n "${!v:-}" ]] && CI_INDICATORS+=("$v"); done
PROXY=0
[[ -n "${HTTP_PROXY:-}${HTTPS_PROXY:-}${ALL_PROXY:-}${http_proxy:-}${https_proxy:-}" ]] && PROXY=1

CHECKS_JOINED="[$(join_by , "${CHECKS_JSON[@]}")]"
CAPS_JOINED="[$(join_by , "${CAPS_JSON[@]}")]"
RESOLVED_TARGETS_JSON=$(json_array_strings "${RESOLVED_TARGETS[@]}")
REQUESTED_TARGETS_JSON=$(json_array_strings "${requested_targets[@]}")
PROJECT_FILES_JSON=$(json_array_strings "${PROJECT_FILES[@]}")

PYTHON_JSON="{\"Interpreters\":$PY_INTERPRETERS_JSON,\"Managers\":$PY_MANAGERS_JSON,\"ActiveEnvironment\":{\"VIRTUAL_ENV\":$(jnull_or_str "${VIRTUAL_ENV:-}"),\"CONDA_PREFIX\":$(jnull_or_str "${CONDA_PREFIX:-}"),\"CONDA_DEFAULT_ENV\":$(jnull_or_str "${CONDA_DEFAULT_ENV:-}"),\"PYENV_VERSION\":$(jnull_or_str "${PYENV_VERSION:-}"),\"POETRY_ACTIVE\":$(jnull_or_str "${POETRY_ACTIVE:-}")},\"ProjectFiles\":$(json_array_strings "$(for f in pyproject.toml poetry.lock uv.lock Pipfile requirements.txt environment.yml .python-version; do has_file "$f" && echo "$f"; done)")}"
GO_JSON="{\"Found\":$(jbool "$GO_FOUND"),\"Command\":{\"Found\":$(jbool "$GO_FOUND"),\"Path\":$(jnull_or_str "$GO_PATH")},\"Version\":$(jnull_or_str "$GO_VERSION_OUTPUT"),\"Environment\":$GO_ENV_JSON,\"Project\":{\"HasGoMod\":$(jbool "$(has_file go.mod && echo 1 || echo 0)"),\"Module\":$(jnull_or_str "$PROJECT_GO_MODULE"),\"HasGoWork\":$(jbool "$(has_file go.work && echo 1 || echo 0)"),\"HasVendor\":$(jbool "$([[ -d "$PROJECT_PATH/vendor" ]] && echo 1 || echo 0)")}}"
WAILS_JSON="{\"CLI\":{\"Found\":$(jbool "${TOOL_FOUND[wails]:-0}"),\"Path\":$(jnull_or_str "${TOOL_PATH[wails]:-}"),\"Version\":$(jnull_or_str "${TOOL_VERSION[wails]:-}")},\"Project\":{\"HasWailsJson\":$(jbool "$HAS_WAILS_JSON"),\"ModuleVersion\":$(jnull_or_str "$PROJECT_WAILS_VERSION")},\"Linux\":{\"Gtk3\":$(jnull_or_str "$PKG_GTK3"),\"WebKit41\":$(jnull_or_str "$PKG_WEBKIT41"),\"WebKit40\":$(jnull_or_str "$PKG_WEBKIT40"),\"SuggestedBuildTag\":$(jnull_or_str "$WAILS_SUGGESTED_TAG")},\"Frontend\":{\"Node\":$(jnull_or_str "${TOOL_VERSION[node]:-}"),\"Npm\":$(jnull_or_str "${TOOL_VERSION[npm]:-}")},\"Packaging\":{\"Nsis\":$(jnull_or_str "${TOOL_VERSION[makensis]:-}"),\"Osslsigncode\":$(jnull_or_str "${TOOL_VERSION[osslsigncode]:-}")}}"
BASH_JSON="{\"Version\":$(jstr "$BASH_VERSION_TEXT"),\"QualityTools\":{\"shellcheck\":$(jnull_or_str "${TOOL_VERSION[shellcheck]:-}"),\"shfmt\":$(jnull_or_str "${TOOL_VERSION[shfmt]:-}"),\"bats\":$(jnull_or_str "${TOOL_VERSION[bats]:-}")}}"
TOOLS_WRAPPER_JSON="{\"Commands\":$TOOLS_JSON,\"ProxyConfigured\":$(jbool "$PROXY"),\"CIIndicators\":$(json_array_strings "${CI_INDICATORS[@]}")}"
PROJECT_JSON="{\"Path\":$(jstr "$PROJECT_PATH"),\"Files\":$PROJECT_FILES_JSON,\"Filesystem\":{\"Type\":$(jstr "$FS_TYPE"),\"Source\":$(jstr "$MOUNT_SOURCE"),\"IsNetworkBacked\":$(jbool "$PROJECT_NETWORK_BACKED"),\"WriteAccess\":$(jstr "$PROJECT_WRITE_ACCESS")},\"Git\":{\"IsRepository\":$(jbool "$GIT_IS_REPO"),\"Root\":$(jnull_or_str "$GIT_ROOT"),\"Branch\":$(jnull_or_str "$GIT_BRANCH"),\"Commit\":$(jnull_or_str "$GIT_COMMIT"),\"Dirty\":$GIT_DIRTY_JSON,\"ChangedFiles\":$GIT_CHANGED_JSON,\"Remotes\":$GIT_REMOTES_JSON,\"Error\":$(jnull_or_str "$GIT_ERROR"),\"DetectionStatus\":$(jstr "$GIT_DETECTION"),\"AccessStatus\":$(jstr "$GIT_ACCESS"),\"SafeDirectoryCommand\":$(jnull_or_str "$GIT_SAFE_CMD"),\"SecurityRecommendation\":$(jnull_or_str "$GIT_SECURITY")}}"

ready_count=0
notready_count=0
for c in "${CAPS_JSON[@]}"; do
  if [[ "$c" == *'"Status":"READY"'* || "$c" == *'"Status":"READY_WITH_WARNINGS"'* ]]; then ((ready_count += 1)); else ((notready_count += 1)); fi
done
if ((${#CAPS_JSON[@]} == 0)); then
  CONCLUSION="No stack targets were selected or inferred; only host facts were collected. Use --targets to assess a stack."
else
  CONCLUSION="$ready_count selected capabilities are ready or ready with warnings; $notready_count require installation or are blocked."
fi

NOT_READY_JSON='['
nf=1
for row in "${HUMAN_NOT_READY[@]}"; do
  IFS='|' read -r n s m <<<"$row"
  ((nf)) || NOT_READY_JSON+=','
  nf=0
  NOT_READY_JSON+="{\"Name\":$(jstr "$n"),\"Status\":$(jstr "$s"),\"Missing\":$(json_array_strings "$m")}"
done
NOT_READY_JSON+=']'
ACTIONS_JSON='['
af=1
for row in "${HUMAN_ACTIONS[@]}"; do
  IFS='|' read -r s a r rem <<<"$row"
  ((af)) || ACTIONS_JSON+=','
  af=0
  ACTIONS_JSON+="{\"Status\":$(jstr "$s"),\"Area\":$(jstr "$a"),\"Requirement\":$(jstr "$r"),\"Remediation\":$(jstr "$rem")}"
done
ACTIONS_JSON+=']'
HUMAN_JSON="{\"Conclusion\":$(jstr "$CONCLUSION"),\"NotReady\":$NOT_READY_JSON,\"EnvironmentWarnings\":$(json_array_strings "${WARNINGS[@]}"),\"RecommendedActions\":$ACTIONS_JSON}"

VALIDATION=()
has_target Go && VALIDATION+=('go test ./...' 'go vet ./...')
has_target Wails && VALIDATION+=('wails doctor')
has_target Python && VALIDATION+=('python3 -m pip check')
has_target Bash && VALIDATION+=('shellcheck <file>' 'shfmt -d <file>')
VALIDATION+=('git status --short')
AGENT_JSON="{\"Project\":$PROJECT_JSON,\"Constraints\":{\"ProjectIsNetworkBacked\":$(jbool "$PROJECT_NETWORK_BACKED"),\"ProjectWriteAccess\":$(jstr "$PROJECT_WRITE_ACCESS"),\"IsElevated\":$(jbool "$IS_ELEVATED"),\"IsWSL\":$(jbool "$IS_WSL"),\"Shell\":$(jstr "$CURRENT_SHELL"),\"BashVersion\":$(jstr "$BASH_VERSION_TEXT")},\"SuggestedValidationCommands\":$(json_array_strings "${VALIDATION[@]}"),\"Limitations\":$(json_array_strings 'Discovery does not intentionally modify projects and does not prove project-directory write access.' 'Tool presence does not prove that a clean build or package restore succeeds.' 'Commands installed outside PATH may not be detected.' 'No secret environment-variable values are collected.')}"

GENERATED_AT=$(date --iso-8601=seconds 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S%z')
REPORT="{\"SchemaVersion\":$(jstr "$SCHEMA_VERSION"),\"Metadata\":{\"GeneratedAt\":$(jstr "$GENERATED_AT"),\"ScriptName\":$(jstr "$SCRIPT_NAME"),\"ScriptVersion\":$(jstr "$SCRIPT_VERSION"),\"Audience\":$(jstr "$AUDIENCE"),\"RequestedTargets\":$REQUESTED_TARGETS_JSON,\"ResolvedTargets\":$RESOLVED_TARGETS_JSON,\"ReadOnlyDiscovery\":$(jbool "$((1 - TEST_PROJECT_WRITE_ACCESS))"),\"ProjectWriteTestRequested\":$(jbool "$TEST_PROJECT_WRITE_ACCESS"),\"PackageInventorySkipped\":$(jbool "$SKIP_PACKAGE_INVENTORY"),\"Policy\":{\"MinimumPythonVersion\":$(jstr "$MIN_PYTHON_VERSION"),\"MinimumGoVersion\":$(jstr "$MIN_GO_VERSION"),\"MinimumBashVersion\":$(jstr "$MIN_BASH_VERSION"),\"MinimumPesterVersion\":null,\"MinimumPSScriptAnalyzerVersion\":null},\"Notes\":$(json_array_strings 'PASS means prerequisites were detected, not that a sample build was compiled.' 'WARN means usable with limitations or that runtime validation is still required.' 'No project files are intentionally modified; first-run tool probes may initialize tool-local user caches.' 'No secret environment-variable values are collected.')}"
REPORT+=",\"OS\":{\"Platform\":$(jstr "$PLATFORM"),\"Details\":{\"Uname\":$(jstr "$UNAME_A"),\"DistroVersion\":$(jstr "$PRETTY_NAME"),\"Kernel\":$(jstr "$KERNEL")},\"MachineName\":$(jstr "$MACHINE_NAME"),\"UserName\":$(jstr "$USER_NAME"),\"OSArchitecture\":$(jstr "$OS_ARCH"),\"IsElevated\":$(jbool "$IS_ELEVATED"),\"TimeZone\":$(jstr "$TIMEZONE"),\"CurrentDirectory\":$(jstr "$PWD"),\"ProjectPath\":$(jstr "$PROJECT_PATH")},\"Runtime\":{\"Shell\":\"Bash\",\"ShellVersion\":$(jstr "$BASH_VERSION_TEXT"),\"EffectiveExecutionPolicy\":null},\"Assessment\":{\"Checks\":$CHECKS_JOINED,\"Capabilities\":$CAPS_JOINED}"
[[ "$AUDIENCE" == Human || "$AUDIENCE" == All ]] && REPORT+=",\"Human\":$HUMAN_JSON"
((INCLUDE_HOST_DOC)) && REPORT+=",\"HostDocumentation\":$HOST_DOC_JSON"
if [[ "$AUDIENCE" == Agent || "$AUDIENCE" == All ]]; then
  REPORT+=",\"Agent\":$AGENT_JSON,\"Shell\":{\"Current\":\"Bash\",\"Executable\":$(jstr "${BASH:-$(command_path bash)}"),\"Version\":$(jstr "$BASH_VERSION_TEXT"),\"ParentProcessChain\":$PARENT_CHAIN_JSON,\"EnvironmentHints\":{\"SHELL\":$(jnull_or_str "${SHELL:-}"),\"TERM\":$(jnull_or_str "${TERM:-}"),\"SSH_TTY_Present\":$(jbool "$([[ -n "${SSH_TTY:-}" ]] && echo 1 || echo 0)")}},\"Python\":$PYTHON_JSON,\"Go\":$GO_JSON,\"Wails\":$WAILS_JSON,\"Bash\":$BASH_JSON,\"Tools\":$TOOLS_WRAPPER_JSON,\"Project\":$PROJECT_JSON"
fi
REPORT+='}'

# -----------------------------------------------------------------------------
# Output
# -----------------------------------------------------------------------------
write_console() {
  printf 'Development Environment Fingerprint\n'
  printf 'Generated: %s\n' "$GENERATED_AT"
  printf 'Host: %s | OS: %s (%s) | Architecture: %s\n' "$MACHINE_NAME" "$PLATFORM" "$PRETTY_NAME" "$OS_ARCH"
  printf 'Shell: Bash %s\n' "$BASH_VERSION_TEXT"
  printf 'Project: %s\nAudience: %s\nTargets: %s\n' "$PROJECT_PATH" "$AUDIENCE" "$(join_by ', ' "${RESOLVED_TARGETS[@]}")"
  if [[ "$AUDIENCE" == Human || "$AUDIENCE" == All ]]; then
    printf '\nHUMAN SUMMARY\n%s\n\nCAPABILITY SUMMARY\n' "$CONCLUSION"
    for c in "${CAPS_JSON[@]}"; do
      status=$(sed -nE 's/.*"Status":"([^"]+)".*/\1/p' <<<"$c")
      name=$(sed -nE 's/.*"Name":"([^"]+)".*/\1/p' <<<"$c")
      summary=$(sed -nE 's/.*"Summary":"([^"]+)".*/\1/p' <<<"$c")
      printf '  %-20s %-34s %s\n' "$status" "$name" "$summary"
    done
    if ((${#WARNINGS[@]})); then
      printf '\nENVIRONMENT WARNINGS\n'
      printf '  - %s\n' "${WARNINGS[@]}"
    fi
    if ((${#HUMAN_ACTIONS[@]})); then
      printf '\nRECOMMENDED NEXT ACTIONS\n'
      for r in "${HUMAN_ACTIONS[@]}"; do
        IFS='|' read -r s a req rem <<<"$r"
        printf '  - [%s] %s / %s: %s\n' "$s" "$a" "$req" "$rem"
      done
    fi
  fi
  if [[ "$AUDIENCE" == Agent || "$AUDIENCE" == All ]]; then
    printf '\nAGENT HANDOFF SUMMARY\n  Repository: %s\n  Branch: %s\n  Working tree dirty: %s\n  Network-backed project: %s\n  Project write access: %s\n  Elevated: %s\n' "${GIT_ROOT:-not detected}" "${GIT_BRANCH:-n/a}" "$GIT_DIRTY_JSON" "$PROJECT_NETWORK_BACKED" "$PROJECT_WRITE_ACCESS" "$IS_ELEVATED"
    if [[ "$GIT_ACCESS" == BLOCKED_SAFE_DIRECTORY ]]; then printf '  Git evidence: %s\n  Suggested command (only if trusted): %s\n' "$GIT_ERROR" "$GIT_SAFE_CMD"; fi
    if [[ "$FORMAT" == Console ]]; then printf '  Use --format Both to save the complete agent handoff as JSON.\n'; fi
  fi
  if ((INCLUDE_HOST_DOC)); then
    printf '\nHOST DOCUMENTATION DISCOVERY\n  CPU: %s\n  RAM: %s\n  IPs: %s\n  DNS names: %s\n  Historical/intent fields are intentionally left as not discoverable.\n' "${CPU_TEXT:-$UNKNOWN}" "${RAM_TEXT:-$UNKNOWN}" "$(join_by ', ' "${HOST_IPS[@]}")" "$(join_by ', ' "${DNS_NAMES[@]}")"
  fi
}

if [[ -n "$HOST_DOC_PATH" ]]; then
  write_host_doc "$HOST_DOC_PATH" || die "failed to write host documentation: $HOST_DOC_PATH"
  [[ "$FORMAT" != Json ]] && printf '\nHost documentation draft written to: %s\n' "$HOST_DOC_PATH"
fi

case "$FORMAT" in
Console) write_console ;;
Json)
  printf '%s\n' "$REPORT"
  [[ -n "$OUTPUT_PATH" ]] && printf '%s\n' "$REPORT" >"$OUTPUT_PATH"
  ;;
Both)
  write_console
  [[ -n "$OUTPUT_PATH" ]] || OUTPUT_PATH="$PWD/agent-environment.json"
  printf '%s\n' "$REPORT" >"$OUTPUT_PATH" || die "failed to write JSON: $OUTPUT_PATH"
  printf '\nJSON report written to: %s\n' "$OUTPUT_PATH"
  ;;
esac

exit 0
