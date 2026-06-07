#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Options:
  -y, --yes       Install supported system dependencies without prompting.
  --install-deps  Install supported system dependencies when missing.
  --skip-deps     Do not try to install system dependencies.
  -h, --help      Show this help.
EOF
}

ASSUME_YES=0
INSTALL_DEPS_MODE="prompt"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yes)
      ASSUME_YES=1
      INSTALL_DEPS_MODE="yes"
      ;;
    --install-deps)
      INSTALL_DEPS_MODE="yes"
      ;;
    --skip-deps)
      INSTALL_DEPS_MODE="skip"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

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
SETTINGS_APP_ID="${APP_ID}.Settings"

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

sudo_cmd() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
    return
  fi

  if command_exists sudo; then
    sudo "$@"
    return
  fi

  echo "sudo is not available. Install dependencies manually, then rerun ./install.sh --skip-deps." >&2
  return 1
}

# Returns success only when we can actually install system packages:
# running as root, or sudo can escalate without a password, or sudo can
# prompt on an interactive terminal. This lets us skip the dependency
# bootstrap gracefully instead of aborting when escalation is impossible.
privilege_escalation_available() {
  if [[ "${EUID}" -eq 0 ]]; then
    return 0
  fi

  if ! command_exists sudo; then
    return 1
  fi

  if sudo -n true >/dev/null 2>&1; then
    return 0
  fi

  if [[ -t 0 ]]; then
    return 0
  fi

  return 1
}

python_import_works() {
  local script="$1"
  command_exists python3 && python3 - <<PY >/dev/null 2>&1
$script
PY
}

have_gtk() {
  python_import_works 'import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk'
}

have_appindicator() {
  python_import_works 'import gi
for namespace in ("AyatanaAppIndicator3", "AppIndicator3"):
    try:
        gi.require_version(namespace, "0.1")
        __import__("gi.repository", fromlist=[namespace])
        raise SystemExit(0)
    except Exception:
        pass
raise SystemExit(1)'
}

have_clipboard_helper() {
  command_exists wl-copy || command_exists xclip || command_exists xsel
}

have_terminal_launcher() {
  local candidate
  for candidate in ghostty x-terminal-emulator kgx gnome-terminal konsole xfce4-terminal mate-terminal tilix alacritty kitty wezterm xterm; do
    if command_exists "$candidate"; then
      return 0
    fi
  done
  return 1
}

needs_dependency_bootstrap() {
  command_exists python3 || return 0
  have_gtk || return 0
  have_appindicator || return 0
  have_clipboard_helper || return 0
  have_terminal_launcher || return 0
  return 1
}

print_missing_dependency_summary() {
  echo "Checking FinderPath Linux desktop dependencies..."
  command_exists python3 || echo "  missing: python3"
  have_gtk || echo "  missing: GTK Python bindings for settings"
  have_appindicator || echo "  missing: AppIndicator gir package for tray"
  have_clipboard_helper || echo "  missing: wl-copy, xclip, or xsel clipboard helper"
  have_terminal_launcher || echo "  missing: a known terminal launcher"
}

install_packages_one_by_one() {
  local manager="$1"
  shift
  local package
  for package in "$@"; do
    case "$manager" in
      apt)
        sudo_cmd apt-get install -y "$package" || true
        ;;
      dnf)
        sudo_cmd dnf install -y "$package" || true
        ;;
      pacman)
        sudo_cmd pacman -S --needed --noconfirm "$package" || true
        ;;
      zypper)
        sudo_cmd zypper --non-interactive install "$package" || true
        ;;
    esac
  done
}

install_supported_dependencies() {
  if command_exists apt-get; then
    sudo_cmd apt-get update || true
    sudo_cmd apt-get install -y python3 || true
    install_packages_one_by_one apt \
      python3-gi python3-pyatspi gir1.2-ayatanaappindicator3-0.1 gir1.2-appindicator3-0.1 \
      wl-clipboard xclip xsel xdotool xterm qdbus-qt5 openssh-client desktop-file-utils \
      hicolor-icon-theme libglib2.0-bin libnotify-bin
    return 0
  fi

  if command_exists dnf; then
    sudo_cmd dnf install -y python3 || true
    install_packages_one_by_one dnf \
      python3-gobject python3-pyatspi libayatana-appindicator-gtk3 libappindicator-gtk3 \
      wl-clipboard xclip xsel xdotool xterm qt5-qttools openssh-clients desktop-file-utils \
      hicolor-icon-theme gtk3 libnotify
    return 0
  fi

  if command_exists pacman; then
    sudo_cmd pacman -Sy --needed --noconfirm python || true
    install_packages_one_by_one pacman \
      python-gobject python-atspi libayatana-appindicator libappindicator-gtk3 \
      wl-clipboard xclip xsel xdotool xterm qt5-tools openssh desktop-file-utils \
      hicolor-icon-theme gtk3 libnotify
    return 0
  fi

  if command_exists zypper; then
    sudo_cmd zypper --non-interactive install python3 || true
    install_packages_one_by_one zypper \
      python3-gobject python3-pyatspi typelib-1_0-AyatanaAppIndicator3-0_1 \
      wl-clipboard xclip xsel xdotool xterm libqt5-qttools openssh-clients desktop-file-utils \
      hicolor-icon-theme gtk3-tools libnotify-tools
    return 0
  fi

  echo "No supported package manager found. Install the dependencies listed in README.md, then rerun ./install.sh --skip-deps." >&2
  return 1
}

confirm_dependency_install() {
  if [[ "$INSTALL_DEPS_MODE" == "yes" || "$ASSUME_YES" -eq 1 ]]; then
    return 0
  fi

  if [[ ! -t 0 ]]; then
    echo "Run ./install.sh --yes to bootstrap dependencies non-interactively, or ./install.sh --skip-deps for CLI-only install."
    return 1
  fi

  local reply
  read -r -p "Install supported desktop dependencies now? [Y/n] " reply
  case "${reply}" in
    n|N|no|NO|No)
      return 1
      ;;
    *)
      return 0
      ;;
  esac
}

maybe_install_dependencies() {
  if [[ "$INSTALL_DEPS_MODE" == "skip" ]]; then
    return 0
  fi

  if ! needs_dependency_bootstrap; then
    return 0
  fi

  print_missing_dependency_summary

  # Never let an inability to install system packages abort the core
  # install. If we cannot escalate privileges, skip the bootstrap with
  # actionable guidance and fall through to the CLI + desktop install.
  if ! privilege_escalation_available; then
    echo "Cannot install system packages automatically (need root or sudo)."
    echo "Continuing with the CLI-only install. To add tray/settings packages later:"
    echo "  - install the packages listed in README.md manually, then rerun ./install.sh --skip-deps, or"
    echo "  - rerun this installer as root or with passwordless sudo: ./install.sh --yes"
    return 0
  fi

  if confirm_dependency_install; then
    install_supported_dependencies || \
      echo "Some desktop dependencies could not be installed; continuing with the CLI install."
  else
    echo "Skipping dependency bootstrap. CLI actions still work when Python 3 is installed; tray/settings may need manual packages."
  fi

  return 0
}

# Bootstrap is best-effort: a dependency failure must never block the
# binary + desktop integration that follow.
maybe_install_dependencies || \
  echo "Dependency bootstrap incomplete; continuing with the core install." >&2

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
Actions=Settings;
StartupNotify=false

[Desktop Action Settings]
Name=Settings
Exec=${BIN} settings
Icon=${ICON_NAME}
EOF

cat > "${APP_DIR}/${SETTINGS_APP_ID}.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=FinderPath Linux Settings
Comment=Configure FinderPath Linux
Exec=${BIN} settings
Icon=${ICON_NAME}
Terminal=false
Categories=Utility;FileTools;
Keywords=path;folder;terminal;ssh;codex;claude;hermes;settings;preferences;
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
write_nautilus_script "Settings" settings

cat > "${KDE_SERVICE_DIR}/finderpath-linux.desktop" <<EOF
[Desktop Entry]
Type=Service
Name=FinderPath Linux
ServiceTypes=KonqPopupMenu/Plugin
MimeType=inode/directory;
Actions=CopyPath;CopyCd;OpenTerminal;OpenGhostty;OpenCmux;OpenCodex;OpenClaude;OpenHermes;Settings;
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

[Desktop Action Settings]
Name=FinderPath: Settings
Icon=${ICON_NAME}
Exec=${BIN} settings
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
echo "Installed settings launcher: ${APP_DIR}/${SETTINGS_APP_ID}.desktop"
echo "Installed Nautilus scripts under: ${NAUTILUS_DIR}"
echo "Installed Dolphin service menu: ${KDE_SERVICE_DIR}/finderpath-linux.desktop"
echo
if [[ ":${PATH}:" != *":${BIN_DIR}:"* ]]; then
  echo "Note: ${BIN_DIR} is not on PATH in this shell."
  echo "Desktop launchers are installed. For terminal use now, run:"
  echo "  export PATH=\"${BIN_DIR}:\$PATH\""
  echo
fi

if command_exists python3; then
  "${BIN}" --self-test
  echo
  "${BIN}" doctor --fix || true
fi

echo
echo "Start FinderPath Linux from your app launcher, or run:"
echo "  ${BIN} tray"
echo "  ${BIN} settings"
