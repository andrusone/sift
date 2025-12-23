#!/usr/bin/env bash
# setup-sift.sh
#
# Idempotent setup for the "sift" repo (Linux).
#
# Installs runtime deps:
# - ffprobe (via ffmpeg)
# - python3 (>= 3.11 strongly recommended for tomllib)
#
# Installs helpful tooling (optional but recommended):
# - python3-venv (for local venvs)
# - python3-pip (if you later add small deps)
# - jq (only needed if you choose to parse ffprobe JSON in shell; safe to have)
#
# Usage:
#   sudo ./setup-sift.sh
#
# Notes:
# - This script is intentionally conservative. It does NOT curl | bash anything.
# - On Ubuntu 24.04+ you already have Python 3.12 and tomllib built-in.

set -euo pipefail

LOG_PREFIX="[sift-setup]"
say() { echo "${LOG_PREFIX} $*"; }
die() {
	echo "${LOG_PREFIX} ERROR: $*" >&2
	exit 1
}

need_cmd() { command -v "$1" >/dev/null 2>&1; }

require_root() {
	if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
		die "Run as root (e.g., sudo $0)"
	fi
}

detect_pkg_mgr() {
	if need_cmd apt-get; then
		echo "apt"
	elif need_cmd dnf; then
		echo "dnf"
	elif need_cmd yum; then
		echo "yum"
	elif need_cmd pacman; then
		echo "pacman"
	else
		echo "unknown"
	fi
}

python_version_ok() {
	# Return 0 if python3 exists and version >= 3.11
	if ! need_cmd python3; then
		return 1
	fi

	python3 - <<'PY' >/dev/null 2>&1
import sys
ok = sys.version_info >= (3, 11)
raise SystemExit(0 if ok else 1)
PY
}

check_tomllib() {
	python3 - <<'PY' >/dev/null 2>&1
import tomllib  # py3.11+
PY
}

install_apt() {
	say "Using apt"
	export DEBIAN_FRONTEND=noninteractive

	say "Updating package indexes"
	apt-get update -y

	# Core runtime deps
	local pkgs=(
		ffmpeg
		python3
	)

	# Quality-of-life (safe to install even if not used)
	local extra=(
		python3-venv
		python3-pip
		jq
		ca-certificates
	)

	say "Installing required packages (idempotent)"
	apt-get install -y --no-install-recommends "${pkgs[@]}" "${extra[@]}"

	say "Done (apt)"
}

install_dnf() {
	say "Using dnf"
	dnf -y makecache

	# Fedora/RHEL-ish naming:
	# - ffmpeg may require RPM Fusion on Fedora; on RHEL it's often not in base repos.
	# We'll try, but if it fails we give a clear error.
	local pkgs=(
		ffmpeg
		python3
		python3-pip
		python3-virtualenv
		jq
		ca-certificates
	)

	say "Installing packages (idempotent)"
	if ! dnf -y install "${pkgs[@]}"; then
		die "dnf install failed. ffmpeg/ffprobe may not be available in your enabled repos.
Enable the appropriate repo (e.g., RPM Fusion on Fedora) and re-run."
	fi

	say "Done (dnf)"
}

install_yum() {
	say "Using yum"
	yum -y makecache fast || true

	local pkgs=(
		ffmpeg
		python3
		python3-pip
		jq
		ca-certificates
	)

	say "Installing packages (idempotent)"
	if ! yum -y install "${pkgs[@]}"; then
		die "yum install failed. ffmpeg/ffprobe may not be available in your enabled repos.
Enable the appropriate repo (EPEL/RPM Fusion equivalents) and re-run."
	fi

	say "Done (yum)"
}

install_pacman() {
	say "Using pacman"
	pacman -Sy --noconfirm

	local pkgs=(
		ffmpeg
		python
		python-pip
		jq
		ca-certificates
	)

	say "Installing packages (idempotent)"
	pacman -S --needed --noconfirm "${pkgs[@]}"

	say "Done (pacman)"
}

print_summary() {
	say "Verifying installs"

	need_cmd ffprobe || die "ffprobe not found after install"
	need_cmd python3 || die "python3 not found after install"

	say "ffprobe: $(ffprobe -version 2>/dev/null | head -n1 || true)"
	say "python3: $(python3 --version)"

	if python_version_ok; then
		say "Python version OK (>= 3.11)"
	else
		say "WARNING: Python is < 3.11. Your config TOML reader may not work (tomllib missing)."
		say "         Consider installing Python 3.11+ (or adjust the project to use a toml dependency)."
	fi

	if python_version_ok && check_tomllib; then
		say "tomllib import OK"
	else
		say "WARNING: tomllib not available. Use Python 3.11+ or add a TOML parser dependency."
	fi

	say "Setup complete."
}

main() {
	require_root

	local mgr
	mgr="$(detect_pkg_mgr)"
	case "$mgr" in
	apt) install_apt ;;
	dnf) install_dnf ;;
	yum) install_yum ;;
	pacman) install_pacman ;;
	*)
		die "Unsupported system: no known package manager found (apt/dnf/yum/pacman)."
		;;
	esac

	print_summary
}

main "$@"
