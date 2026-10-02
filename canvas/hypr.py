"""Direct Hyprland IPC via Unix socket — no subprocess needed.

Hyprland's .socket.sock speaks a one-shot request-response protocol:
  connect → send b"<command>" → read response until EOF → close

The server closes the connection after each response, so every send()
opens a fresh connection. This avoids subprocess startup while keeping
each request independent. Thread-safe via lock.

WARNING: Hyprland processes IPC synchronously — an unclosed connection
freezes the compositor for up to 5 seconds. Always close promptly.
"""

import json
import logging
import os
import socket
import threading
from dataclasses import dataclass

log = logging.getLogger("canvas.hypr")

_MAX_RESPONSE = 16 * 1024 * 1024  # j/clients can be large; this is generous

LUA_DISPATCH_HELPER = """
local function _canvas_dispatch(result)
  if type(result) ~= "table" or result.ok == false then
    local message = type(result) == "table" and result.error or "dispatcher returned no result"
    error(message or "dispatch failed")
  end
end
""".strip()


class HyprIPCError(RuntimeError):
    """Hyprland returned a textual error response for an IPC request."""


@dataclass(frozen=True)
class CanvasViewport:
    """Canvas camera state expressed in world-space units."""

    enabled: bool = False
    zoom: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    monitor_x: float = 0.0
    monitor_y: float = 0.0

    def screen_to_world(self, x: float, y: float) -> tuple[float, float]:
        return (
            self.monitor_x + self.offset_x + (x - self.monitor_x) / self.zoom,
            self.monitor_y + self.offset_y + (y - self.monitor_y) / self.zoom,
        )

    def world_to_screen(self, x: float, y: float) -> tuple[float, float]:
        return (
            self.monitor_x + (x - self.monitor_x - self.offset_x) * self.zoom,
            self.monitor_y + (y - self.monitor_y - self.offset_y) * self.zoom,
        )


def _hypr_socket_path() -> str:
    """Resolve the Hyprland IPC socket path."""
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    uid = os.getuid()
    base = f"/run/user/{uid}/hypr"
    if sig and os.path.exists(f"{base}/{sig}/.socket.sock"):
        return f"{base}/{sig}/.socket.sock"
    if os.path.isdir(base):
        for d in sorted(os.listdir(base)):
            sock = f"{base}/{d}/.socket.sock"
            if os.path.exists(sock):
                return sock
    raise FileNotFoundError("Hyprland socket not found")


def _hypr_socket2_path() -> str:
    """Resolve the Hyprland event socket (.socket2.sock) path."""
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    uid = os.getuid()
    base = f"/run/user/{uid}/hypr"
    if sig and os.path.exists(f"{base}/{sig}/.socket2.sock"):
        return f"{base}/{sig}/.socket2.sock"
    if os.path.isdir(base):
        for d in sorted(os.listdir(base)):
            sock = f"{base}/{d}/.socket2.sock"
            if os.path.exists(sock):
                return sock
    raise FileNotFoundError("Hyprland event socket not found")


def _normalize_address(addr: str) -> str:
    """Normalize window address for comparison.

    Hyprland uses '0x...' format in j/clients and IPC.
    socket2 events may omit the '0x' prefix.
    """
    addr = addr.strip().lower()
    if not addr.startswith("0x"):
        addr = "0x" + addr
    return addr


class HyprIPC:
    """Thread-safe one-shot Hyprland IPC client.

    Encapsulates connection state as instance attributes instead of
    module globals, enabling testability via dependency injection.
    """

    def __init__(self, socket_path: str) -> None:
        self._socket_path = socket_path
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "HyprIPC":
        """Create HyprIPC by auto-detecting socket path from environment."""
        return cls(_hypr_socket_path())

    def _connect(self) -> socket.socket:
        """Create a new connection to Hyprland IPC socket."""
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(self._socket_path)
        return s

    def _recv_response(self, s: socket.socket) -> str:
        """Read full response from socket until server closes."""
        resp = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
            if len(resp) > _MAX_RESPONSE:
                raise ConnectionError("Hyprland response exceeded size limit")
        return resp.decode().strip()

    def send(self, command: str) -> str:
        """Send a command to the Hyprland IPC socket, return response string.

        One fresh connection per command (the server closes after each
        response). Thread-safe via lock.
        """
        with self._lock:
            s = self._connect()
            try:
                s.sendall(command.encode())
                s.shutdown(socket.SHUT_WR)
                response = self._recv_response(s)
                if response.lower().startswith("error"):
                    command_name = command.split(" ", 1)[0]
                    raise HyprIPCError(f"Hyprland {command_name} failed: {response}")
                return response
            finally:
                s.close()

    def eval_lua(self, lua: str) -> str:
        """Execute Lua code via Hyprland eval. Returns response string."""
        return self.send(f"eval {lua}")

    def get_cursor_pos(self) -> tuple[int, int]:
        """Query cursor position. Returns (x, y)."""
        resp = self.send("cursorpos")
        parts = resp.split(", ")
        return int(parts[0]), int(parts[1])

    def get_active_window_geometry(self) -> tuple[str, int, int, int, int] | None:
        """Focused window as (address, x, y, width, height), or None if unknown.

        During an interactive drag Hyprland focuses the dragged window, so
        this is the ground truth for where the dragged window really is.
        """
        resp = self.send("j/activewindow")
        w = json.loads(resp)
        addr = str(w.get("address", ""))
        at = w.get("at", [0, 0])
        size = w.get("size", [0, 0])
        if not addr or len(at) < 2 or len(size) < 2:
            return None
        try:
            return addr, int(at[0]), int(at[1]), int(size[0]), int(size[1])
        except (TypeError, ValueError):
            return None

    def set_canvas_viewport(self, action: str, workspace_id: int) -> bool:
        """Best-effort bridge to the optional hypr-canvas plugin."""
        if action not in {"enable", "disable", "reset", "zoom-in", "zoom-out", "zoom-reset"}:
            raise ValueError(f"invalid canvas viewport action: {action}")
        try:
            self.send(f"hypr-canvas {action} {int(workspace_id)}")
            return True
        except Exception as e:
            log.debug("hypr-canvas %s ws=%s unavailable: %s", action, workspace_id, e)
            return False

    def get_canvas_viewport(self, workspace_id: int) -> CanvasViewport:
        """Read camera state; fall back to an identity viewport if plugin is absent."""
        try:
            raw = self.send(f"hypr-canvas status {int(workspace_id)}")
            data = json.loads(raw)
            zoom = float(data.get("zoom", 1.0))
            if not (0.0 < zoom <= 1.0):
                raise ValueError(f"invalid zoom {zoom}")
            return CanvasViewport(
                enabled=bool(data.get("enabled", False)),
                zoom=zoom,
                offset_x=float(data.get("offset_x", 0.0)),
                offset_y=float(data.get("offset_y", 0.0)),
                monitor_x=float(data.get("monitor_x", 0.0)),
                monitor_y=float(data.get("monitor_y", 0.0)),
            )
        except Exception as e:
            log.debug("hypr-canvas status ws=%s unavailable: %s", workspace_id, e)
            return CanvasViewport()


_default: HyprIPC | None = None
_default_lock = threading.Lock()


def _get_default() -> HyprIPC:
    """Get or create the default module-level HyprIPC instance."""
    global _default
    if _default is None:
        with _default_lock:
            if _default is None:
                _default = HyprIPC.from_env()
    return _default


def send(command: str) -> str:
    """Send a command via the default HyprIPC instance."""
    return _get_default().send(command)


def eval_lua(lua: str) -> str:
    """Execute Lua code via the default HyprIPC instance."""
    return _get_default().eval_lua(lua)


def get_cursor_pos() -> tuple[int, int]:
    """Query cursor position via the default HyprIPC instance."""
    return _get_default().get_cursor_pos()


def get_active_window_geometry() -> tuple[str, int, int, int, int] | None:
    """Focused window geometry via the default HyprIPC instance."""
    return _get_default().get_active_window_geometry()
