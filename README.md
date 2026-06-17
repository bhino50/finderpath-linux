# FinderPath Linux

FinderPath Linux is a Linux sibling of the macOS FinderPath app. It gives Linux file managers and tray workflows the same core path actions: print or copy the current folder path, copy a shell-safe `cd` command, open a terminal, open Ghostty or cmux, launch Codex/Claude/Hermes at that folder, and start SSH sessions.

The app is dependency-light by design. CLI and file-manager actions use only Python's standard library. The tray UI is optional and uses GTK/AppIndicator when those packages are installed.

## Features

- Detect a path from `--path`, file-manager script environment variables, GNOME Files/Nautilus accessibility breadcrumbs, Dolphin D-Bus, active terminal cwd, or the current working directory.
- Copy the raw path or a shell-safe `cd` command.
- Open the folder in a terminal, Ghostty, or cmux.
- Launch Codex, Claude, or Hermes in the detected folder.
- Open SSH sessions in a terminal.
- Configure the preferred terminal, `cd` quote style, and agent executables from a GTK settings window.
- Resolve the current open folder when tray actions are clicked, so folder changes do not require restarting the tray.
- Parse Tailscale status for the optional tray menu.
- Install Nautilus scripts and a Dolphin service menu.
- Install the same branded icon used by the macOS FinderPath app.

## Requirements

Required:

- Linux
- Python 3.10+

The installer can bootstrap the supported desktop packages on Debian/Ubuntu, Fedora, Arch, and openSUSE when run with `--yes` or when you accept the prompt.

Optional:

- Clipboard: `wl-clipboard`, `xclip`, or `xsel`
- Tray UI: `python3-gi` plus `gir1.2-ayatanaappindicator3-0.1` or `gir1.2-appindicator3-0.1`
- GNOME Files/Nautilus active-folder detection: `python3-pyatspi` (the installer also turns on the GNOME `toolkit-accessibility` setting it depends on)
- Active-window detection: `xdotool` on X11, `hyprctl` on Hyprland, `qdbus` for Dolphin
- Remote connections: `ssh`
- Tailscale menu data: `tailscale`

Optional package examples:

```bash
# Debian / Ubuntu
sudo apt update
sudo apt install python3 python3-gi python3-pyatspi gir1.2-ayatanaappindicator3-0.1 wl-clipboard xclip xdotool qdbus-qt5 openssh-client

# Fedora
sudo dnf install python3 python3-gobject python3-pyatspi libappindicator-gtk3 wl-clipboard xclip xdotool qt5-qttools openssh-clients

# Arch
sudo pacman -S python python-gobject python-atspi libappindicator-gtk3 wl-clipboard xclip xdotool qt5-tools openssh
```

You do not need every optional package for CLI-only use. For a plug-and-play desktop install, let `install.sh` install the recommended packages.

## Install

Recommended release install:

```bash
curl -fL -o finderpath-linux-installer.sh \
  https://github.com/bhino50/finderpath-linux/releases/latest/download/finderpath-linux-installer.sh
chmod +x finderpath-linux-installer.sh
./finderpath-linux-installer.sh --yes
```

The one-file installer unpacks the app, installs the user-level launchers, and bootstraps supported desktop dependencies. Omit `--yes` if you want to review the dependency prompt. Use `--skip-deps` for a CLI-only install or when you manage packages yourself.

Release downloads also include a version-pinned installer, a tarball, and `SHA256SUMS` checksums. For example:

```bash
curl -fL -O https://github.com/bhino50/finderpath-linux/releases/latest/download/finderpath-linux-installer.sh
curl -fL -O https://github.com/bhino50/finderpath-linux/releases/latest/download/SHA256SUMS
sha256sum -c SHA256SUMS --ignore-missing
```

Source checkout install:

```bash
git clone https://github.com/bhino50/finderpath-linux.git
cd finderpath-linux
./install.sh --yes
```

Or, from an existing checkout:

```bash
./install.sh --yes
```

This installs:

- `~/.local/bin/finderpath-linux`
- `~/.local/share/applications/io.github.bhino50.FinderPathLinux.desktop`
- `~/.local/share/applications/io.github.bhino50.FinderPathLinux.Settings.desktop`
- `~/.local/share/icons/hicolor/512x512/apps/io.github.bhino50.FinderPathLinux.png`
- Nautilus scripts under `~/.local/share/nautilus/scripts/FinderPath`
- Dolphin service menu at `~/.local/share/kio/servicemenus/finderpath-linux.desktop`
- Settings saved at `~/.config/finderpath-linux/config.json`

Make sure `~/.local/bin` is on your `PATH` if you want to run `finderpath-linux` directly.

After installing, log out and back in if your file manager does not immediately show the new scripts/service menu. Some desktops cache menu and icon state.

Verify the install:

```bash
finderpath-linux doctor
finderpath-linux path --path "$PWD" --source
finderpath-linux copy-cd --path "$PWD"
```

Start the optional tray app:

```bash
finderpath-linux tray
```

Open settings:

```bash
finderpath-linux settings
```

Settings are also available from the tray menu, the standalone "FinderPath Linux Settings" app launcher, the desktop launcher action, the Nautilus scripts menu, and the Dolphin service menu.

If the tray command says GTK/AppIndicator packages are missing, install the tray dependencies listed above or keep using the CLI/file-manager actions.

The tray and settings windows must be started from a graphical desktop session. A plain SSH shell without `DISPLAY` or `WAYLAND_DISPLAY` can still run the CLI and installer tests, but it cannot show desktop windows.

## Usage

```bash
./finderpath_linux.py path --source
./finderpath_linux.py copy --path ~/Projects
./finderpath_linux.py copy-cd --path ~/Projects
./finderpath_linux.py open-terminal --path ~/Projects
./finderpath_linux.py open-ghostty --path ~/Projects
./finderpath_linux.py open-cmux --path ~/Projects
./finderpath_linux.py codex --path ~/Projects
./finderpath_linux.py claude --path ~/Projects
./finderpath_linux.py hermes --path ~/Projects
./finderpath_linux.py connect myserver
./finderpath_linux.py tray
./finderpath_linux.py settings
```

After installation, use `finderpath-linux` instead of `./finderpath_linux.py`:

```bash
finderpath-linux open-terminal --path ~/Projects
finderpath-linux codex --path ~/Projects
finderpath-linux connect myserver
finderpath-linux settings
```

You can also set a preferred terminal:

```bash
FINDERPATH_TERMINAL=ghostty ./finderpath_linux.py open-terminal --path ~/Projects
./finderpath_linux.py codex --path ~/Projects --terminal konsole
```

## Path Detection

Linux desktops do not expose one shared Finder-like automation API. FinderPath Linux uses this order:

1. Explicit `--path`.
2. File-manager environment variables from Nautilus, Nemo, and Caja scripts.
3. `FINDERPATH_PATH`.
4. GNOME Files/Nautilus accessibility breadcrumbs when `python3-pyatspi` is installed.
5. Dolphin D-Bus when the active window is Dolphin.
6. Active-window process cwd through `/proc`.
7. Current working directory.

For reliable file-manager integration, prefer exact path handoff through `--path`, Nautilus/Nemo/Caja script variables, or Dolphin's `%f` service-menu placeholder.

The tray header refreshes while the tray is running, and tray actions resolve the current open folder when clicked.

GNOME exposes the Nautilus breadcrumb used by step 4 only when the `org.gnome.desktop.interface toolkit-accessibility` setting is on. The installer, `finderpath-linux doctor --fix`, and the tray enable it automatically. After it is first turned on, restart GNOME Files (`nautilus -q`) or log out and back in so already-open windows pick it up; otherwise detection falls back to your home folder.

## Validate

```bash
python3 -m py_compile finderpath_linux.py
python3 finderpath_linux.py --self-test
python3 finderpath_linux.py doctor
bash -n install.sh
bash -n uninstall.sh
bash -n scripts/package_release.sh
./scripts/package_release.sh
```

## Publish a Release

Releases are built by `.github/workflows/release.yml` from version tags.

1. Make sure `main` has the installer and docs changes you want to ship.
2. Create and push a version tag:

   ```bash
   VERSION=0.1.2
   git tag "v${VERSION}"
   git push origin "v${VERSION}"
   ```

3. The Release workflow validates the app, builds the installer assets, tests the self-extracting installer, and publishes a GitHub release.

Each release contains:

- `finderpath-linux-installer.sh`: stable installer name used by the latest-download URL.
- `finderpath-linux-<version>-installer.sh`: version-pinned installer.
- `finderpath-linux-<version>.tar.gz`: source bundle for manual inspection or offline install.
- `SHA256SUMS`: checksums for the installer and tarball assets.

You can also build the same assets locally:

```bash
VERSION=0.1.2 ./scripts/package_release.sh
ls -lh dist/
```

## Notes

- Clipboard actions require one of `wl-copy`, `xclip`, or `xsel`.
- The tray command exits with a clear error if GTK/AppIndicator packages or a graphical display session are missing.
- The settings command exits with a clear error if `python3-gi` or a graphical display session is missing.
- The launcher icon is installed from `assets/finderpath-linux-icon.png`, which matches the macOS FinderPath app icon.
- SSH rejects hosts that start with `-` to avoid option injection.
- This repo is Linux-only. The macOS Swift/AppKit app lives in the separate FinderPath macOS repository.

## Uninstall

```bash
./uninstall.sh
```

This removes the user-level executable, desktop launchers, icon, Nautilus scripts, and Dolphin service menu.

## License

MIT. See [LICENSE](LICENSE).
