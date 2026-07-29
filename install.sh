#!/usr/bin/env bash
# BlazeCode installer — https://github.com/thealokverse/blazecode
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/thealokverse/blazecode/main/install.sh | bash
#   BLAZECODE_VERSION=1.1.0 ./install.sh
set -euo pipefail

REPO="${BLAZECODE_REPO:-thealokverse/blazecode}"
INSTALL_ROOT="${BLAZECODE_INSTALL_ROOT:-${HOME}/.local/share/blazecode}"
BIN_DIR="${BLAZECODE_BIN_DIR:-${HOME}/.local/bin}"
BIN_NAME="blazecode"
TMPDIR_CREATE="${TMPDIR:-/tmp}"
WORK_DIR=""

# Never touch user data under ~/.blazecode (config, sessions, history, skills).

say()  { printf '==> %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
err()  { printf 'error: %s\n' "$*" >&2; exit 1; }
warn() { printf 'warning: %s\n' "$*" >&2; }

cleanup() {
  if [[ -n "${WORK_DIR}" && -d "${WORK_DIR}" ]]; then
    rm -rf "${WORK_DIR}"
  fi
}
trap cleanup EXIT

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || err "'$1' is required but was not found"
}

detect_os() {
  local u
  u="$(uname -s | tr '[:upper:]' '[:lower:]')"
  case "$u" in
    linux*)  echo "linux" ;;
    darwin*) echo "darwin" ;;
    *) err "unsupported operating system: $(uname -s). Supported: Linux, macOS." ;;
  esac
}

detect_arch() {
  local m
  m="$(uname -m)"
  case "$m" in
    x86_64|amd64) echo "x86_64" ;;
    aarch64|arm64) echo "arm64" ;;
    armv7l|armv8l) err "32-bit ARM is not supported" ;;
    *) err "unsupported CPU architecture: $m" ;;
  esac
}

find_python() {
  local candidate
  for candidate in "${BLAZECODE_PYTHON:-}" python3.14 python3.13 python3.12 python3.11 python3; do
    [[ -z "$candidate" ]] && continue
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        command -v "$candidate"
        return 0
      fi
    fi
  done
  err "Python 3.11+ is required. Install it, then re-run this script."
}

latest_version() {
  if [[ -n "${BLAZECODE_VERSION:-}" ]]; then
    echo "${BLAZECODE_VERSION#v}"
    return 0
  fi
  # Local / mirror installs can pin via VERSION file next to assets.
  if [[ -n "${BLAZECODE_BASE_URL:-}" && "${BLAZECODE_BASE_URL}" == file://* ]]; then
    local vf="${BLAZECODE_BASE_URL#file://}/VERSION"
    if [[ -f "$vf" ]]; then
      tr -d '[:space:]' < "$vf"
      return 0
    fi
  fi
  need_cmd curl
  local json tag
  json="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest")" || \
    err "could not query GitHub releases for ${REPO}"
  tag="$(printf '%s' "$json" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
  [[ -n "$tag" ]] || err "no GitHub release found for ${REPO}. Publish a release first, or set BLAZECODE_VERSION."
  echo "${tag#v}"
}

download() {
  local url="$1" dest="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --retry 3 --retry-delay 1 -o "$dest" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O "$dest" "$url"
  else
    err "need curl or wget to download releases"
  fi
}

checksum_file() {
  local file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk 'NR==1 {print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk 'NR==1 {print $1}'
  else
    err "need sha256sum or shasum to verify downloads"
  fi
}

verify_checksum() {
  local archive="$1" sums="$2" name
  name="$(basename "$archive")"
  [[ -f "$sums" ]] || { warn "SHA256SUMS missing; skipping verification"; return 0; }
  local expected actual
  expected="$(awk -v f="$name" '$2 == f {print $1; exit}' "$sums")"
  if [[ -z "$expected" ]]; then
    # Some sum files use "./name"
    expected="$(awk -v f="$name" '$2 == "./"f || $2 ~ "/"f"$" {print $1; exit}' "$sums")"
  fi
  [[ -n "$expected" ]] || err "no checksum entry for ${name} in SHA256SUMS"
  actual="$(checksum_file "$archive")"
  [[ "$expected" == "$actual" ]] || err "checksum mismatch for ${name} (expected ${expected}, got ${actual})"
  info "checksum ok"
}

path_contains() {
  case ":${PATH}:" in
    *":$1:"*) return 0 ;;
    *) return 1 ;;
  esac
}

print_path_help() {
  local bin_dir="$1"
  cat <<EOF

${bin_dir} is not on your PATH. Add it by appending one of these to your shell rc file:

  # bash
  echo 'export PATH="${bin_dir}:\$PATH"' >> ~/.bashrc && source ~/.bashrc

  # zsh
  echo 'export PATH="${bin_dir}:\$PATH"' >> ~/.zshrc && source ~/.zshrc

  # fish
  mkdir -p ~/.config/fish && echo 'fish_add_path ${bin_dir}' >> ~/.config/fish/config.fish
EOF
}

main() {
  say "BlazeCode installer"
  need_cmd uname
  need_cmd tar
  need_cmd mktemp
  need_cmd mkdir
  need_cmd chmod

  local os arch version python
  os="$(detect_os)"
  arch="$(detect_arch)"
  python="$(find_python)"
  version="$(latest_version)"

  info "os=${os} arch=${arch}"
  info "python=${python} ($("$python" -c 'import sys; print("%d.%d.%d"%sys.version_info[:3])'))"
  info "version=${version}"
  info "install-root=${INSTALL_ROOT}"
  info "bin-dir=${BIN_DIR}"

  local asset="blazecode-${version}-${os}-${arch}.tar.gz"
  # BLAZECODE_BASE_URL overrides GitHub (file:// or https:// mirror / local dist).
  local base="${BLAZECODE_BASE_URL:-https://github.com/${REPO}/releases/download/v${version}}"
  base="${base%/}"
  WORK_DIR="$(mktemp -d "${TMPDIR_CREATE}/blazecode-install.XXXXXX")"

  say "Downloading ${asset}"
  if [[ "$base" == file://* ]]; then
    local src="${base#file://}/${asset}"
    [[ -f "$src" ]] || err "local asset not found: ${src}"
    cp "$src" "${WORK_DIR}/${asset}"
  else
    if ! download "${base}/${asset}" "${WORK_DIR}/${asset}"; then
      err "failed to download ${base}/${asset}
Publish release assets first, or set BLAZECODE_VERSION / BLAZECODE_BASE_URL."
    fi
  fi

  say "Downloading SHA256SUMS"
  local sums_ok=0
  if [[ "$base" == file://* ]]; then
    if [[ -f "${base#file://}/SHA256SUMS" ]]; then
      cp "${base#file://}/SHA256SUMS" "${WORK_DIR}/SHA256SUMS"
      sums_ok=1
    fi
  elif download "${base}/SHA256SUMS" "${WORK_DIR}/SHA256SUMS"; then
    sums_ok=1
  fi
  if [[ "$sums_ok" -eq 1 ]]; then
    say "Verifying archive"
    verify_checksum "${WORK_DIR}/${asset}" "${WORK_DIR}/SHA256SUMS"
  else
    warn "could not download SHA256SUMS; continuing without verification"
  fi

  say "Extracting"
  mkdir -p "${WORK_DIR}/extract"
  tar -xzf "${WORK_DIR}/${asset}" -C "${WORK_DIR}/extract"
  local extracted="${WORK_DIR}/extract/blazecode"
  [[ -d "$extracted" ]] || err "archive layout unexpected (missing blazecode/)"
  [[ -x "${extracted}/bin/blazecode" || -f "${extracted}/bin/blazecode" ]] || \
    err "archive missing bin/blazecode"
  chmod 755 "${extracted}/bin/blazecode"

  # Rewrite shebang to the discovered Python when possible (keeps env python3 as fallback).
  if head -n1 "${extracted}/bin/blazecode" | grep -q 'python'; then
    # Leave #!/usr/bin/env python3 — runtime find uses PATH. No change required.
    :
  fi

  say "Installing to ${INSTALL_ROOT}"
  mkdir -p "$(dirname "$INSTALL_ROOT")" "$BIN_DIR"
  local previous_version=""
  if [[ -f "${INSTALL_ROOT}/VERSION" ]]; then
    previous_version="$(tr -d '[:space:]' < "${INSTALL_ROOT}/VERSION" || true)"
    info "upgrading existing install${previous_version:+ (was v${previous_version})}"
  fi

  # Atomic-ish replace: stage then swap. Never touch ~/.blazecode.
  local staging="${INSTALL_ROOT}.new.$$"
  rm -rf "$staging"
  mkdir -p "$staging"
  # Copy tree
  if command -v cp >/dev/null 2>&1; then
    cp -a "$extracted"/. "$staging"/
  fi
  # Record install metadata
  printf '%s\n' "$version" > "${staging}/VERSION"
  printf '%s\n' "$os" > "${staging}/OS"
  printf '%s\n' "$arch" > "${staging}/ARCH"
  printf '%s\n' "$python" > "${staging}/PYTHON"

  rm -rf "${INSTALL_ROOT}.old"
  if [[ -d "$INSTALL_ROOT" ]]; then
    mv "$INSTALL_ROOT" "${INSTALL_ROOT}.old"
  fi
  mv "$staging" "$INSTALL_ROOT"
  rm -rf "${INSTALL_ROOT}.old"

  say "Linking ${BIN_DIR}/${BIN_NAME}"
  ln -sfn "${INSTALL_ROOT}/bin/blazecode" "${BIN_DIR}/${BIN_NAME}"
  chmod 755 "${INSTALL_ROOT}/bin/blazecode"

  # Ensure the linked binary is used for verification when possible.
  local verify_bin="${BIN_DIR}/${BIN_NAME}"
  if [[ ! -x "$verify_bin" ]]; then
    verify_bin="${INSTALL_ROOT}/bin/blazecode"
  fi

  say "Verifying installation"
  local reported
  if ! reported="$("$verify_bin" --version 2>&1)"; then
    err "blazecode --version failed after install:
${reported}"
  fi
  info "${reported}"

  if ! path_contains "$BIN_DIR"; then
    warn "${BIN_DIR} is not on PATH"
    print_path_help "$BIN_DIR"
  fi

  # Explicitly confirm user data was not modified.
  info "user config/sessions (~/.blazecode) were not modified"

  cat <<EOF

✓ BlazeCode v${version} installed

  Binary:  ${BIN_DIR}/${BIN_NAME}
  Prefix:  ${INSTALL_ROOT}

  Get started:
    blazecode
    blazecode --version
    blazecode -p "Explain this repository"

  Update:   curl -fsSL https://raw.githubusercontent.com/${REPO}/main/update.sh | bash
  Remove:   curl -fsSL https://raw.githubusercontent.com/${REPO}/main/uninstall.sh | bash
EOF
}

main "$@"
