#!/usr/bin/env bash
# Build GitHub Release artifacts for BlazeCode.
# Produces platform-named tarballs (pure-Python relocatable bundles) + SHA256SUMS.
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
STAGE="${DIST}/stage"
BUNDLE_NAME="blazecode"
OUT_DIR="${DIST}/release"
PYTHON="${PYTHON:-python3}"

echo "==> Building BlazeCode v${VERSION}"
rm -rf "$DIST"
mkdir -p "$STAGE/$BUNDLE_NAME/bin" "$STAGE/$BUNDLE_NAME/lib/python" "$OUT_DIR"

if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "error: Python 3.11+ is required to build (found $($PYTHON --version 2>&1))" >&2
  exit 1
fi

echo "==> Building wheel"
"$PYTHON" -m pip install --upgrade pip build wheel -q
"$PYTHON" -m build --wheel --outdir "$DIST/wheels"

WHEEL="$(ls -1 "$DIST/wheels"/blazecode-*.whl | head -n1)"
if [[ -z "$WHEEL" || ! -f "$WHEEL" ]]; then
  echo "error: wheel was not produced" >&2
  exit 1
fi

echo "==> Assembling relocatable bundle from ${WHEEL##*/}"
"$PYTHON" -m pip install \
  --upgrade \
  --no-compile \
  --target "$STAGE/$BUNDLE_NAME/lib/python" \
  "$WHEEL" \
  "httpx>=0.27,<1" \
  "prompt-toolkit>=3.0.48,<4" \
  "rich>=13.9,<15" \
  "typer>=0.12,<1"

# Remove build junk from the target tree.
find "$STAGE/$BUNDLE_NAME/lib/python" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
find "$STAGE/$BUNDLE_NAME/lib/python" -type d -name '*.dist-info' -path '*/pip*' -exec rm -rf {} + 2>/dev/null || true
rm -rf "$STAGE/$BUNDLE_NAME/lib/python/bin" 2>/dev/null || true

cat > "$STAGE/$BUNDLE_NAME/bin/blazecode" <<'EOF'
#!/usr/bin/env python3
"""BlazeCode launcher — resolves the bundled library next to this script."""
from __future__ import annotations

import sys
from pathlib import Path

# Require Python 3.11+ at runtime (matches package metadata).
if sys.version_info < (3, 11):
    sys.stderr.write(
        f"BlazeCode requires Python 3.11+ (found {sys.version.split()[0]})\n"
    )
    sys.exit(1)

_ROOT = Path(__file__).resolve().parent.parent
_LIB = _ROOT / "lib" / "python"
if not _LIB.is_dir():
    sys.stderr.write(f"BlazeCode install is corrupt: missing {_LIB}\n")
    sys.exit(1)

sys.path.insert(0, str(_LIB))

from blazecode.cli import app  # noqa: E402

if __name__ == "__main__":
    app()
EOF
chmod 755 "$STAGE/$BUNDLE_NAME/bin/blazecode"

printf '%s\n' "$VERSION" > "$STAGE/$BUNDLE_NAME/VERSION"
cp "$ROOT/LICENSE" "$STAGE/$BUNDLE_NAME/LICENSE"
cp "$ROOT/README.md" "$STAGE/$BUNDLE_NAME/README.md"

# Platform matrix for GitHub Release asset names.
# Bundle content is pure Python; names let install.sh pick a stable URL per host.
PLATFORMS=(
  "linux-x86_64"
  "linux-arm64"
  "darwin-x86_64"
  "darwin-arm64"
)

echo "==> Creating release archives"
(
  cd "$STAGE"
  for platform in "${PLATFORMS[@]}"; do
    archive="blazecode-${VERSION}-${platform}.tar.gz"
    tar -czf "${OUT_DIR}/${archive}" "$BUNDLE_NAME"
    echo "    ${archive}"
  done
)

# Also ship the wheel, installer scripts, and a VERSION pin file.
cp "$WHEEL" "$OUT_DIR/"
printf '%s\n' "$VERSION" > "$OUT_DIR/VERSION"
cp "$ROOT/install.sh" "$OUT_DIR/install.sh"
cp "$ROOT/uninstall.sh" "$OUT_DIR/uninstall.sh"
cp "$ROOT/update.sh" "$OUT_DIR/update.sh"
chmod 755 "$OUT_DIR/install.sh" "$OUT_DIR/uninstall.sh" "$OUT_DIR/update.sh"

echo "==> Writing SHA256SUMS"
(
  cd "$OUT_DIR"
  # Hash release payloads only (not SHA256SUMS itself).
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum blazecode-*.tar.gz blazecode-*.whl install.sh uninstall.sh update.sh > SHA256SUMS
  else
    shasum -a 256 blazecode-*.tar.gz blazecode-*.whl install.sh uninstall.sh update.sh > SHA256SUMS
  fi
)

echo "==> Done"
echo "Artifacts in ${OUT_DIR}:"
ls -lh "$OUT_DIR"
