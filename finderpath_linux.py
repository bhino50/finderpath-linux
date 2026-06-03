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
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import unquote, urlparse


APP_ID = "io.github.bhino50.FinderPathLinux"
APP_NAME = "FinderPath Linux"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "finderpath-linux"
CONFIG_PATH = CONFIG_DIR / "config.json"
DEFAULT_AGENTS = {
    "codex": "codex",
    "claude": "claude",
    "hermes": "hermes",
}
DEFAULT_CONFIG = {
    "terminal": "",
    "cd_quote_style": "single",
    "codex_executable": "codex",
    "claude_executable": "claude",
    "hermes_executable": "hermes",
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


def load_config() -> dict[str, str]:
    config = dict(DEFAULT_CONFIG)
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return config

    if not isinstance(payload, dict):
        return config

    for key, default in DEFAULT_CONFIG.items():
        value = payload.get(key)
        if isinstance(value, str):
            config[key] = value.strip()
        else:
            config[key] = default

    if config["cd_quote_style"] not in {"single", "double"}:
        config["cd_quote_style"] = DEFAULT_CONFIG["cd_quote_style"]

    return config


def save_config(config: Mapping[str, str]) -> None:
    sanitized = dict(DEFAULT_CONFIG)
    for key in DEFAULT_CONFIG:
        value = config.get(key, DEFAULT_CONFIG[key])
        sanitized[key] = value.strip() if isinstance(value, str) else DEFAULT_CONFIG[key]

    if sanitized["cd_quote_style"] not in {"single", "double"}:
        sanitized["cd_quote_style"] = DEFAULT_CONFIG["cd_quote_style"]

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(sanitized, indent=2) + "\n", encoding="utf-8")


def configured_agent_executable(agent: str, override: str | None = None) -> str:
    if override and override.strip():
        return override.strip()

    config = load_config()
    key = f"{agent}_executable"
    return config.get(key) or DEFAULT_AGENTS[agent]


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

    nautilus_path = active_nautilus_path()
    if nautilus_path:
        return nautilus_path

    dolphin_path = active_dolphin_path()
    if dolphin_path:
        return dolphin_path

    active_cwd = active_window_cwd()
    if active_cwd:
        return active_cwd

    return PathResult(str(Path.cwd()), "current working directory")


def active_nautilus_path() -> PathResult | None:
    if not has_graphical_display():
        return None

    try:
        import pyatspi  # type: ignore
    except ImportError:
        return None

    try:
        desktop = pyatspi.Registry.getDesktop(0)
    except Exception:
        return None

    for index in range(accessible_child_count(desktop)):
        app = accessible_child(desktop, index)
        if app is None:
            continue
        app_name = accessible_name(app).lower()
        if "nautilus" not in app_name and "files" not in app_name:
            continue

        path = path_from_nautilus_accessible(app)
        if path:
            return PathResult(path, "Nautilus accessibility")

    return None


def path_from_nautilus_accessible(root: Any) -> str | None:
    names: list[str] = []
    collect_accessible_names(root, names, limit=700)
    path = nautilus_breadcrumb_path(names)
    return normalize_path(path) if path else None


def collect_accessible_names(node: Any, names: list[str], limit: int) -> None:
    if len(names) >= limit:
        return

    name = accessible_name(node)
    if name:
        names.append(name)

    for index in range(min(accessible_child_count(node), 80)):
        child = accessible_child(node, index)
        if child is not None:
            collect_accessible_names(child, names, limit)
        if len(names) >= limit:
            return


def nautilus_breadcrumb_path(names: Sequence[str]) -> str | None:
    try:
        menu_index = list(names).index("Current Folder Menu")
    except ValueError:
        return None

    window = list(names[max(0, menu_index - 50):menu_index])
    tokens: list[str] = []
    for name in window:
        cleaned = name.strip()
        if cleaned and (not tokens or tokens[-1] != cleaned):
            tokens.append(cleaned)

    last_navigation_index = -1
    for marker in ("Back", "Forward"):
        if marker in tokens:
            last_navigation_index = max(last_navigation_index, len(tokens) - 1 - tokens[::-1].index(marker))

    tokens = tokens[last_navigation_index + 1:]
    tokens = [token for token in tokens if token not in {"Back", "Forward"}]
    if not tokens:
        return None

    if "Home" in tokens:
        start = len(tokens) - 1 - tokens[::-1].index("Home")
        components = [token for token in tokens[start + 1:] if token != "/"]
        return str(Path.home().joinpath(*components))

    if "/" in tokens:
        start = tokens.index("/")
        components = [token for token in tokens[start + 1:] if token != "/"]
        return str(Path("/").joinpath(*components))

    return None


def accessible_name(node: Any) -> str:
    try:
        name = node.name
    except Exception:
        return ""
    return name if isinstance(name, str) else ""


def accessible_child_count(node: Any) -> int:
    try:
        return int(node.childCount)
    except Exception:
        return 0


def accessible_child(node: Any, index: int) -> Any | None:
    try:
        return node.getChildAtIndex(index)
    except Exception:
        return None


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
    commands: list[tuple[str, ...]] = []
    if os.environ.get("WAYLAND_DISPLAY"):
        commands.append(("wl-copy",))
    if os.environ.get("DISPLAY"):
        commands.extend(
            [
                ("xclip", "-selection", "clipboard"),
                ("xsel", "--clipboard", "--input"),
            ]
        )
    if not commands:
        commands.extend(
            [
                ("wl-copy",),
                ("xclip", "-selection", "clipboard"),
                ("xsel", "--clipboard", "--input"),
            ]
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
                timeout=3,
            )
            return None
        except subprocess.TimeoutExpired:
            failures.append(f"{command[0]}: timed out")
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
    config = load_config()
    for value in (preferred, os.environ.get("FINDERPATH_TERMINAL"), config.get("terminal")):
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
    quote_style = args.quote_style or load_config()["cd_quote_style"]
    command = cd_command(result.path, quote_style)
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
    executable = configured_agent_executable(agent, args.executable)
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


class SettingsWindow:
    def __init__(self, on_save: Callable[[], None] | None = None, quit_on_destroy: bool = False) -> None:
        if not has_graphical_display():
            raise RuntimeError(
                "No graphical display session found. Start settings from your desktop session "
                "or set DISPLAY/WAYLAND_DISPLAY before running it."
            )

        try:
            import gi  # type: ignore
        except ImportError as error:
            raise RuntimeError("GTK settings support is not installed. Install python3-gi.") from error

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk  # type: ignore

        self.Gtk = Gtk
        self.on_save = on_save
        self.quit_on_destroy = quit_on_destroy
        self.entries: dict[str, Any] = {}
        self.quote_combo: Any | None = None
        self.window = Gtk.Window(title=f"{APP_NAME} Settings")
        self.window.set_icon_name(APP_ID)
        self.window.set_default_size(520, 360)
        self.window.set_border_width(18)
        self.window.connect("destroy", self.on_destroy)
        self.build()

    def build(self) -> None:
        Gtk = self.Gtk
        config = load_config()

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.window.add(root)

        heading = Gtk.Label(label="FinderPath Linux Settings")
        heading.set_xalign(0)
        heading.get_style_context().add_class("title")
        root.pack_start(heading, False, False, 0)

        grid = Gtk.Grid(column_spacing=14, row_spacing=12)
        root.pack_start(grid, True, True, 0)

        self.add_entry_row(grid, 0, "Terminal", "terminal", config["terminal"], "auto-detect")
        self.add_quote_row(grid, 1, config["cd_quote_style"])
        self.add_entry_row(grid, 2, "Codex executable", "codex_executable", config["codex_executable"], "codex")
        self.add_entry_row(grid, 3, "Claude executable", "claude_executable", config["claude_executable"], "claude")
        self.add_entry_row(grid, 4, "Hermes executable", "hermes_executable", config["hermes_executable"], "hermes")

        config_label = Gtk.Label(label=f"Config: {CONFIG_PATH}")
        config_label.set_xalign(0)
        config_label.set_selectable(True)
        root.pack_start(config_label, False, False, 0)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buttons.set_halign(Gtk.Align.END)
        root.pack_start(buttons, False, False, 0)

        reset = Gtk.Button(label="Reset")
        reset.connect("clicked", lambda _button: self.reset_to_defaults())
        buttons.pack_start(reset, False, False, 0)

        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _button: self.window.destroy())
        buttons.pack_start(cancel, False, False, 0)

        save = Gtk.Button(label="Save")
        save.get_style_context().add_class("suggested-action")
        save.connect("clicked", lambda _button: self.save())
        buttons.pack_start(save, False, False, 0)

    def add_entry_row(
        self,
        grid: object,
        row: int,
        label_text: str,
        key: str,
        value: str,
        placeholder: str,
    ) -> None:
        Gtk = self.Gtk
        label = Gtk.Label(label=label_text)
        label.set_xalign(0)
        grid.attach(label, 0, row, 1, 1)

        entry = Gtk.Entry()
        entry.set_hexpand(True)
        entry.set_text(value)
        entry.set_placeholder_text(placeholder)
        grid.attach(entry, 1, row, 1, 1)
        self.entries[key] = entry

    def add_quote_row(self, grid: object, row: int, value: str) -> None:
        Gtk = self.Gtk
        label = Gtk.Label(label="cd command quotes")
        label.set_xalign(0)
        grid.attach(label, 0, row, 1, 1)

        combo = Gtk.ComboBoxText()
        combo.append("single", "Single quotes")
        combo.append("double", "Double quotes")
        combo.set_active_id(value if value in {"single", "double"} else DEFAULT_CONFIG["cd_quote_style"])
        grid.attach(combo, 1, row, 1, 1)
        self.quote_combo = combo

    def reset_to_defaults(self) -> None:
        for key, entry in self.entries.items():
            entry.set_text(DEFAULT_CONFIG[key])
        if self.quote_combo is not None:
            self.quote_combo.set_active_id(DEFAULT_CONFIG["cd_quote_style"])

    def save(self) -> None:
        config = {key: entry.get_text() for key, entry in self.entries.items()}
        quote_style = self.quote_combo.get_active_id() if self.quote_combo is not None else None
        config["cd_quote_style"] = quote_style or DEFAULT_CONFIG["cd_quote_style"]
        save_config(config)
        notify(APP_NAME, "Settings saved")
        if self.on_save:
            self.on_save()
        self.window.destroy()

    def on_destroy(self, *_args: object) -> None:
        if self.quit_on_destroy:
            self.Gtk.main_quit()

    def show(self) -> None:
        self.window.show_all()
        self.window.present()


def show_settings_window(on_save: Callable[[], None] | None = None, run_main: bool = False) -> None:
    settings = SettingsWindow(on_save=on_save, quit_on_destroy=run_main)
    settings.show()
    if run_main:
        settings.Gtk.main()


def action_settings(_args: argparse.Namespace) -> int:
    try:
        show_settings_window(run_main=True)
    except RuntimeError as error:
        print(error, file=sys.stderr)
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
        from gi.repository import GLib, Gtk  # type: ignore

        try:
            gi.require_version("AyatanaAppIndicator3", "0.1")
            from gi.repository import AyatanaAppIndicator3 as AppIndicator3  # type: ignore
        except (ImportError, ValueError):
            gi.require_version("AppIndicator3", "0.1")
            from gi.repository import AppIndicator3  # type: ignore

        self.Gtk = Gtk
        self.GLib = GLib
        self.AppIndicator3 = AppIndicator3
        self.terminal_override = preferred_terminal
        self.config = load_config()
        self.refresh_source_id: int | None = None
        self.indicator = AppIndicator3.Indicator.new(
            APP_ID,
            APP_ID,
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

    def run(self) -> int:
        self.rebuild_menu()
        self.refresh_source_id = self.GLib.timeout_add_seconds(2, self.rebuild_menu)
        self.Gtk.main()
        return 0

    def rebuild_menu(self) -> bool:
        Gtk = self.Gtk
        self.config = load_config()
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
        self.append_item(menu, "Copy Path", self.copy_path)
        self.append_item(menu, "Copy cd Command", self.copy_cd)
        menu.append(Gtk.SeparatorMenuItem())

        self.append_item(
            menu,
            "Open in Terminal",
            lambda: self.run_action(open_terminal_at(current_path().path, self.terminal_override)),
        )
        self.append_item(
            menu,
            "Open in Ghostty",
            lambda: self.run_action(open_ghostty_at(current_path().path)),
            executable="ghostty",
        )
        self.append_item(
            menu,
            "Open in cmux",
            lambda: self.run_action(open_cmux_at(current_path().path)),
            executable="cmux",
        )
        menu.append(Gtk.SeparatorMenuItem())

        for agent in DEFAULT_AGENTS:
            executable = configured_agent_executable(agent)
            label = f"Open with {agent.capitalize()}"
            self.append_item(
                menu,
                label,
                lambda agent=agent, executable=executable: self.run_action(
                    open_agent(agent, executable, current_path().path, self.terminal_override)
                ),
                executable=executable,
            )

        menu.append(Gtk.SeparatorMenuItem())
        self.append_tailscale_menu(menu)
        menu.append(Gtk.SeparatorMenuItem())
        self.append_item(menu, "Settings...", lambda: show_settings_window(on_save=self.rebuild_menu))
        self.append_item(menu, "Quit", Gtk.main_quit)

        menu.show_all()
        self.indicator.set_menu(menu)
        return True

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
                item.connect("activate", lambda _item, name=device.name: self.run_action(open_ssh(name, self.terminal_override)))
                submenu.append(item)

        submenu_root.set_submenu(submenu)
        menu.append(submenu_root)

    def copy_path(self) -> None:
        path = current_path().path
        error = copy_to_clipboard(path)
        self.run_action(error)
        if not error:
            notify(APP_NAME, "Copied path")

    def copy_cd(self) -> None:
        path = current_path().path
        error = copy_to_clipboard(cd_command(path, self.config["cd_quote_style"]))
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
    assert (
        nautilus_breadcrumb_path(["Back", "Forward", "Home", "/", "Backups", "/", "mac-projects", "Current Folder Menu"])
        == str(Path.home() / "Backups" / "mac-projects")
    )
    assert (
        nautilus_breadcrumb_path(["Back", "Forward", "/", "var", "/", "log", "Current Folder Menu"])
        == "/var/log"
    )
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
    copy_cd_parser.add_argument("--quote-style", choices=("single", "double"), default=None)

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

    subparsers.add_parser("settings", help="Open the GTK settings window.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    command = args.command
    if command is None:
        if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
            command = "tray"
            args.terminal = None
        else:
            command = "path"
            args.path = None
            args.source = False

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
    if command == "settings":
        return action_settings(args)

    parser.error(f"unknown command: {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
