#!/usr/bin/env bash
# Build release artifacts for BlazeCode (wheel + checksums).
# The curl installer installs from GitHub source tags; this script is for
# optional GitHub Release attachments and local packaging checks.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="${BLAZECODE_VERSION:-}"
if [[ -z "$VERSION" ]]; then
  VERSION="$(
    python3 - <<'PY'
from pathlib import Path
text = Path("pyproject.toml").read_text(encoding="utf-8")
for line in text.splitlines():
    if line.startswith("version"):
        print(line.split("=", 1)[1].strip().strip('"'))
        break
PY
  )"
fi
VERSION="${VERSION#v}"

DIST="${ROOT}/dist"
OUT_DIR="${DIST}/release"
PYTHON="${PYTHON:-python3}"

echo "==> Building BlazeCode v${VERSION}"
rm -rf "$DIST"
mkdir -p "$OUT_DIR"

if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "error: Python 3.11+ is required to build (found $($PYTHON --version 2>&1))" >&2
  exit 1
fi

echo "==> Building wheel"
"$PYTHON" -m pip install --upgrade pip build wheel -q
"$PYTHON" -m build --wheel --outdir "$OUT_DIR"

WHEEL="$(ls -1 "$OUT_DIR"/blazecode-*.whl | head -n1)"
if [[ -z "$WHEEL" || ! -f "$WHEEL" ]]; then
  echo "error: wheel was not produced" >&2
  exit 1
fi

printf '%s\n' "$VERSION" > "$OUT_DIR/VERSION"
cp "$ROOT/install.sh" "$OUT_DIR/install.sh"
chmod 755 "$OUT_DIR/install.sh"
cp "$ROOT/install.ps1" "$OUT_DIR/install.ps1"

echo "==> Writing SHA256SUMS"
(
  cd "$OUT_DIR"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum blazecode-*.whl install.sh install.ps1 > SHA256SUMS
  else
    shasum -a 256 blazecode-*.whl install.sh install.ps1 > SHA256SUMS
  fi
)

echo "==> Done"
echo "Artifacts in ${OUT_DIR}:"
ls -lh "$OUT_DIR"
