# Contributing

Keep FinderPath Linux small, dependency-light, and reliable from file-manager hooks.

## Development Checks

Run these before submitting changes:

```bash
python3 -m py_compile finderpath_linux.py
python3 finderpath_linux.py --self-test
bash -n install.sh
bash -n uninstall.sh
```

If you change installer output, test with a temporary home directory:

```bash
tmp_home="$(mktemp -d)"
HOME="$tmp_home" ./install.sh
find "$tmp_home/.local" -maxdepth 5 -type f -print
test -f "$tmp_home/.local/share/icons/hicolor/512x512/apps/io.github.bhino50.FinderPathLinux.png"
rm -rf "$tmp_home"
```

## Code Style

- Keep CLI and file-manager actions on the Python standard library.
- Keep optional GTK/AppIndicator imports inside the tray code path.
- Prefer exact path handoff before adding active-window heuristics.
- Quote shell arguments with `shlex.quote`.
- Keep process launches argv-based where possible.

## Manual Testing

Test exact path detection first:

```bash
./finderpath_linux.py path --path "$PWD" --source
./finderpath_linux.py copy-cd --path "$PWD"
./finderpath_linux.py open-terminal --path "$PWD"
```

Then test the integration that changed: Nautilus scripts, Dolphin service menu, tray menu, terminal launchers, or Tailscale parsing.
