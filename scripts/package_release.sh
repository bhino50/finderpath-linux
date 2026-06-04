#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"
VERSION="${VERSION:-$(git -C "$ROOT_DIR" describe --tags --always --dirty 2>/dev/null || date +%Y%m%d)}"
VERSION="${VERSION#v}"
PACKAGE_NAME="finderpath-linux-${VERSION}"
PACKAGE_DIR="${DIST_DIR}/${PACKAGE_NAME}"
TARBALL="${DIST_DIR}/${PACKAGE_NAME}.tar.gz"
INSTALLER="${DIST_DIR}/finderpath-linux-installer.sh"
VERSIONED_INSTALLER="${DIST_DIR}/${PACKAGE_NAME}-installer.sh"
CHECKSUMS="${DIST_DIR}/SHA256SUMS"

rm -rf "$PACKAGE_DIR" "$TARBALL" "$INSTALLER" "$VERSIONED_INSTALLER" "$CHECKSUMS"
mkdir -p "$PACKAGE_DIR/assets" "$DIST_DIR"

install -m 755 "${ROOT_DIR}/finderpath_linux.py" "${PACKAGE_DIR}/finderpath_linux.py"
install -m 755 "${ROOT_DIR}/install.sh" "${PACKAGE_DIR}/install.sh"
install -m 755 "${ROOT_DIR}/uninstall.sh" "${PACKAGE_DIR}/uninstall.sh"
install -m 644 "${ROOT_DIR}/README.md" "${PACKAGE_DIR}/README.md"
install -m 644 "${ROOT_DIR}/CONTRIBUTING.md" "${PACKAGE_DIR}/CONTRIBUTING.md"
install -m 644 "${ROOT_DIR}/LICENSE" "${PACKAGE_DIR}/LICENSE"
install -m 644 "${ROOT_DIR}/assets/finderpath-linux-icon.png" "${PACKAGE_DIR}/assets/finderpath-linux-icon.png"

# Strip macOS extended attributes (e.g. com.apple.provenance) so GNU tar on
# Linux does not emit "Ignoring unknown extended header keyword 'LIBARCHIVE.xattr...'"
# warnings every time a downloader extracts the bundle.
if command -v xattr >/dev/null 2>&1; then
  xattr -cr "$PACKAGE_DIR" >/dev/null 2>&1 || true
fi

# Use word-split string (not an array) so this stays safe under `set -u` on the
# bash 3.2 that ships with macOS, where an empty "${arr[@]}" is an unbound error.
TAR_FLAGS=""
if tar --no-mac-metadata --version >/dev/null 2>&1; then
  TAR_FLAGS="$TAR_FLAGS --no-mac-metadata"
fi
if tar --no-xattrs --version >/dev/null 2>&1; then
  TAR_FLAGS="$TAR_FLAGS --no-xattrs"
fi

COPYFILE_DISABLE=1 tar $TAR_FLAGS -C "$DIST_DIR" -czf "$TARBALL" "$PACKAGE_NAME"

cat > "$INSTALLER" <<'HEADER'
#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "FinderPath Linux installer must be run on Linux." >&2
  exit 1
fi

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

archive_line="$(awk '/^__FINDERPATH_LINUX_ARCHIVE_BELOW__$/ { print NR + 1; exit 0; }' "$0")"
if [[ -z "$archive_line" ]]; then
  echo "Installer archive marker is missing." >&2
  exit 1
fi

tail -n +"$archive_line" "$0" | base64 -d | tar -xz -C "$tmp_dir"
package_dir="$(find "$tmp_dir" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
exec "$package_dir/install.sh" "$@"

__FINDERPATH_LINUX_ARCHIVE_BELOW__
HEADER

base64 < "$TARBALL" >> "$INSTALLER"
printf '\n' >> "$INSTALLER"
chmod +x "$INSTALLER"
cp "$INSTALLER" "$VERSIONED_INSTALLER"

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1"
    return
  fi

  shasum -a 256 "$1"
}

(
  cd "$DIST_DIR"
  sha256_file "$(basename "$TARBALL")"
  sha256_file "$(basename "$INSTALLER")"
  sha256_file "$(basename "$VERSIONED_INSTALLER")"
) > "$CHECKSUMS"

echo "Created ${TARBALL}"
echo "Created ${INSTALLER}"
echo "Created ${VERSIONED_INSTALLER}"
echo "Created ${CHECKSUMS}"
