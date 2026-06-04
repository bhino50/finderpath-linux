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

rm -rf "$PACKAGE_DIR"
mkdir -p "$PACKAGE_DIR/assets" "$DIST_DIR"

install -m 755 "${ROOT_DIR}/finderpath_linux.py" "${PACKAGE_DIR}/finderpath_linux.py"
install -m 755 "${ROOT_DIR}/install.sh" "${PACKAGE_DIR}/install.sh"
install -m 755 "${ROOT_DIR}/uninstall.sh" "${PACKAGE_DIR}/uninstall.sh"
install -m 644 "${ROOT_DIR}/README.md" "${PACKAGE_DIR}/README.md"
install -m 644 "${ROOT_DIR}/CONTRIBUTING.md" "${PACKAGE_DIR}/CONTRIBUTING.md"
install -m 644 "${ROOT_DIR}/LICENSE" "${PACKAGE_DIR}/LICENSE"
install -m 644 "${ROOT_DIR}/assets/finderpath-linux-icon.png" "${PACKAGE_DIR}/assets/finderpath-linux-icon.png"

tar -C "$DIST_DIR" -czf "$TARBALL" "$PACKAGE_NAME"

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

echo "Created ${TARBALL}"
echo "Created ${INSTALLER}"
