#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "FinderPath Linux uninstaller must be run on Linux." >&2
  exit 1
fi

APP_ID="io.github.bhino50.FinderPathLinux"

rm -f "${HOME}/.local/bin/finderpath-linux"
rm -f "${HOME}/.local/share/applications/${APP_ID}.desktop"
rm -f "${HOME}/.local/share/applications/${APP_ID}.Settings.desktop"
rm -f "${HOME}/.local/share/icons/hicolor/512x512/apps/${APP_ID}.png"
rm -rf "${HOME}/.local/share/nautilus/scripts/FinderPath"
rm -f "${HOME}/.local/share/kio/servicemenus/finderpath-linux.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "${HOME}/.local/share/applications" >/dev/null 2>&1 || true
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q "${HOME}/.local/share/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "Removed FinderPath Linux user install files."
