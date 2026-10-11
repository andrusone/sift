#!/usr/bin/env bash
# bootstrap.sh
# Configures what a GitHub template cannot copy: labels, repository settings,
# the Projects v2 board (status options and custom fields), branch protection,
# and the sprint log issue. Reads policy from ./config/*.tsv.
#
# Safe by default: without --apply it only READS from GitHub and prints the plan.
# Idempotent: re-running converges. It never deletes anything and only touches a
# project whose title exactly matches --project-title.
#
# Requires: gh (authenticated with the repo, project and workflow scopes), bash 4.4+.
# No jq needed; gh's built-in -q is used to read its own output.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$SCRIPT_DIR/config"

log() { echo "[github-bootstrap] $*"; }
warn() { echo "[github-bootstrap][WARN] $*" >&2; }
die() {
  echo "[github-bootstrap][ERROR] $*" >&2
  exit 1
}

REPO=""
PROJECT_TITLE=""
BRANCH="main"
REQUIRED_CHECKS=""
STEPS="labels,settings,project,protection,sprint-log"
APPLY=0
ALLOW_TEMPLATE=0

usage() {
  cat <<'EOF'
Usage: bootstrap.sh [options]

Without --apply, nothing is changed: GitHub is only read and the plan is printed.

Options:
  --repo OWNER/NAME        Target repository (default: the repo of the current directory)
  --project-title TITLE    Projects v2 board title (default: the repository name)
  --branch NAME            Branch to protect (default: main)
  --required-checks LIST   Comma-separated CI check names required to merge
                           (default: none; set once CI exists, e.g. "windows,ubuntu")
  --only LIST              Comma-separated steps: labels,settings,project,protection,sprint-log
                           (default: all)
  --apply                  Make the changes
  --allow-template         Allow --apply on a repo marked as a template (normally refused)
  --allow-template         Allow --apply against a repository marked as a template (normally refused)
  -h, --help               Show help

Examples:
  ./bootstrap.sh                          # plan only
  ./bootstrap.sh --apply
  ./bootstrap.sh --only labels,project --apply
  ./bootstrap.sh --required-checks "windows,ubuntu" --only protection --apply
EOF
}

while (($#)); do
  case "$1" in
  --repo | --project-title | --branch | --required-checks | --only)
    [[ $# -ge 2 ]] || die "$1 requires a value"
    case "$1" in
    --repo) REPO=$2 ;;
    --project-title) PROJECT_TITLE=$2 ;;
    --branch) BRANCH=$2 ;;
    --required-checks) REQUIRED_CHECKS=$2 ;;
    --only) STEPS=$2 ;;
    esac
    shift 2
    ;;
  --apply)
    APPLY=1
    shift
    ;;
  --allow-template)
    ALLOW_TEMPLATE=1
    shift
    ;;
  -h | --help)
    usage
    exit 0
    ;;
  *) die "unknown argument: $1 (use --help)" ;;
  esac
done

command -v gh >/dev/null 2>&1 || die "gh (GitHub CLI) is required"
gh auth status >/dev/null 2>&1 || die "gh is not authenticated; run: gh auth login"

if [[ -z "$REPO" ]]; then
  REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)" ||
    die "could not determine the repository; pass --repo OWNER/NAME"
fi
[[ "$REPO" == */* ]] || die "--repo must be OWNER/NAME"
OWNER="${REPO%%/*}"
NAME="${REPO##*/}"
[[ -n "$PROJECT_TITLE" ]] || PROJECT_TITLE="$NAME"
[[ "$PROJECT_TITLE" != *'"'* && "$PROJECT_TITLE" != *'\'* ]] || die "--project-title must not contain quotes or backslashes"

IS_TEMPLATE="$(gh repo view "$REPO" --json isTemplate -q .isTemplate 2>/dev/null || echo false)"
if [[ "$IS_TEMPLATE" == true ]] && ((APPLY)) && ((!ALLOW_TEMPLATE)); then
  die "$REPO is a template repository. Run the bootstrap against a repo created FROM the template, not the template itself (override: --allow-template)."
fi

step_enabled() { [[ ",$STEPS," == *",$1,"* ]]; }
for s in ${STEPS//,/ }; do
  case "$s" in labels | settings | project | protection | sprint-log) ;; *) die "unknown step: $s" ;; esac
done

# Run a mutating command, or print it in plan mode.
run() {
  if ((APPLY)); then
    "$@"
  else
    printf '  [plan] '
    printf '%q ' "$@"
    echo
  fi
}

if ((APPLY)); then log "APPLY mode: changing $REPO"; else log "PLAN mode (no changes): $REPO. Re-run with --apply to make them."; fi
log "project title: '$PROJECT_TITLE'  steps: $STEPS"

# -----------------------------------------------------------------------------
# Labels
# -----------------------------------------------------------------------------
do_labels() {
  log "== labels"
  local existing name color desc cur
  existing="$(gh label list --repo "$REPO" --limit 200 --json name,color,description \
    -q '.[] | [.name, .color, .description] | @tsv')"
  while IFS=$'\t' read -r name color desc; do
    [[ -z "$name" || "$name" == \#* ]] && continue
    cur="$(awk -F'\t' -v n="$name" '$1 == n { print $2 "\t" $3 }' <<<"$existing")"
    if [[ -z "$cur" ]]; then
      log "label '$name': create"
    elif [[ "$cur" == "$color"$'\t'"$desc" ]]; then
      log "label '$name': ok"
      continue
    else
      log "label '$name': update"
    fi
    run gh label create "$name" --repo "$REPO" --color "$color" --description "$desc" --force
  done <"$CONFIG_DIR/labels.tsv"
}

# -----------------------------------------------------------------------------
# Repository settings
# -----------------------------------------------------------------------------
do_settings() {
  log "== repository settings"
  log "squash merge only, delete branch on merge, wiki off, issues and projects on"
  run gh repo edit "$REPO" \
    --enable-squash-merge --enable-merge-commit=false --enable-rebase-merge=false \
    --delete-branch-on-merge --enable-wiki=false --enable-issues --enable-projects
}

# -----------------------------------------------------------------------------
# Project (Projects v2)
# -----------------------------------------------------------------------------
PROJECT_NUMBER=""
find_project() {
  gh project list --owner "$OWNER" --limit 100 --format json \
    -q ".projects[] | select(.title == \"$PROJECT_TITLE\") | .number" | head -n1
}

do_project() {
  log "== project '$PROJECT_TITLE'"
  PROJECT_NUMBER="$(find_project || true)"
  if [[ -n "$PROJECT_NUMBER" ]]; then
    log "project exists: #$PROJECT_NUMBER"
  else
    log "project does not exist: create"
    if ((APPLY)); then
      PROJECT_NUMBER="$(gh project create --owner "$OWNER" --title "$PROJECT_TITLE" --format json -q .number)"
      log "created project #$PROJECT_NUMBER"
    else
      run gh project create --owner "$OWNER" --title "$PROJECT_TITLE"
    fi
  fi

  if [[ -n "$PROJECT_NUMBER" ]]; then
    run gh project link "$PROJECT_NUMBER" --owner "$OWNER" --repo "$REPO"
  fi

  local fields=""
  if [[ -n "$PROJECT_NUMBER" ]]; then
    fields="$(gh project field-list "$PROJECT_NUMBER" --owner "$OWNER" --format json \
      -q '.fields[] | [.id, .name, .type] | @tsv')"
  fi

  # Status options (replaces the default Todo / In Progress / Done on a new board)
  local want="" name color desc opts="" status_id cur_opts
  while IFS=$'\t' read -r name color desc; do
    [[ -z "$name" || "$name" == \#* ]] && continue
    want+="${want:+,}$name"
    opts+="${opts:+,}{name:\"$name\",color:$color,description:\"$desc\"}"
  done <"$CONFIG_DIR/project-status.tsv"

  status_id="$(awk -F'\t' '$2 == "Status" { print $1 }' <<<"$fields")"
  if [[ -z "$status_id" ]]; then
    log "Status field: set options [$want] (after the project exists)"
  else
    cur_opts="$(gh project field-list "$PROJECT_NUMBER" --owner "$OWNER" --format json \
      -q '.fields[] | select(.name == "Status") | [.options[].name] | join(",")')"
    if [[ "$cur_opts" == "$want" ]]; then
      log "Status field: ok [$want]"
    else
      log "Status field: set options [$want] (currently [$cur_opts])"
      run gh api graphql -f f="$status_id" -f query="mutation(\$f: ID!) { updateProjectV2Field(input: {fieldId: \$f, singleSelectOptions: [$opts]}) { projectV2Field { ... on ProjectV2SingleSelectField { id } } } }"
    fi
  fi

  # Custom fields
  local ftype fopts dtype
  while IFS=$'\t' read -r name ftype fopts; do
    [[ -z "$name" || "$name" == \#* ]] && continue
    if awk -F'\t' -v n="$name" '$2 == n { found = 1 } END { exit !found }' <<<"$fields"; then
      log "field '$name': ok"
      continue
    fi
    log "field '$name' ($ftype): create"
    case "$ftype" in
    single_select) dtype=SINGLE_SELECT ;;
    number) dtype=NUMBER ;;
    text) dtype=TEXT ;;
    date) dtype=DATE ;;
    *) die "unknown field type '$ftype' for '$name'" ;;
    esac
    if [[ -z "$PROJECT_NUMBER" ]]; then
      if [[ "$dtype" == SINGLE_SELECT ]]; then
        run gh project field-create "<new project>" --owner "$OWNER" --name "$name" --data-type SINGLE_SELECT --single-select-options "$fopts"
      else
        run gh project field-create "<new project>" --owner "$OWNER" --name "$name" --data-type "$dtype"
      fi
    elif [[ "$dtype" == SINGLE_SELECT ]]; then
      run gh project field-create "$PROJECT_NUMBER" --owner "$OWNER" --name "$name" --data-type SINGLE_SELECT --single-select-options "$fopts"
    else
      run gh project field-create "$PROJECT_NUMBER" --owner "$OWNER" --name "$name" --data-type "$dtype"
    fi
  done <"$CONFIG_DIR/project-fields.tsv"
}

# -----------------------------------------------------------------------------
# Branch protection
# -----------------------------------------------------------------------------
do_protection() {
  log "== branch protection ($BRANCH)"
  local checks="null" c first=1
  if [[ -n "$REQUIRED_CHECKS" ]]; then
    checks='{"strict":true,"contexts":['
    for c in ${REQUIRED_CHECKS//,/ }; do
      ((first)) || checks+=','
      first=0
      checks+="\"$c\""
    done
    checks+=']}'
  fi
  local body
  body="$(
    cat <<EOF
{
  "required_status_checks": $checks,
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 0,
    "dismiss_stale_reviews": true
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
EOF
  )"
  log "require PR, linear history, no force-push or deletion, resolved conversations; required checks: ${REQUIRED_CHECKS:-none}"
  if ((APPLY)); then
    local out
    if out="$(gh api -X PUT "repos/$REPO/branches/$BRANCH/protection" --input - <<<"$body" 2>&1)"; then
      log "branch protection set"
    elif grep -q 'Upgrade to GitHub Pro or make this repository public' <<<"$out"; then
      warn "branch protection is unavailable: this repo is private on a plan without it."
      warn "Make the repo public (or upgrade), then re-run: ./bootstrap.sh --only protection --apply"
    else
      die "branch protection failed: $out"
    fi
  else
    log "[plan] gh api -X PUT repos/$REPO/branches/$BRANCH/protection (body below)"
    sed 's/^/    /' <<<"$body"
  fi
}

# -----------------------------------------------------------------------------
# Sprint log issue
# -----------------------------------------------------------------------------
do_sprint_log() {
  log "== sprint log issue"
  local n
  n="$(gh issue list --repo "$REPO" --label sprint-log --state all --limit 1 --json number -q '.[0].number // empty')"
  if [[ -n "$n" ]]; then
    log "sprint log exists: #$n"
    return 0
  fi
  log "no sprint log: create and pin"
  if ((APPLY)); then
    local url num
    url="$(gh issue create --repo "$REPO" --title "Sprint log" --label sprint-log \
      --body $'One check-in comment each time the architect looks, plus metrics.\n\nSee docs/OPERATING-MODEL.md.')"
    num="${url##*/}"
    gh api graphql -f query="mutation { pinIssue(input: {issueId: \"$(gh issue view "$num" --repo "$REPO" --json id -q .id)\"}) { issue { number } } }" >/dev/null ||
      warn "could not pin issue #$num; pin it manually"
    log "created sprint log: $url"
  else
    run gh issue create --repo "$REPO" --title "Sprint log" --label sprint-log
  fi
}

step_enabled labels && do_labels
step_enabled settings && do_settings
step_enabled project && do_project
step_enabled protection && do_protection
step_enabled sprint-log && do_sprint_log

if ((APPLY)); then log "Done."; else log "Plan complete. Nothing was changed."; fi
