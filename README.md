# FinderPath Linux

FinderPath Linux is a Linux sibling of the macOS FinderPath app. It gives Linux file managers and tray workflows the same core path actions: print or copy the current folder path, copy a shell-safe `cd` command, open a terminal, open Ghostty or cmux, launch Codex/Claude/Hermes at that folder, and start SSH sessions.

The app is dependency-light by design. CLI and file-manager actions use only Python's standard library. The tray UI is optional and uses GTK/AppIndicator when those packages are installed.

## Features

- Detect a path from `--path`, file-manager script environment variables, Dolphin D-Bus, active terminal cwd, or the current working directory.
- Copy the raw path or a shell-safe `cd` command.
- Open the folder in a terminal, Ghostty, or cmux.
- Launch Codex, Claude, or Hermes in the detected folder.
- Open SSH sessions in a terminal.
- Parse Tailscale status for the optional tray menu.
- Install Nautilus scripts and a Dolphin service menu.

## Requirements

Required:

- Linux
- Python 3.10+

Optional:

- Clipboard: `wl-clipboard`, `xclip`, or `xsel`
- Tray UI: `python3-gi` plus `gir1.2-ayatanaappindicator3-0.1` or `gir1.2-appindicator3-0.1`
- Active-window detection: `xdotool` on X11, `hyprctl` on Hyprland, `qdbus` for Dolphin
- Remote connections: `ssh`
- Tailscale menu data: `tailscale`

## Install

From the repo root:

```bash
./install.sh
```

This installs:

- `~/.local/bin/finderpath-linux`
- `~/.local/share/applications/io.github.bhino50.FinderPathLinux.desktop`
- Nautilus scripts under `~/.local/share/nautilus/scripts/FinderPath`
- Dolphin service menu at `~/.local/share/kio/servicemenus/finderpath-linux.desktop`

Make sure `~/.local/bin` is on your `PATH` if you want to run `finderpath-linux` directly.

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
4. Dolphin D-Bus when the active window is Dolphin.
5. Active-window process cwd through `/proc`.
6. Current working directory.

For reliable file-manager integration, prefer exact path handoff through `--path`, Nautilus/Nemo/Caja script variables, or Dolphin's `%f` service-menu placeholder.

## Validate

```bash
python3 -m py_compile finderpath_linux.py
python3 finderpath_linux.py --self-test
bash -n install.sh
```

## Notes

- Clipboard actions require one of `wl-copy`, `xclip`, or `xsel`.
- The tray command exits with a clear error if GTK/AppIndicator packages are missing.
- SSH rejects hosts that start with `-` to avoid option injection.
- This repo is Linux-only. The macOS Swift/AppKit app lives in the separate FinderPath macOS repository.

## License

MIT. See [LICENSE](LICENSE).

