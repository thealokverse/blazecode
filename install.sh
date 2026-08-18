#!/usr/bin/env bash
#
# Blazecode installer.
#
# Installs into an isolated venv under ~/.local/share/blazecode and links the
# blazecode binary to ~/.local/bin. Re-run to update. Never touches ~/.blazecode.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/thealokverse/blazecode/main/install.sh | bash
#
#   # pin a version
#   curl -fsSL ... | bash -s -- --version v1.3.0
#   # or:
#   BLAZECODE_VERSION=1.3.0 curl -fsSL ... | bash
#
#   # custom locations
#   curl -fsSL ... | bash -s -- --bin-dir ~/.bin
#
#   # remove the program (keeps ~/.blazecode)
#   curl -fsSL ... | bash -s -- --uninstall
#
set -euo pipefail

REPO="${BLAZECODE_REPO:-thealokverse/blazecode}"
INSTALL_ROOT="${BLAZECODE_INSTALL_ROOT:-${HOME}/.local/share/blazecode}"
BIN_DIR_OVERRIDE="${BLAZECODE_BIN_DIR:-}"
VERSION="${BLAZECODE_VERSION:-}"
DO_UNINSTALL=0
BRANCH="${BLAZECODE_BRANCH:-main}"
TMPDIR_CLEANUP=""

cleanup() {
  if [ -n "${TMPDIR_CLEANUP}" ] && [ -d "${TMPDIR_CLEANUP}" ]; then
    rm -rf "${TMPDIR_CLEANUP}"
  fi
}
trap cleanup EXIT

log()  { printf '%s\n' "$*"; }
note() { printf '\033[36m=>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mwarn:\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --version)
      [ $# -ge 2 ] || die "--version needs a tag (e.g. v1.3.0)"
      VERSION="$2"; shift 2 ;;
    --bin-dir)
      [ $# -ge 2 ] || die "--bin-dir needs a path"
      BIN_DIR_OVERRIDE="$2"; shift 2 ;;
    --uninstall)
      DO_UNINSTALL=1; shift ;;
    --help|-h)
      log "Blazecode installer"
      log "  --version <tag>  Install a specific release tag (default: latest release, else main)"
      log "  --bin-dir <path> Install directory for the blazecode symlink"
      log "  --uninstall      Remove Blazecode (keeps ~/.blazecode)"
      exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

need_cmd() { command -v "$1" >/dev/null 2>&1; }

download() {
  local url="$1" dest="$2"
  if need_cmd curl; then
    curl -fsSL --retry 3 --retry-delay 1 -o "$dest" "$url"
  elif need_cmd wget; then
    wget -q -O "$dest" "$url"
  else
    die "curl or wget is required"
  fi
}

download_to_stdout() {
  local url="$1"
  if need_cmd curl; then
    curl -fsSL --retry 3 --retry-delay 1 "$url"
  elif need_cmd wget; then
    wget -q -O - "$url"
  else
    die "curl or wget is required"
  fi
}

choose_bindir() {
  if [ -n "$BIN_DIR_OVERRIDE" ]; then
    printf '%s\n' "$BIN_DIR_OVERRIDE"
    return
  fi
  local candidate="${HOME}/.local/bin"
  if { [ -d "$candidate" ] || mkdir -p "$candidate" 2>/dev/null; } && [ -w "$candidate" ]; then
    printf '%s\n' "$candidate"
    return
  fi
  printf '%s\n' "/usr/local/bin"
}

find_python() {
  local candidate
  for candidate in "${BLAZECODE_PYTHON:-}" python3.14 python3.13 python3.12 python3.11 python3; do
    [ -z "$candidate" ] && continue
    if need_cmd "$candidate"; then
      if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        command -v "$candidate"
        return 0
      fi
    fi
  done
  die "Python 3.11+ is required. Install it, then re-run this script."
}

resolve_version() {
  if [ -n "$VERSION" ]; then
    VERSION="${VERSION#v}"
    return
  fi
  local json tag
  if json="$(download_to_stdout "https://api.github.com/repos/${REPO}/releases/latest" 2>/dev/null)"; then
    tag="$(printf '%s' "$json" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
    if [ -n "$tag" ]; then
      VERSION="${tag#v}"
      return
    fi
  fi
  VERSION=""
}

path_contains() {
  case ":${PATH}:" in
    *":$1:"*) return 0 ;;
    *) return 1 ;;
  esac
}

place_file() {
  # place_file <src> <dest> — mv with optional sudo
  local src="$1" dest="$2" dir
  dir="$(dirname "$dest")"
  if [ ! -d "$dir" ]; then
    mkdir -p "$dir" 2>/dev/null || {
      warn "${dir} could not be created; trying sudo"
      sudo mkdir -p "$dir"
    }
  fi
  if [ -w "$dir" ]; then
    mv "$src" "$dest"
  else
    warn "${dir} is not writable; using sudo"
    sudo mv "$src" "$dest"
  fi
}

remove_path() {
  # remove_path <path> — rm with optional sudo
  local path="$1"
  if rm -rf "$path" 2>/dev/null; then
    return 0
  fi
  if need_cmd sudo; then
    sudo rm -rf "$path"
    return 0
  fi
  return 1
}

uninstall() {
  note "Uninstalling Blazecode"
  local bindir target removed=0
  bindir="$(choose_bindir)"
  target="${bindir}/blazecode"

  if [ -L "$target" ] || [ -f "$target" ]; then
    if [ -L "$target" ]; then
      local link
      link="$(readlink "$target" 2>/dev/null || true)"
      case "$link" in
        "${INSTALL_ROOT}"/*|*share/blazecode*)
          if remove_path "$target"; then
            log "  removed ${target}"
            removed=1
          fi
          ;;
        *)
          # Wrapper script we write also counts.
          if grep -q "local/share/blazecode\|BLAZECODE_ROOT\|-m blazecode" "$target" 2>/dev/null; then
            if remove_path "$target"; then
              log "  removed ${target}"
              removed=1
            fi
          else
            warn "left ${target} in place (does not look like a Blazecode install)"
          fi
          ;;
      esac
    elif grep -q "local/share/blazecode\|-m blazecode\|from blazecode" "$target" 2>/dev/null; then
      if remove_path "$target"; then
        log "  removed ${target}"
        removed=1
      fi
    else
      warn "left ${target} in place (unrecognized file)"
    fi
  else
    log "  no ${target} found"
  fi

  if [ -d "$INSTALL_ROOT" ]; then
    if remove_path "$INSTALL_ROOT"; then
      log "  removed ${INSTALL_ROOT}"
      removed=1
    fi
  else
    log "  no ${INSTALL_ROOT} found"
  fi
  remove_path "${INSTALL_ROOT}.old" 2>/dev/null || true

  if [ -d "${HOME}/.blazecode" ]; then
    log "  preserved ${HOME}/.blazecode (config, sessions, skills)"
  fi

  if [ "$removed" -eq 0 ]; then
    note "Nothing to uninstall."
  else
    note "Blazecode removed."
  fi
}

install_blazecode() {
  need_cmd uname
  need_cmd tar
  need_cmd mktemp
  need_cmd mkdir

  local python bindir
  python="$(find_python)"
  bindir="$(choose_bindir)"
  resolve_version

  note "Blazecode installer"
  log "  python:  ${python} ($("$python" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])'))"
  log "  prefix:  ${INSTALL_ROOT}"
  log "  bin-dir: ${bindir}"
  if [ -n "$VERSION" ]; then
    log "  version: v${VERSION}"
  else
    log "  version: ${BRANCH} (no release tag found)"
  fi

  local archive url src_dir launcher
  TMPDIR_CLEANUP="$(mktemp -d 2>/dev/null || mktemp -d -t blazecode)"

  if [ -n "$VERSION" ]; then
    archive="blazecode-${VERSION}.tar.gz"
    url="https://github.com/${REPO}/archive/refs/tags/v${VERSION}.tar.gz"
  else
    archive="blazecode-${BRANCH}.tar.gz"
    url="https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz"
  fi

  note "Downloading source"
  if ! download "$url" "${TMPDIR_CLEANUP}/${archive}"; then
    die "download failed: ${url}
Is the tag/branch published on GitHub?"
  fi

  note "Extracting"
  mkdir -p "${TMPDIR_CLEANUP}/src"
  tar -xzf "${TMPDIR_CLEANUP}/${archive}" -C "${TMPDIR_CLEANUP}/src"
  src_dir="$(find "${TMPDIR_CLEANUP}/src" -mindepth 1 -maxdepth 1 -type d | head -n1)"
  [ -n "$src_dir" ] && [ -f "${src_dir}/pyproject.toml" ] || die "unexpected archive layout"

  note "Creating virtualenv"
  mkdir -p "$(dirname "$INSTALL_ROOT")"
  # Keep previous install until the new one is ready, then swap.
  rm -rf "${INSTALL_ROOT}.old"
  if [ -d "$INSTALL_ROOT" ]; then
    mv "$INSTALL_ROOT" "${INSTALL_ROOT}.old"
  fi

  if ! "$python" -m venv "$INSTALL_ROOT"; then
    [ -d "${INSTALL_ROOT}.old" ] && mv "${INSTALL_ROOT}.old" "$INSTALL_ROOT"
    die "failed to create virtualenv at ${INSTALL_ROOT}"
  fi

  # Upgrade pip quietly; ignore failure on locked-down environments.
  "${INSTALL_ROOT}/bin/python" -m pip install --upgrade pip setuptools wheel -q || true

  note "Installing package"
  if ! "${INSTALL_ROOT}/bin/python" -m pip install --upgrade "${src_dir}" -q; then
    rm -rf "$INSTALL_ROOT"
    [ -d "${INSTALL_ROOT}.old" ] && mv "${INSTALL_ROOT}.old" "$INSTALL_ROOT"
    die "pip install failed"
  fi

  rm -rf "${INSTALL_ROOT}.old"

  if [ -n "$VERSION" ]; then
    printf '%s\n' "$VERSION" > "${INSTALL_ROOT}/VERSION"
  else
    printf '%s\n' "$BRANCH" > "${INSTALL_ROOT}/VERSION"
  fi

  [ -x "${INSTALL_ROOT}/bin/blazecode" ] || die "install succeeded but blazecode entrypoint is missing"

  # Portable launcher — always calls the venv python at the final install path.
  note "Linking ${bindir}/blazecode"
  launcher="${TMPDIR_CLEANUP}/blazecode"
  cat > "$launcher" <<EOF
#!/usr/bin/env bash
exec "${INSTALL_ROOT}/bin/python" -m blazecode "\$@"
EOF
  chmod 755 "$launcher"
  place_file "$launcher" "${bindir}/blazecode"

  note "Verifying"
  local reported
  if ! reported="$("${bindir}/blazecode" --version 2>&1)"; then
    die "blazecode --version failed after install:
${reported}"
  fi
  log "  ${reported}"

  if ! path_contains "$bindir"; then
    warn "${bindir} is not on your PATH"
    log "  Add this to your shell config (~/.bashrc, ~/.zshrc):"
    log "    export PATH=\"${bindir}:\$PATH\""
  fi

  log ""
  note "Done. Run: blazecode"
  log "  Binary: ${bindir}/blazecode"
  log "  Prefix: ${INSTALL_ROOT}"
  log "  Config: ~/.blazecode (never modified by this installer)"
  log ""
  log "  Update:    curl -fsSL https://raw.githubusercontent.com/${REPO}/main/install.sh | bash"
  log "  Uninstall: curl -fsSL https://raw.githubusercontent.com/${REPO}/main/install.sh | bash -s -- --uninstall"
}

if [ "$DO_UNINSTALL" -eq 1 ]; then
  uninstall
else
  install_blazecode
fi
