#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "FinderPath Linux installer must be run on Linux." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$SCRIPT_DIR/finderpath_linux.py"

if [[ ! -f "$SOURCE" ]]; then
  echo "Missing finderpath_linux.py next to install.sh." >&2
  exit 1
fi

BIN_DIR="${HOME}/.local/bin"
APP_DIR="${HOME}/.local/share/applications"
NAUTILUS_DIR="${HOME}/.local/share/nautilus/scripts/FinderPath"
KDE_SERVICE_DIR="${HOME}/.local/share/kio/servicemenus"
BIN="${BIN_DIR}/finderpath-linux"

mkdir -p "$BIN_DIR" "$APP_DIR" "$NAUTILUS_DIR" "$KDE_SERVICE_DIR"
install -m 755 "$SOURCE" "$BIN"

cat > "${APP_DIR}/io.github.bhino50.FinderPathLinux.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=FinderPath Linux
Comment=Copy and open the current Linux file-manager path
Exec=${BIN} tray
Icon=folder
Terminal=false
Categories=Utility;FileTools;
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
ServiceTypes=KonqPopupMenu/Plugin
MimeType=inode/directory;
Actions=CopyPath;CopyCd;OpenTerminal;OpenGhostty;OpenCmux;OpenCodex;OpenClaude;OpenHermes;
X-KDE-Priority=TopLevel

[Desktop Action CopyPath]
Name=FinderPath: Copy Path
Icon=edit-copy
Exec=${BIN} copy --path %f

[Desktop Action CopyCd]
Name=FinderPath: Copy cd Command
Icon=utilities-terminal
Exec=${BIN} copy-cd --path %f

[Desktop Action OpenTerminal]
Name=FinderPath: Open in Terminal
Icon=utilities-terminal
Exec=${BIN} open-terminal --path %f

[Desktop Action OpenGhostty]
Name=FinderPath: Open in Ghostty
Icon=utilities-terminal
Exec=${BIN} open-ghostty --path %f

[Desktop Action OpenCmux]
Name=FinderPath: Open in cmux
Icon=utilities-terminal
Exec=${BIN} open-cmux --path %f

[Desktop Action OpenCodex]
Name=FinderPath: Open with Codex
Icon=utilities-terminal
Exec=${BIN} codex --path %f

[Desktop Action OpenClaude]
Name=FinderPath: Open with Claude
Icon=utilities-terminal
Exec=${BIN} claude --path %f

[Desktop Action OpenHermes]
Name=FinderPath: Open with Hermes
Icon=utilities-terminal
Exec=${BIN} hermes --path %f
EOF

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
fi

echo "Installed ${BIN}"
echo "Installed desktop launcher: ${APP_DIR}/io.github.bhino50.FinderPathLinux.desktop"
echo "Installed Nautilus scripts under: ${NAUTILUS_DIR}"
echo "Installed Dolphin service menu: ${KDE_SERVICE_DIR}/finderpath-linux.desktop"
echo
echo "Optional packages for the full desktop experience:"
echo "  Tray UI: python3-gi plus gir1.2-ayatanaappindicator3-0.1 or gir1.2-appindicator3-0.1"
echo "  Clipboard: wl-clipboard, xclip, or xsel"
echo "  Active-window detection: xdotool on X11, hyprctl on Hyprland, qdbus for Dolphin"
