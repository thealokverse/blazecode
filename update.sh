#!/usr/bin/env bash
# BlazeCode updater — re-runs the installer (safe upgrade).
# Preserves ~/.blazecode configuration and sessions.
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/thealokverse/blazecode/main/update.sh | bash
#   BLAZECODE_VERSION=1.1.0 ./update.sh
set -euo pipefail

REPO="${BLAZECODE_REPO:-thealokverse/blazecode}"
INSTALL_ROOT="${BLAZECODE_INSTALL_ROOT:-${HOME}/.local/share/blazecode}"
BRANCH="${BLAZECODE_BRANCH:-main}"

say()  { printf '==> %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
err()  { printf 'error: %s\n' "$*" >&2; exit 1; }

say "BlazeCode updater"

if [[ -f "${INSTALL_ROOT}/VERSION" ]]; then
  info "current: v$(tr -d '[:space:]' < "${INSTALL_ROOT}/VERSION")"
else
  info "no existing install detected; performing a fresh install"
fi

# Prefer the install.sh shipped next to this script (repo / release checkout).
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd 2>/dev/null || true)"
if [[ -n "${SCRIPT_DIR}" && -f "${SCRIPT_DIR}/install.sh" ]]; then
  say "Running local install.sh"
  exec bash "${SCRIPT_DIR}/install.sh" "$@"
fi

need_curl() {
  command -v curl >/dev/null 2>&1 || err "curl is required"
}

need_curl
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

URL="https://raw.githubusercontent.com/${REPO}/${BRANCH}/install.sh"
say "Fetching ${URL}"
curl -fsSL "$URL" -o "$TMP"
bash "$TMP" "$@"
