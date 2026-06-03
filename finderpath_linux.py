#!/usr/bin/env python3
"""FinderPath Linux.

A Linux sibling for the macOS FinderPath menu bar app. The core commands use
only the Python standard library so file-manager scripts and service menus can
run on minimal desktops. The optional tray UI uses GTK/AppIndicator when those
packages are installed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import unquote, urlparse


APP_ID = "io.github.bhino50.FinderPathLinux"
APP_NAME = "FinderPath Linux"
DEFAULT_AGENTS = {
    "codex": "codex",
    "claude": "claude",
    "hermes": "hermes",
}


@dataclass(frozen=True)
class PathResult:
    path: str
    source: str
    warning: str | None = None


@dataclass(frozen=True)
class TailscaleDevice:
    name: str
    address: str
    os_name: str
    online: bool

    @property
    def is_linux(self) -> bool:
        return self.os_name.lower() == "linux"


@dataclass(frozen=True)
class TailscaleStatus:
    backend: str
    self_address: str | None
    devices: tuple[TailscaleDevice, ...]

    @property
    def is_running(self) -> bool:
        return self.backend == "running"


TAILSCALE_UNAVAILABLE = TailscaleStatus("unavailable", None, ())


def run_text(args: Sequence[str], timeout: float = 2.5) -> str | None:
    try:
        completed = subprocess.run(
            list(args),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if completed.returncode != 0:
        return None

    output = completed.stdout.strip()
    return output or None


def parse_file_uri(value: str) -> str | None:
    parsed = urlparse(value)
    if parsed.scheme != "file":
        return None

    if parsed.netloc not in ("", "localhost"):
        return None

    return unquote(parsed.path)


def normalize_path(value: str) -> str | None:
    raw = value.strip()
    if not raw:
        return None

    parsed_file = parse_file_uri(raw)
    if parsed_file:
        raw = parsed_file

    try:
        candidate = Path(raw).expanduser()
    except (OSError, RuntimeError):
        return None

    if candidate.exists() and not candidate.is_dir():
        candidate = candidate.parent

    try:
        if candidate.exists():
            return str(candidate.resolve())
    except OSError:
        return None

    return str(candidate)


def first_nonempty_line(value: str) -> str | None:
    for line in value.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def path_from_file_manager_env(env: Mapping[str, str] | None = None) -> PathResult | None:
    current_env = env or os.environ
    selected_keys = (
        "NAUTILUS_SCRIPT_SELECTED_FILE_PATHS",
        "NEMO_SCRIPT_SELECTED_FILE_PATHS",
        "CAJA_SCRIPT_SELECTED_FILE_PATHS",
    )
    current_uri_keys = (
        "NAUTILUS_SCRIPT_CURRENT_URI",
        "NEMO_SCRIPT_CURRENT_URI",
        "CAJA_SCRIPT_CURRENT_URI",
    )

    for key in selected_keys:
        value = current_env.get(key)
        if not value:
            continue
        first = first_nonempty_line(value)
        if first:
            path = normalize_path(first)
            if path:
                return PathResult(path, key)

    for key in current_uri_keys:
        value = current_env.get(key)
        if not value:
            continue
        path = normalize_path(value)
        if path:
            return PathResult(path, key)

    env_path = current_env.get("FINDERPATH_PATH")
    if env_path:
        path = normalize_path(env_path)
        if path:
            return PathResult(path, "FINDERPATH_PATH")

    return None


def current_path(explicit_path: str | None = None, env: Mapping[str, str] | None = None) -> PathResult:
    if explicit_path:
        path = normalize_path(explicit_path)
        if path:
            return PathResult(path, "--path")

    from_env = path_from_file_manager_env(env)
    if from_env:
        return from_env

    dolphin_path = active_dolphin_path()
    if dolphin_path:
        return dolphin_path

    active_cwd = active_window_cwd()
    if active_cwd:
        return active_cwd

    return PathResult(str(Path.cwd()), "current working directory")


def active_window_pid() -> int | None:
    if shutil.which("xdotool"):
        output = run_text(["xdotool", "getactivewindow", "getwindowpid"])
        if output and output.isdigit():
            return int(output)

    if shutil.which("hyprctl"):
        output = run_text(["hyprctl", "activewindow", "-j"])
        if output:
            try:
                pid = json.loads(output).get("pid")
            except json.JSONDecodeError:
                pid = None
            if isinstance(pid, int) and pid > 0:
                return pid

    return None


def process_name(pid: int) -> str | None:
    comm = Path("/proc") / str(pid) / "comm"
    try:
        value = comm.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    return value or None


def active_dolphin_path() -> PathResult | None:
    pid = active_window_pid()
    if not pid:
        return None

    name = (process_name(pid) or "").lower()
    if "dolphin" not in name:
        return None

    path = dolphin_dbus_path(pid)
    if path:
        return PathResult(path, "Dolphin D-Bus")

    return None


def dolphin_dbus_path(pid: int) -> str | None:
    if not shutil.which("qdbus"):
        return None

    names: list[str] = [f"org.kde.dolphin-{pid}"]
    qdbus_names = run_text(["qdbus"], timeout=3)
    if qdbus_names:
        for line in qdbus_names.splitlines():
            name = line.strip()
            if name.startswith("org.kde.dolphin") and name not in names:
                names.append(name)

    object_paths: list[str] = [
        "/dolphin/Dolphin_1",
        "/dolphin/Dolphin_0",
        "/dolphin/MainWindow_1",
        "/dolphin/MainWindow_0",
    ]
    methods = (
        "org.kde.dolphin.MainWindow.activeViewUrl",
        "activeViewUrl",
        "currentUrl",
    )

    for name in names:
        listed_paths = run_text(["qdbus", name], timeout=2)
        if listed_paths:
            for line in listed_paths.splitlines():
                candidate = line.strip()
                if candidate.startswith("/dolphin/") and candidate not in object_paths:
                    object_paths.append(candidate)

        for object_path in object_paths:
            for method in methods:
                output = run_text(["qdbus", name, object_path, method], timeout=2)
                path = path_from_dbus_output(output or "")
                if path:
                    return path

    return None


def path_from_dbus_output(output: str) -> str | None:
    if not output:
        return None

    file_uri = re.search(r"file://[^\s'\"\)]+", output)
    if file_uri:
        return normalize_path(file_uri.group(0))

    for line in output.splitlines():
        path = normalize_path(line)
        if path and path.startswith("/"):
            return path

    return None


def active_window_cwd() -> PathResult | None:
    pid = active_window_pid()
    if not pid:
        return None

    cwd_link = Path("/proc") / str(pid) / "cwd"
    try:
        path = os.readlink(cwd_link)
    except OSError:
        return None

    normalized = normalize_path(path)
    if not normalized:
        return None

    source = process_name(pid) or f"pid {pid}"
    return PathResult(normalized, f"active-window cwd ({source})")


def cd_command(path: str, quote_style: str = "single") -> str:
    if quote_style == "double":
        escaped = (
            path.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("$", "\\$")
            .replace("`", "\\`")
        )
        return f'cd "{escaped}"'

    return f"cd {shlex.quote(path)}"


def copy_to_clipboard(text: str) -> str | None:
    commands: tuple[tuple[str, ...], ...] = (
        ("wl-copy",),
        ("xclip", "-selection", "clipboard"),
        ("xsel", "--clipboard", "--input"),
    )
    failures: list[str] = []

    for command in commands:
        if not shutil.which(command[0]):
            continue
        try:
            subprocess.run(
                list(command),
                input=text,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            return None
        except (OSError, subprocess.CalledProcessError) as error:
            failures.append(f"{command[0]}: {error}")

    if failures:
        return "Could not write to the clipboard. Tried " + "; ".join(failures)

    return "No clipboard helper found. Install wl-clipboard, xclip, or xsel."


def notify(summary: str, body: str = "") -> None:
    if not shutil.which("notify-send"):
        return

    subprocess.Popen(
        ["notify-send", summary, body],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def executable_for(command: str) -> str | None:
    if os.path.isabs(command) and os.access(command, os.X_OK):
        return command

    return shutil.which(command)


def terminal_executable(preferred: str | None = None) -> str | None:
    candidates: list[str] = []
    for value in (preferred, os.environ.get("FINDERPATH_TERMINAL")):
        if value:
            candidates.append(value)

    candidates.extend(
        [
            "ghostty",
            "x-terminal-emulator",
            "kgx",
            "gnome-terminal",
            "konsole",
            "xfce4-terminal",
            "mate-terminal",
            "tilix",
            "alacritty",
            "kitty",
            "wezterm",
            "xterm",
        ]
    )

    for candidate in candidates:
        resolved = executable_for(candidate)
        if resolved:
            return resolved

    return None


def terminal_kind(executable: str) -> str:
    return Path(executable).name.lower()


def terminal_args_for_directory(executable: str, path: str) -> tuple[list[str], str | None]:
    kind = terminal_kind(executable)
    if kind == "ghostty":
        return [executable, f"--working-directory={path}"], None
    if kind in {"gnome-terminal", "kgx", "tilix", "terminator"}:
        return [executable, f"--working-directory={path}"], None
    if kind == "konsole":
        return [executable, "--workdir", path], None
    if kind in {"xfce4-terminal", "mate-terminal"}:
        return [executable, f"--working-directory={path}"], None
    if kind == "alacritty":
        return [executable, "--working-directory", path], None
    if kind == "kitty":
        return [executable, "--directory", path], None
    if kind == "wezterm":
        return [executable, "start", "--cwd", path], None

    return [executable], path


def terminal_args_for_shell(executable: str, path: str, command: str) -> tuple[list[str], str | None]:
    kind = terminal_kind(executable)
    shell = os.environ.get("SHELL", "/bin/sh")

    if kind == "ghostty":
        return [executable, f"--working-directory={path}", "-e", shell, "-lc", command], None
    if kind in {"gnome-terminal", "kgx"}:
        return [executable, f"--working-directory={path}", "--", shell, "-lc", command], None
    if kind == "konsole":
        return [executable, "--workdir", path, "-e", shell, "-lc", command], None
    if kind in {"xfce4-terminal", "mate-terminal"}:
        return [executable, f"--working-directory={path}", "-x", shell, "-lc", command], None
    if kind == "tilix":
        return [executable, f"--working-directory={path}", "-e", shell, "-lc", command], None
    if kind == "alacritty":
        return [executable, "--working-directory", path, "-e", shell, "-lc", command], None
    if kind == "kitty":
        return [executable, "--directory", path, shell, "-lc", command], None
    if kind == "wezterm":
        return [executable, "start", "--cwd", path, "--", shell, "-lc", command], None
    if kind in {"xterm", "x-terminal-emulator"}:
        return [executable, "-e", shell, "-lc", command], path

    return [executable, "-e", shell, "-lc", command], path


def launch(args: Sequence[str], cwd: str | None = None) -> str | None:
    try:
        subprocess.Popen(
            list(args),
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        return str(error)

    return None


def open_terminal_at(path: str, preferred_terminal: str | None = None) -> str | None:
    terminal = terminal_executable(preferred_terminal)
    if not terminal:
        return "No terminal emulator found. Install Ghostty, GNOME Terminal, Konsole, xterm, or set FINDERPATH_TERMINAL."

    args, cwd = terminal_args_for_directory(terminal, path)
    return launch(args, cwd=cwd)


def run_shell_in_terminal(path: str, command: str, preferred_terminal: str | None = None) -> str | None:
    terminal = terminal_executable(preferred_terminal)
    if not terminal:
        return "No terminal emulator found. Install one or set FINDERPATH_TERMINAL."

    args, cwd = terminal_args_for_shell(terminal, path, command)
    return launch(args, cwd=cwd)


def open_ghostty_at(path: str) -> str | None:
    ghostty = executable_for("ghostty")
    if not ghostty:
        return "Ghostty was not found on PATH."

    return launch([ghostty, f"--working-directory={path}"])


def open_cmux_at(path: str) -> str | None:
    cmux = executable_for("cmux")
    if not cmux:
        return "cmux was not found on PATH."

    return launch([cmux, path])


def open_agent(agent: str, executable: str, path: str, preferred_terminal: str | None = None) -> str | None:
    display_name = agent.capitalize()
    executable_argument = shlex.quote(executable)
    missing = f"{display_name} CLI was not found. Install it or add {executable} to PATH."
    command = (
        "clear; "
        f"cd {shlex.quote(path)} && "
        f"if command -v -- {executable_argument} >/dev/null 2>&1; then "
        f"exec {executable_argument}; "
        f"else printf '%s\\n' {shlex.quote(missing)}; "
        'exec "${SHELL:-/bin/sh}" -l; fi'
    )

    return run_shell_in_terminal(path, command, preferred_terminal)


def open_ssh(host: str, preferred_terminal: str | None = None) -> str | None:
    target = host.strip()
    if not target:
        return "No SSH host was provided."
    if target.startswith("-"):
        return "Refusing to connect to a host that starts with '-' (possible SSH flag injection)."

    command = f"exec ssh -- {shlex.quote(target)}"
    return run_shell_in_terminal(str(Path.home()), command, preferred_terminal)


def tailscale_status() -> TailscaleStatus:
    tailscale = executable_for("tailscale")
    if not tailscale:
        return TAILSCALE_UNAVAILABLE

    output = run_text([tailscale, "status", "--json"], timeout=5)
    if not output:
        return TAILSCALE_UNAVAILABLE

    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return TAILSCALE_UNAVAILABLE

    backend_map = {
        "Running": "running",
        "NeedsLogin": "needs-login",
        "NoState": "needs-login",
    }
    backend = backend_map.get(payload.get("BackendState"), "stopped")
    self_node = payload.get("Self") if isinstance(payload.get("Self"), dict) else {}
    self_ips = self_node.get("TailscaleIPs") if isinstance(self_node, dict) else None
    self_address = self_ips[0] if isinstance(self_ips, list) and self_ips else None

    devices: list[TailscaleDevice] = []
    peers = payload.get("Peer")
    if isinstance(peers, dict):
        for peer in peers.values():
            if not isinstance(peer, dict):
                continue
            dns_name = peer.get("DNSName")
            short_name = str(dns_name).split(".", 1)[0] if dns_name else None
            host_name = peer.get("HostName")
            ips = peer.get("TailscaleIPs")
            devices.append(
                TailscaleDevice(
                    name=short_name or str(host_name or "unknown"),
                    address=ips[0] if isinstance(ips, list) and ips else "",
                    os_name=str(peer.get("OS") or ""),
                    online=bool(peer.get("Online")),
                )
            )

    devices.sort(key=lambda device: (not device.online, device.name.lower()))
    return TailscaleStatus(backend, self_address, tuple(devices))


def action_copy_path(args: argparse.Namespace) -> int:
    result = current_path(args.path)
    error = copy_to_clipboard(result.path)
    if error:
        print(error, file=sys.stderr)
        notify(APP_NAME, error)
        return 1

    print(result.path)
    notify(APP_NAME, f"Copied path from {result.source}")
    return 0


def action_copy_cd(args: argparse.Namespace) -> int:
    result = current_path(args.path)
    command = cd_command(result.path, args.quote_style)
    error = copy_to_clipboard(command)
    if error:
        print(error, file=sys.stderr)
        notify(APP_NAME, error)
        return 1

    print(command)
    notify(APP_NAME, f"Copied cd command from {result.source}")
    return 0


def action_open_terminal(args: argparse.Namespace) -> int:
    result = current_path(args.path)
    error = open_terminal_at(result.path, args.terminal)
    if error:
        print(error, file=sys.stderr)
        notify(APP_NAME, error)
        return 1

    return 0


def action_open_ghostty(args: argparse.Namespace) -> int:
    result = current_path(args.path)
    error = open_ghostty_at(result.path)
    if error:
        print(error, file=sys.stderr)
        notify(APP_NAME, error)
        return 1

    return 0


def action_open_cmux(args: argparse.Namespace) -> int:
    result = current_path(args.path)
    error = open_cmux_at(result.path)
    if error:
        print(error, file=sys.stderr)
        notify(APP_NAME, error)
        return 1

    return 0


def action_open_agent(args: argparse.Namespace) -> int:
    agent = args.agent
    executable = args.executable or DEFAULT_AGENTS[agent]
    result = current_path(args.path)
    error = open_agent(agent, executable, result.path, args.terminal)
    if error:
        print(error, file=sys.stderr)
        notify(APP_NAME, error)
        return 1

    return 0


def action_connect(args: argparse.Namespace) -> int:
    error = open_ssh(args.host, args.terminal)
    if error:
        print(error, file=sys.stderr)
        notify(APP_NAME, error)
        return 1

    return 0


class TrayApp:
    def __init__(self, preferred_terminal: str | None = None) -> None:
        if not has_graphical_display():
            raise RuntimeError(
                "No graphical display session found. Start FinderPath Linux from your desktop session "
                "or set DISPLAY/WAYLAND_DISPLAY before running the tray."
            )

        try:
            import gi  # type: ignore
        except ImportError as error:
            raise RuntimeError(
                "GTK tray support is not installed. Install python3-gi and an AppIndicator gir package."
            ) from error

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk  # type: ignore

        try:
            gi.require_version("AyatanaAppIndicator3", "0.1")
            from gi.repository import AyatanaAppIndicator3 as AppIndicator3  # type: ignore
        except (ImportError, ValueError):
            gi.require_version("AppIndicator3", "0.1")
            from gi.repository import AppIndicator3  # type: ignore

        self.Gtk = Gtk
        self.AppIndicator3 = AppIndicator3
        self.preferred_terminal = preferred_terminal
        self.indicator = AppIndicator3.Indicator.new(
            APP_ID,
            APP_ID,
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

    def run(self) -> int:
        self.rebuild_menu()
        self.Gtk.main()
        return 0

    def rebuild_menu(self) -> None:
        Gtk = self.Gtk
        menu = Gtk.Menu()
        path_result = current_path()

        header = Gtk.MenuItem(label=f"{path_result.path}")
        header.set_sensitive(False)
        menu.append(header)
        source = Gtk.MenuItem(label=f"Source: {path_result.source}")
        source.set_sensitive(False)
        menu.append(source)
        menu.append(Gtk.SeparatorMenuItem())

        self.append_item(menu, "Refresh", self.rebuild_menu)
        self.append_item(menu, "Copy Path", lambda: self.copy_path(path_result.path))
        self.append_item(menu, "Copy cd Command", lambda: self.copy_cd(path_result.path))
        menu.append(Gtk.SeparatorMenuItem())

        self.append_item(menu, "Open in Terminal", lambda: self.run_action(open_terminal_at(path_result.path, self.preferred_terminal)))
        self.append_item(menu, "Open in Ghostty", lambda: self.run_action(open_ghostty_at(path_result.path)), executable="ghostty")
        self.append_item(menu, "Open in cmux", lambda: self.run_action(open_cmux_at(path_result.path)), executable="cmux")
        menu.append(Gtk.SeparatorMenuItem())

        for agent, executable in DEFAULT_AGENTS.items():
            label = f"Open with {agent.capitalize()}"
            self.append_item(
                menu,
                label,
                lambda agent=agent, executable=executable: self.run_action(
                    open_agent(agent, executable, path_result.path, self.preferred_terminal)
                ),
                executable=executable,
            )

        menu.append(Gtk.SeparatorMenuItem())
        self.append_tailscale_menu(menu)
        menu.append(Gtk.SeparatorMenuItem())
        self.append_item(menu, "Quit", Gtk.main_quit)

        menu.show_all()
        self.indicator.set_menu(menu)

    def append_item(
        self,
        menu: object,
        label: str,
        callback: Callable[[], None],
        executable: str | None = None,
    ) -> None:
        Gtk = self.Gtk
        item = Gtk.MenuItem(label=label)
        if executable and not executable_for(executable):
            item.set_label(f"{label} (not installed)")
            item.set_sensitive(False)
        else:
            item.connect("activate", lambda _item: callback())
        menu.append(item)

    def append_tailscale_menu(self, menu: object) -> None:
        Gtk = self.Gtk
        status = tailscale_status()
        submenu_root = Gtk.MenuItem(label="Connect to Tailscale Server")
        submenu = Gtk.Menu()

        if status.backend == "unavailable":
            item = Gtk.MenuItem(label="Tailscale CLI not found")
            item.set_sensitive(False)
            submenu.append(item)
        elif not status.devices:
            item = Gtk.MenuItem(label="No Tailscale devices found")
            item.set_sensitive(False)
            submenu.append(item)
        else:
            for device in status.devices:
                if not device.address:
                    continue
                label = f"{device.name} ({device.os_name})"
                item = Gtk.MenuItem(label=label)
                item.connect("activate", lambda _item, name=device.name: self.run_action(open_ssh(name, self.preferred_terminal)))
                submenu.append(item)

        submenu_root.set_submenu(submenu)
        menu.append(submenu_root)

    def copy_path(self, path: str) -> None:
        error = copy_to_clipboard(path)
        self.run_action(error)
        if not error:
            notify(APP_NAME, "Copied path")

    def copy_cd(self, path: str) -> None:
        error = copy_to_clipboard(cd_command(path))
        self.run_action(error)
        if not error:
            notify(APP_NAME, "Copied cd command")

    def run_action(self, error: str | None) -> None:
        if error:
            notify(APP_NAME, error)
            print(error, file=sys.stderr)


def action_tray(args: argparse.Namespace) -> int:
    try:
        return TrayApp(args.terminal).run()
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1


def has_graphical_display(env: Mapping[str, str] | None = None) -> bool:
    current_env = env or os.environ
    return bool(current_env.get("DISPLAY") or current_env.get("WAYLAND_DISPLAY"))


def run_self_test() -> int:
    assert parse_file_uri("file:///tmp/hello%20there") == "/tmp/hello there"
    assert parse_file_uri("https://example.com/nope") is None
    assert cd_command("/tmp/it's ok") == "cd '/tmp/it'\"'\"'s ok'"
    assert cd_command('/tmp/a"$b', "double") == 'cd "/tmp/a\\"\\$b"'
    assert path_from_dbus_output("file:///tmp/example") == "/tmp/example"
    assert has_graphical_display({"DISPLAY": ":0"})
    assert has_graphical_display({"WAYLAND_DISPLAY": "wayland-0"})
    assert not has_graphical_display({})

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        file_path = folder / "file.txt"
        file_path.write_text("ok", encoding="utf-8")
        resolved_folder = str(folder.resolve())
        assert current_path(str(folder)).path == resolved_folder
        assert current_path(str(file_path)).path == resolved_folder
        env = {"NAUTILUS_SCRIPT_SELECTED_FILE_PATHS": f"{file_path}\n"}
        assert path_from_file_manager_env(env).path == resolved_folder  # type: ignore[union-attr]

    print("finderpath-linux self-test passed")
    return 0


def add_path_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--path", help="Directory or file path to use instead of auto-detection.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FinderPath actions for Linux desktops.")
    parser.add_argument("--self-test", action="store_true", help="Run built-in validation checks.")
    subparsers = parser.add_subparsers(dest="command")

    path_parser = subparsers.add_parser("path", help="Print the detected path.")
    add_path_argument(path_parser)
    path_parser.add_argument("--source", action="store_true", help="Also print the path source.")

    copy_parser = subparsers.add_parser("copy", help="Copy the detected path.")
    add_path_argument(copy_parser)

    copy_cd_parser = subparsers.add_parser("copy-cd", help="Copy a shell-safe cd command.")
    add_path_argument(copy_cd_parser)
    copy_cd_parser.add_argument("--quote-style", choices=("single", "double"), default="single")

    terminal_parser = subparsers.add_parser("open-terminal", help="Open a terminal at the detected path.")
    add_path_argument(terminal_parser)
    terminal_parser.add_argument("--terminal", help="Preferred terminal executable.")

    ghostty_parser = subparsers.add_parser("open-ghostty", help="Open Ghostty at the detected path.")
    add_path_argument(ghostty_parser)

    cmux_parser = subparsers.add_parser("open-cmux", help="Open cmux at the detected path.")
    add_path_argument(cmux_parser)

    agent_parser = subparsers.add_parser("open-agent", help="Open a CLI agent at the detected path.")
    add_path_argument(agent_parser)
    agent_parser.add_argument("agent", choices=tuple(DEFAULT_AGENTS))
    agent_parser.add_argument("--executable", help="Agent executable override.")
    agent_parser.add_argument("--terminal", help="Preferred terminal executable.")

    for agent in DEFAULT_AGENTS:
        agent_short = subparsers.add_parser(agent, help=f"Open {agent.capitalize()} at the detected path.")
        add_path_argument(agent_short)
        agent_short.add_argument("--executable", help="Agent executable override.")
        agent_short.add_argument("--terminal", help="Preferred terminal executable.")

    connect_parser = subparsers.add_parser("connect", help="Open ssh to a host in a terminal.")
    connect_parser.add_argument("host")
    connect_parser.add_argument("--terminal", help="Preferred terminal executable.")

    tray_parser = subparsers.add_parser("tray", help="Run the optional GTK/AppIndicator tray app.")
    tray_parser.add_argument("--terminal", help="Preferred terminal executable.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    command = args.command
    if command is None:
        command = "tray" if (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")) else "path"

    if command == "path":
        result = current_path(args.path)
        print(result.path)
        if args.source:
            print(result.source)
        return 0
    if command == "copy":
        return action_copy_path(args)
    if command == "copy-cd":
        return action_copy_cd(args)
    if command == "open-terminal":
        return action_open_terminal(args)
    if command == "open-ghostty":
        return action_open_ghostty(args)
    if command == "open-cmux":
        return action_open_cmux(args)
    if command == "open-agent":
        return action_open_agent(args)
    if command in DEFAULT_AGENTS:
        args.agent = command
        return action_open_agent(args)
    if command == "connect":
        return action_connect(args)
    if command == "tray":
        return action_tray(args)

    parser.error(f"unknown command: {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
