#!/usr/bin/env bash
# BlazeCode uninstaller — removes the program only.
# Never deletes ~/.blazecode (config, sessions, history, skills).
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/thealokverse/blazecode/main/uninstall.sh | bash
#   ./uninstall.sh
set -euo pipefail

INSTALL_ROOT="${BLAZECODE_INSTALL_ROOT:-${HOME}/.local/share/blazecode}"
BIN_DIR="${BLAZECODE_BIN_DIR:-${HOME}/.local/bin}"
BIN_NAME="blazecode"
BIN_PATH="${BIN_DIR}/${BIN_NAME}"

say()  { printf '==> %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
err()  { printf 'error: %s\n' "$*" >&2; exit 1; }

say "BlazeCode uninstaller"

removed_any=0

if [[ -L "$BIN_PATH" || -f "$BIN_PATH" ]]; then
  # Only remove if it points at our install root (or is our name in BIN_DIR).
  if [[ -L "$BIN_PATH" ]]; then
    target="$(readlink "$BIN_PATH" || true)"
    case "$target" in
      "${INSTALL_ROOT}"/*|*/blazecode|blazecode)
        rm -f "$BIN_PATH"
        info "removed ${BIN_PATH}"
        removed_any=1
        ;;
      *)
        # Still remove if basename link in default location looks like ours.
        if [[ "$target" == *"/share/blazecode/"* ]]; then
          rm -f "$BIN_PATH"
          info "removed ${BIN_PATH}"
          removed_any=1
        else
          info "left ${BIN_PATH} in place (does not look like a BlazeCode install link)"
        fi
        ;;
    esac
  else
    # Regular file named blazecode in bin dir — only remove if it mentions blazecode package path.
    if grep -q 'blazecode' "$BIN_PATH" 2>/dev/null; then
      rm -f "$BIN_PATH"
      info "removed ${BIN_PATH}"
      removed_any=1
    else
      info "left ${BIN_PATH} in place (unrecognized file)"
    fi
  fi
else
  info "no ${BIN_PATH} found"
fi

if [[ -d "$INSTALL_ROOT" ]]; then
  rm -rf "$INSTALL_ROOT"
  info "removed ${INSTALL_ROOT}"
  removed_any=1
else
  info "no ${INSTALL_ROOT} found"
fi

# Clean temporary upgrade leftovers if present.
rm -rf "${INSTALL_ROOT}.old" "${INSTALL_ROOT}.new."* 2>/dev/null || true

if [[ -d "${HOME}/.blazecode" ]]; then
  info "preserved ${HOME}/.blazecode (config, sessions, history, skills)"
fi

if [[ "$removed_any" -eq 0 ]]; then
  say "Nothing to uninstall."
else
  say "BlazeCode removed."
fi

cat <<EOF

Configuration and sessions were not deleted.
To wipe user data as well (optional):

  rm -rf ~/.blazecode

EOF
