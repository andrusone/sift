#!/usr/bin/env bash
# check-placeholders.sh
# Lists unresolved <<REPLACE: ...>> markers left from the OneFoundry template.
# Exit 0 when none remain, 1 when some do (use --warn to always exit 0).
#
#   tools/check-placeholders.sh [--warn] [path]

set -euo pipefail

WARN=0
ROOT=""
for a in "$@"; do
  case "$a" in
  --warn) WARN=1 ;;
  -h | --help)
    sed -n '2,6p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  *) ROOT="$a" ;;
  esac
done
ROOT="${ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"

# Only tracked files, never this script or the template's own documentation of the marker.
matches="$(cd "$ROOT" && git ls-files -z 2>/dev/null | xargs -0 grep -nH '<<REPLACE' 2>/dev/null |
  grep -v '^tools/check-placeholders' || true)"

if [[ -z "$matches" ]]; then
  echo "No unresolved <<REPLACE>> markers."
  exit 0
fi

count="$(wc -l <<<"$matches" | tr -d ' ')"
echo "$count unresolved <<REPLACE>> marker(s):"
sed 's/^/  /' <<<"$matches"
((WARN)) && exit 0
exit 1
