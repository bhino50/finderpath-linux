#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "FinderPath Linux installer must be run on Linux." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$SCRIPT_DIR/finderpath_linux.py"
ICON_SOURCE="$SCRIPT_DIR/assets/finderpath-linux-icon.png"
APP_ID="io.github.bhino50.FinderPathLinux"

if [[ ! -f "$SOURCE" ]]; then
  echo "Missing finderpath_linux.py next to install.sh." >&2
  exit 1
fi

if [[ ! -f "$ICON_SOURCE" ]]; then
  echo "Missing assets/finderpath-linux-icon.png next to install.sh." >&2
  exit 1
fi

BIN_DIR="${HOME}/.local/bin"
APP_DIR="${HOME}/.local/share/applications"
ICON_DIR="${HOME}/.local/share/icons/hicolor/512x512/apps"
NAUTILUS_DIR="${HOME}/.local/share/nautilus/scripts/FinderPath"
KDE_SERVICE_DIR="${HOME}/.local/share/kio/servicemenus"
BIN="${BIN_DIR}/finderpath-linux"
ICON_NAME="${APP_ID}"
ICON_PATH="${ICON_DIR}/${ICON_NAME}.png"

mkdir -p "$BIN_DIR" "$APP_DIR" "$ICON_DIR" "$NAUTILUS_DIR" "$KDE_SERVICE_DIR"
install -m 755 "$SOURCE" "$BIN"
install -m 644 "$ICON_SOURCE" "$ICON_PATH"

cat > "${APP_DIR}/${APP_ID}.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=FinderPath Linux
Comment=Copy and open the current Linux file-manager path
Exec=${BIN} tray
Icon=${ICON_NAME}
Terminal=false
Categories=Utility;FileTools;
Keywords=path;folder;terminal;ssh;codex;claude;hermes;
StartupNotify=false
EOF

write_nautilus_script() {
  local name="$1"
  shift
  local target="${NAUTILUS_DIR}/${name}"
  {
    printf '%s\n' '#!/usr/bin/env sh'
    printf '%s\n' "exec \"${BIN}\" $*"
  } > "$target"
  chmod +x "$target"
}

write_nautilus_script "Copy Path" copy
write_nautilus_script "Copy cd Command" copy-cd
write_nautilus_script "Open in Terminal" open-terminal
write_nautilus_script "Open in Ghostty" open-ghostty
write_nautilus_script "Open in cmux" open-cmux
write_nautilus_script "Open with Codex" codex
write_nautilus_script "Open with Claude" claude
write_nautilus_script "Open with Hermes" hermes

cat > "${KDE_SERVICE_DIR}/finderpath-linux.desktop" <<EOF
[Desktop Entry]
Type=Service
Name=FinderPath Linux
ServiceTypes=KonqPopupMenu/Plugin
MimeType=inode/directory;
Actions=CopyPath;CopyCd;OpenTerminal;OpenGhostty;OpenCmux;OpenCodex;OpenClaude;OpenHermes;
X-KDE-Priority=TopLevel

[Desktop Action CopyPath]
Name=FinderPath: Copy Path
Icon=${ICON_NAME}
Exec=${BIN} copy --path %f

[Desktop Action CopyCd]
Name=FinderPath: Copy cd Command
Icon=${ICON_NAME}
Exec=${BIN} copy-cd --path %f

[Desktop Action OpenTerminal]
Name=FinderPath: Open in Terminal
Icon=${ICON_NAME}
Exec=${BIN} open-terminal --path %f

[Desktop Action OpenGhostty]
Name=FinderPath: Open in Ghostty
Icon=${ICON_NAME}
Exec=${BIN} open-ghostty --path %f

[Desktop Action OpenCmux]
Name=FinderPath: Open in cmux
Icon=${ICON_NAME}
Exec=${BIN} open-cmux --path %f

[Desktop Action OpenCodex]
Name=FinderPath: Open with Codex
Icon=${ICON_NAME}
Exec=${BIN} codex --path %f

[Desktop Action OpenClaude]
Name=FinderPath: Open with Claude
Icon=${ICON_NAME}
Exec=${BIN} claude --path %f

[Desktop Action OpenHermes]
Name=FinderPath: Open with Hermes
Icon=${ICON_NAME}
Exec=${BIN} hermes --path %f
EOF

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q "${HOME}/.local/share/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "Installed ${BIN}"
echo "Installed icon: ${ICON_PATH}"
echo "Installed desktop launcher: ${APP_DIR}/${APP_ID}.desktop"
echo "Installed Nautilus scripts under: ${NAUTILUS_DIR}"
echo "Installed Dolphin service menu: ${KDE_SERVICE_DIR}/finderpath-linux.desktop"
echo
echo "Optional packages for the full desktop experience:"
echo "  Tray UI: python3-gi plus gir1.2-ayatanaappindicator3-0.1 or gir1.2-appindicator3-0.1"
echo "  Clipboard: wl-clipboard, xclip, or xsel"
echo "  Active-window detection: xdotool on X11, hyprctl on Hyprland, qdbus for Dolphin"
