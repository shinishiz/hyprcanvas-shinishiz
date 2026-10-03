"""Canvas daemon — main loop wiring all modules together."""

import contextlib
import json
import logging
import re
import signal
import socket
import threading
import time
from typing import Any

from canvas import debug
from canvas.config import load
from canvas.hypr import (
    LUA_DISPATCH_HELPER,
    CanvasViewport,
    HyprIPC,
    _hypr_socket2_path,
    _normalize_address,
    get_cursor_pos,
)
from canvas.ipc import IpcServer, acquire_singleton
from canvas.navigation import Navigator
from canvas.panning import EdgeScrollParams, EdgeScrollState, PanningState, cursor_poller

log = logging.getLogger("canvas")

_VALID_ADDR = re.compile(r"^0x[0-9a-fA-F]+$")


_MAX_OPENWINDOW_RETRIES = 3
_OPENWINDOW_RETRY_DELAY = 0.05  # 50ms

def _lua_escape(s: str) -> str:
    """Escape a string for safe interpolation into a Lua double-quoted literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")


class EventListener:
    """Listens to Hyprland .socket2.sock for window events."""

    def __init__(
        self,
        navigator: Navigator,
        ipc: HyprIPC,
        stop_event: threading.Event,
    ) -> None:
        self._navigator = navigator
        self._ipc = ipc
        self._stop_event = stop_event
        self._thread: threading.Thread | None = None
        self._pending_retries: dict[str, tuple[int, float]] = {}  # addr -> (attempt, deadline)
        self._pending_lock = threading.Lock()
        self._sock: socket.socket | None = None

    def start(self) -> None:
        """Start the event listener thread."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.debug("EventListener started")

    def stop(self) -> None:
        """Stop the event listener thread."""
        self._stop_event.set()
        if self._sock:
            with contextlib.suppress(Exception):
                self._sock.close()
        if self._thread:
            self._thread.join(timeout=1)
        log.debug("EventListener stopped")

    def _run(self) -> None:
        """Main event loop."""
        sock_path = _hypr_socket2_path()
        try:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.settimeout(1.0)
            self._sock.connect(sock_path)
        except Exception as e:
            log.warning("EventListener failed to connect to %s: %s", sock_path, e)
            return

        buffer = ""
        while not self._stop_event.is_set():
            # Process pending retries
            self._process_pending_retries()

            try:
                chunk = self._sock.recv(4096)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    self._handle_line(line.strip())
            except TimeoutError:
                continue
            except OSError as e:
                if not self._stop_event.is_set():
                    log.debug("EventListener socket error: %s", e)
                break

        if self._sock:
            self._sock.close()
            self._sock = None

    def _handle_line(self, line: str) -> None:
        """Handle a single event line from socket2."""
        if not line or ">>" not in line:
            return
        event, payload = line.split(">>", 1)
        event = event.strip()
        payload = payload.strip()

        if event == "openwindow":
            self._handle_openwindow(payload)
        elif event == "closewindow":
            self._handle_closewindow(payload)
        elif event == "movewindowv2":
            self._handle_movewindowv2(payload)

    def _handle_movewindowv2(self, payload: str) -> None:
        """Handle movewindowv2: ADDRESS,DEST_WORKSPACE_ID,DEST_WORKSPACE_NAME."""
        parts = payload.split(",", 2)
        if len(parts) != 3:
            return

        addr = _normalize_address(parts[0])
        if not _VALID_ADDR.match(addr):
            return
        try:
            destination_workspace_id = int(parts[1])
        except (TypeError, ValueError):
            return
        if destination_workspace_id <= 0:
            return
        destination_workspace_name = parts[2].strip()
        if not destination_workspace_name:
            return

        # movewindowv2 is emitted after CWindow::moveToWorkspace().  Verify the
        # current client before reconciling so delayed 2->6->3 events cannot
        # mutate ownership using a stale destination.
        try:
            clients = json.loads(self._ipc.send("j/clients"))
        except Exception as exc:
            log.debug("movewindowv2: j/clients failed: %s", exc)
            return
        if not isinstance(clients, list):
            return
        client = next(
            (
                c
                for c in clients
                if isinstance(c, dict)
                and _normalize_address(str(c.get("address", ""))) == addr
            ),
            None,
        )
        if client is None:
            return
        workspace = client.get("workspace")
        if not isinstance(workspace, dict):
            return
        raw_workspace_id = workspace.get("id")
        if isinstance(raw_workspace_id, bool) or not isinstance(raw_workspace_id, (int, str)):
            return
        try:
            current_workspace_id = int(raw_workspace_id)
        except (TypeError, ValueError):
            return
        if current_workspace_id != destination_workspace_id:
            log.debug(
                "movewindowv2: stale event for %s: event=%s current=%s",
                addr,
                destination_workspace_id,
                current_workspace_id,
            )
            return

        self._navigator.handle_window_moved(
            addr,
            destination_workspace_id,
            destination_workspace_name,
            client,
        )

    def _handle_openwindow(self, payload: str) -> None:
        """Handle openwindow event: ADDRESS,WORKSPACENAME,CLASS,TITLE"""
        parts = payload.split(",", 3)
        if len(parts) < 4:
            return

        raw_addr = parts[0]
        addr = _normalize_address(raw_addr)

        # Look up the client in j/clients to get workspace ID and geometry
        self._process_new_window(addr, attempt=0)

    def _process_new_window(self, addr: str, attempt: int) -> None:
        """Process a newly opened window, with retry logic."""
        try:
            resp = self._ipc.send("j/clients")
            clients = json.loads(resp)
        except Exception as e:
            log.debug("openwindow: j/clients failed: %s", e)
            self._schedule_retry(addr, attempt)
            return

        client = next(
            (c for c in clients if _normalize_address(c.get("address", "")) == addr),
            None,
        )
        if not client:
            self._schedule_retry(addr, attempt)
            return

        # Check if client has valid geometry
        at = client.get("at")
        size = client.get("size")
        if not at or not size or len(at) < 2 or len(size) < 2:
            self._schedule_retry(addr, attempt)
            return

        floating = client.get("floating", False)
        if floating:
            # Already floating, nothing to do
            return

        ws_info = client.get("workspace")
        if not isinstance(ws_info, dict):
            return
        ws_id = ws_info.get("id")
        if ws_id is None:
            return

        # Check if this workspace has Canvas active
        if not self._navigator.is_canvas_active(ws_id):
            return

        # Check if hidden/fullscreen/pinned - skip if so
        if client.get("hidden") or client.get("fullscreen"):
            return

        # Get spawn geometry from tiled snapshot (median size)
        spawn_geo = self._navigator.get_spawn_geometry(ws_id)
        if spawn_geo is not None:
            w, h = spawn_geo
        else:
            # Fallback: use the window's current size (capped to reasonable max)
            w, h = int(size[0]), int(size[1])
            max_w, max_h = 1200, 800
            if w > max_w:
                w = max_w
            if h > max_h:
                h = max_h

        # Position at the visual center of this window's own monitor/workspace.
        # If that monitor cannot be resolved, preserve the current window center
        # instead of guessing a monitor or resolution.
        world_center: tuple[float, float] | None = None
        try:
            monitor_id = int(client.get("monitor"))
        except (TypeError, ValueError):
            monitor_id = None
        if monitor_id is not None:
            world_center = self._navigator.get_canvas_visual_center(ws_id, monitor_id)
        if world_center is None:
            try:
                world_center = (
                    float(at[0]) + float(size[0]) / 2,
                    float(at[1]) + float(size[1]) / 2,
                )
            except (TypeError, ValueError):
                self._schedule_retry(addr, attempt)
                return

        x = world_center[0] - w / 2
        y = world_center[1] - h / 2

        lua = (
            f"{LUA_DISPATCH_HELPER}\n"
            f"local ws = hl.get_windows({{ workspace = {ws_id} }})\n"
            f"for _, win in ipairs(ws) do\n"
            f'  if tostring(win.address) == "{addr}" then\n'
            f"    _canvas_dispatch(hl.dispatch(hl.dsp.window.float("
            f"{{ action = \"toggle\", window = win }})))\n"
            f"    _canvas_dispatch(hl.dispatch(hl.dsp.window.resize("
            f"{{ x = {w}, y = {h}, relative = false, window = win }})))\n"
            f"    _canvas_dispatch(hl.dispatch(hl.dsp.window.move("
            f"{{ x = {x}, y = {y}, relative = false, window = win }})))\n"
            f"    break\n"
            f"  end\n"
            f"end\n"
        )
        try:
            self._ipc.eval_lua(lua)
        except Exception as e:
            log.warning("openwindow: failed to float new window %s: %s", addr, e)
            return

        # Register as spawned during canvas
        self._navigator.register_spawned_during_canvas(ws_id, addr)

    def _schedule_retry(self, addr: str, attempt: int) -> None:
        """Schedule a retry for openwindow processing."""
        if attempt >= _MAX_OPENWINDOW_RETRIES:
            log.debug("openwindow: max retries reached for %s", addr)
            with self._pending_lock:
                self._pending_retries.pop(addr, None)
            return

        with self._pending_lock:
            self._pending_retries[addr] = (attempt + 1, time.monotonic() + _OPENWINDOW_RETRY_DELAY)

    def _process_pending_retries(self) -> None:
        """Process any pending openwindow retries."""
        now = time.monotonic()
        with self._pending_lock:
            due = [
                (addr, _attempt)
                for addr, (_attempt, deadline) in self._pending_retries.items()
                if now >= deadline
            ]
            for addr, _attempt in due:
                self._pending_retries.pop(addr, None)

        for addr, _attempt in due:
            self._process_new_window(addr, _attempt)

    def _handle_closewindow(self, payload: str) -> None:
        """Handle closewindow event: ADDRESS"""
        raw_addr = payload.strip()
        if not raw_addr:
            return
        addr = _normalize_address(raw_addr)

        # Remove from pending retries
        with self._pending_lock:
            self._pending_retries.pop(addr, None)

        # Remove from navigator state
        self._navigator.unregister_window(addr)


class DaemonState:
    """Encapsulates daemon runtime state — replaces closure + nonlocal.

    Makes state testable via dependency injection (mock HyprIPC, etc).
    """

    def __init__(
        self,
        panning: PanningState,
        edge_scroll: EdgeScrollState,
        navigator: Navigator,
        ipc: HyprIPC,
    ) -> None:
        self.panning = panning
        self.edge_scroll = edge_scroll
        self.navigator = navigator
        self.ipc = ipc
        self.baselines: dict[str, tuple[int, int]] = {}
        # Workspace whose windows the baselines belong to; pan and
        # edge-scroll moves are scoped to it so other workspaces'
        # floating layouts stay untouched.
        self.baseline_workspace: int | None = None
        self.baseline_zoom = 1.0
        self.edge_scroll_workspace: int | None = None
        # Serializes compositor mutations from the IPC thread with main-loop
        # pan/edge moves. State objects retain their own fine-grained locks.
        self._operation_lock = threading.RLock()

    def _fetch_monitor_rect(self) -> bool:
        """Fetch focused monitor geometry for edge-scroll. True on success."""
        try:
            resp = self.ipc.send("j/monitors")
            monitors: list[dict[str, Any]] = json.loads(resp)
            first_valid: tuple[int, int, int, int] | None = None
            for monitor in monitors:
                try:
                    x = int(monitor["x"])
                    y = int(monitor["y"])
                    width = int(monitor["width"])
                    height = int(monitor["height"])
                except (KeyError, TypeError, ValueError):
                    continue
                if width <= 0 or height <= 0:
                    continue
                rect = (x, y, width, height)
                if first_valid is None:
                    first_valid = rect
                if monitor.get("focused", False):
                    self.edge_scroll.set_monitor_rect(*rect)
                    return True
            if first_valid is not None:
                self.edge_scroll.set_monitor_rect(*first_valid)
                return True
        except Exception as e:
            log.debug("fetch monitor rect failed: %s", e)
        return False

    def _get_active_workspace_id(self) -> int | None:
        """Active workspace id, or None when the query fails."""
        try:
            resp = self.ipc.send("j/activeworkspace")
            ws: dict[str, Any] = json.loads(resp)
            return int(ws["id"])
        except Exception as e:
            log.debug("get active workspace failed: %s", e)
            return None

    def _canvas_viewport(self, workspace_id: int) -> CanvasViewport:
        """Current viewport for an active Canvas workspace, else identity."""
        try:
            if self.navigator.is_canvas_active(workspace_id) is not True:
                return CanvasViewport()
            viewport = self.ipc.get_canvas_viewport(workspace_id)
            return viewport if isinstance(viewport, CanvasViewport) else CanvasViewport()
        except Exception as e:
            log.debug("canvas viewport query failed for ws=%s: %s", workspace_id, e)
            return CanvasViewport()

    _IPC_DISPATCH: dict[str, str] = {
        "PAN_START": "_handle_pan_start",
        "PAN_STOP": "_handle_pan_stop",
        "NAV_LEFT": "_handle_nav_left",
        "NAV_RIGHT": "_handle_nav_right",
        "NAV_UP": "_handle_nav_up",
        "NAV_DOWN": "_handle_nav_down",
        "CENTER_CURSOR": "_handle_center_cursor",
        "ZOOM_IN": "_handle_zoom_in",
        "ZOOM_OUT": "_handle_zoom_out",
        "ZOOM_RESET": "_handle_zoom_reset",
        "EDGE_START": "_handle_edge_start",
        "EDGE_STOP": "_handle_edge_stop",
        "TOGGLE": "_handle_toggle",
        "CANVAS_TOGGLE": "_handle_canvas_toggle",
        "CANVAS_TOGGLE_ALL": "_handle_canvas_toggle_all",
        "CANVAS_TOGGLE_SINGLE": "_handle_canvas_toggle_single",
        "PING": "_handle_ping",
        "STATUS": "_handle_status",
    }

    def handle_ipc(self, cmd: str) -> str:
        """Process an IPC command, return response string."""
        with self._operation_lock:
            command = cmd
            workspace_id: int | None = None
            parts = cmd.split()
            if parts and parts[0] in {"CANVAS_TOGGLE", "CANVAS_TOGGLE_ALL"}:
                command = parts[0]
                if len(parts) > 2:
                    return "ERROR:INVALID_WORKSPACE"
                if len(parts) == 2:
                    try:
                        workspace_id = int(parts[1])
                    except ValueError:
                        return "ERROR:INVALID_WORKSPACE"
                    if workspace_id <= 0:
                        return "ERROR:INVALID_WORKSPACE"

            handler_name = self._IPC_DISPATCH.get(command)
            if handler_name is not None:
                handler = getattr(self, handler_name)
                if command in {"CANVAS_TOGGLE", "CANVAS_TOGGLE_ALL"}:
                    result = handler(workspace_id)
                else:
                    result = handler()
                debug.dbg("CMD", cmd=cmd, result=result)
                return result
            debug.dbg("CMD", cmd=cmd, result="UNKNOWN")
            return f"UNKNOWN: {cmd}"

    def _handle_pan_start(self) -> str:
        if self.edge_scroll.active:
            self.edge_scroll.stop()
            debug.dbg2("MODE_SWITCH", to="pan", stopped="edge")
        if not self.fetch_baselines():
            self.panning.stop_pan()
            debug.dbg2("PAN_START", baselines=0, result="PAN_NO_BASELINE")
            return "PAN_NO_BASELINE"
        result = self.panning.start_pan()
        debug.dbg2("PAN_START", baselines=len(self.baselines), result=result)
        return result

    def _handle_pan_stop(self) -> str:
        self.panning.stop_pan()
        self.baselines = {}
        self.baseline_workspace = None
        self.baseline_zoom = 1.0
        debug.dbg2("PAN_STOP")
        return "PAN_OFF"

    def _handle_nav_left(self) -> str:
        self._stop_competing_modes("navigation")
        return "OK" if self.navigator.navigate("left") else "ERROR:NAV_FAILED"

    def _handle_nav_right(self) -> str:
        self._stop_competing_modes("navigation")
        return "OK" if self.navigator.navigate("right") else "ERROR:NAV_FAILED"

    def _handle_nav_up(self) -> str:
        self._stop_competing_modes("navigation")
        return "OK" if self.navigator.navigate("up") else "ERROR:NAV_FAILED"

    def _handle_nav_down(self) -> str:
        self._stop_competing_modes("navigation")
        return "OK" if self.navigator.navigate("down") else "ERROR:NAV_FAILED"

    def _handle_center_cursor(self) -> str:
        self._stop_competing_modes("center-cursor")
        try:
            cursor_x, cursor_y = self.ipc.get_cursor_pos()
        except Exception as e:
            log.debug("center-cursor: cursor query failed: %s", e)
            return "ERROR:NO_CURSOR"

        workspace_id = self._get_active_workspace_id()
        if workspace_id is None:
            return "ERROR:NO_WORKSPACE"

        try:
            target = self._find_window_at_cursor(cursor_x, cursor_y, workspace_id, strict=True)
        except Exception as e:
            log.debug("center-cursor: client query failed: %s", e)
            return "ERROR:QUERY_FAILED"
        if target is None:
            return "ERROR:NO_WINDOW"

        try:
            centered = self.navigator.center_window(
                str(target.get("address", "")),
                workspace_id=workspace_id,
                cursor_x=cursor_x,
                cursor_y=cursor_y,
            )
        except Exception as e:
            log.warning("center-cursor failed: %s", e)
            return "ERROR:CENTER_FAILED"
        if not centered:
            return "ERROR:CENTER_FAILED"
        debug.dbg2(
            "CENTER_CURSOR",
            ws=workspace_id,
            target=target.get("address"),
            cursor=(cursor_x, cursor_y),
        )
        return "OK"

    def _handle_zoom(self, action: str) -> str:
        workspace_id = self._get_active_workspace_id()
        if workspace_id is None:
            return "ERROR:NO_WORKSPACE"
        if self.navigator.is_canvas_active(workspace_id) is not True:
            return "ERROR:CANVAS_INACTIVE"

        self._stop_competing_modes("zoom")
        if not self.ipc.set_canvas_viewport(action, workspace_id):
            return "ERROR:ZOOM_UNAVAILABLE"
        return "OK"

    def _handle_zoom_in(self) -> str:
        return self._handle_zoom("zoom-in")

    def _handle_zoom_out(self) -> str:
        return self._handle_zoom("zoom-out")

    def _handle_zoom_reset(self) -> str:
        return self._handle_zoom("zoom-reset")

    def _get_focused_window_address(self) -> str:
        """Address of the focused window, empty string on failure."""
        try:
            resp = self.ipc.send("j/activewindow")
            w: dict[str, Any] = json.loads(resp)
            return str(w.get("address", ""))
        except Exception as e:
            log.debug("get focused window address failed: %s", e)
            return ""

    def _find_window_at_cursor(
        self, cx: int, cy: int, workspace_id: int, *, strict: bool = False
    ) -> dict[str, Any] | None:
        """Movable floating window on the workspace whose rect contains the cursor.

        Hyprland's window.drag() moves whatever is under the pointer, not
        the previously focused window — geometry must come from the same
        place. Shared by edge-scroll and center-cursor. On overlap the last
        match wins: Hyprland's clients vector is bottom-to-top.
        """
        try:
            resp = self.ipc.send("j/clients")
            clients: list[dict[str, Any]] = json.loads(resp)
        except Exception as e:
            if strict:
                raise
            log.debug("find window at cursor failed: %s", e)
            return None

        found: dict[str, Any] | None = None
        viewport = self._canvas_viewport(workspace_id)
        hit_x, hit_y = viewport.screen_to_world(cx, cy) if viewport.enabled else (cx, cy)
        for w in clients:
            if not w.get("floating"):
                continue
            if w.get("hidden") or w.get("fullscreen"):
                continue
            wsw = w.get("workspace")
            if not isinstance(wsw, dict) or wsw.get("id") != workspace_id:
                continue
            addr = str(w.get("address", ""))
            at = w.get("at", [0, 0])
            size = w.get("size", [0, 0])
            if not addr or len(at) < 2 or len(size) < 2:
                continue
            if at[0] <= hit_x < at[0] + size[0] and at[1] <= hit_y < at[1] + size[1]:
                found = w
        return found

    def _handle_edge_start(self) -> str:
        """Activate edge-scroll for the floating window under the cursor."""
        if self.panning.is_dragging:
            # Modes are mutually exclusive: a stale pan session would fight
            # the edge camera (and vice versa below).
            self.panning.stop_pan()
            self.baselines = {}
            debug.dbg2("MODE_SWITCH", to="edge", stopped="pan")

        try:
            cx, cy = get_cursor_pos()
        except Exception as e:
            debug.dbg("EDGE_START_DECISION", verdict="NO_CURSOR", error=str(e))
            return "EDGE_NO_CURSOR"

        ws_id = self._get_active_workspace_id()
        if ws_id is None:
            debug.dbg("EDGE_START_DECISION", cursor=(cx, cy), verdict="NO_WORKSPACE")
            return "EDGE_NO_WORKSPACE"

        win = self._find_window_at_cursor(cx, cy, ws_id)
        if win is None:
            # Nothing draggable under the pointer: empty desktop, a tiled
            # window, or a stale-focused window that sits off-screen.
            # Activating here would derive bogus grab offsets and send the
            # camera chasing an invisible window.
            debug.dbg(
                "EDGE_START_DECISION",
                cursor=(cx, cy),
                ws=ws_id,
                candidate=None,
                verdict="NO_WINDOW_UNDER_CURSOR",
            )
            return "EDGE_NO_WINDOW"

        at = win.get("at", [0, 0])
        size = win.get("size", [0, 0])
        candidate_addr = str(win.get("address", ""))

        # A real grab makes Hyprland focus the pressed window. If focus is
        # elsewhere, this press landed on a border/gap inside the window's
        # bounding rect — no drag will engage. Refuse before arming.
        focused_addr = self._get_focused_window_address()
        if focused_addr != candidate_addr:
            debug.dbg(
                "EDGE_START_DECISION",
                cursor=(cx, cy),
                ws=ws_id,
                candidate=candidate_addr,
                focused=focused_addr,
                verdict="REFUSED_FOCUS_MISMATCH",
            )
            return "EDGE_NO_WINDOW"

        self.edge_scroll_workspace = ws_id
        viewport = self._canvas_viewport(ws_id)
        if viewport.enabled:
            self.edge_scroll.set_viewport(
                viewport.zoom, viewport.offset_x, viewport.offset_y
            )
        else:
            self.edge_scroll.set_viewport(1.0, 0.0, 0.0)
        if not self._fetch_monitor_rect():
            # Without real geometry the overflow math would run against a
            # default 1920x1080 rect — on multi-monitor setups that causes
            # phantom scrolling at wrong edges. Refuse instead.
            debug.dbg("EDGE_START_DECISION", candidate=candidate_addr, verdict="NO_MONITOR")
            return "EDGE_NO_MONITOR"

        result = self.edge_scroll.start(
            EdgeScrollParams(
                dragged_addr=candidate_addr,
                win_x=at[0] if len(at) >= 2 else 0,
                win_y=at[1] if len(at) >= 2 else 0,
                win_w=size[0] if len(size) >= 2 else 0,
                win_h=size[1] if len(size) >= 2 else 0,
                cursor_x=cx,
                cursor_y=cy,
            )
        )
        debug.dbg(
            "EDGE_START_DECISION",
            cursor=(cx, cy),
            ws=ws_id,
            candidate=candidate_addr,
            focused=focused_addr,
            verdict=result,
        )
        return result

    def _handle_edge_stop(self) -> str:
        result = self.edge_scroll.stop()
        self.edge_scroll.set_viewport(1.0, 0.0, 0.0)
        debug.dbg("EDGE_STOP", verdict=result)
        return result

    def _handle_toggle(self) -> str:
        self.panning.inverted = not self.panning.inverted
        return "INVERTED" if self.panning.inverted else "NORMAL"

    def _stop_competing_modes(self, to: str) -> None:
        """Stop pan/edge sessions before a canvas-toggle.

        A live pan keeps applying baseline+delta moves to floating windows,
        which would fight the toggle Lua dispatched right after (same
        windows, absolute writes, one frame apart). Clearing first makes
        the toggle outcome deterministic.
        """
        if self.panning.is_dragging:
            self.panning.stop_pan()
            self.baselines = {}
            self.baseline_workspace = None
            self.baseline_zoom = 1.0
            debug.dbg2("MODE_SWITCH", to=to, stopped="pan")
        if self.edge_scroll.active:
            self.edge_scroll.stop()
            self.edge_scroll_workspace = None
            self.edge_scroll.set_viewport(1.0, 0.0, 0.0)
            debug.dbg2("MODE_SWITCH", to=to, stopped="edge")

    def _handle_canvas_toggle(self, workspace_id: int | None = None) -> str:
        self._stop_competing_modes("canvas-toggle")
        return self.navigator.canvas_toggle(workspace_id)

    def _handle_canvas_toggle_all(self, workspace_id: int | None = None) -> str:
        self._stop_competing_modes("canvas-toggle")
        return self.navigator.canvas_toggle_all(workspace_id)

    def _handle_canvas_toggle_single(self) -> str:
        self._stop_competing_modes("canvas-toggle")
        return self.navigator.canvas_toggle_single()

    def _handle_ping(self) -> str:
        return "PONG"

    def _handle_status(self) -> str:
        inv = "INVERTED" if self.panning.inverted else "NORMAL"
        pan = "PANNING" if self.panning.is_dragging else "IDLE"
        return f"{inv} {pan}"

    def handle_idle_pan_stop(self) -> bool:
        """Auto-stop panning after cursor idle; drop baselines.

        Baselines must die together with the pan: keeping them after an
        idle timeout would make a later shutdown restore windows to
        long-stale pre-pan positions, silently destroying layout changes
        the user made in between.
        """
        stopped = self.panning.check_idle_timeout()
        if stopped:
            self.baselines = {}
        return stopped

    def fetch_baselines(self) -> bool:
        """Snapshot floating windows of the ACTIVE workspace as pan baselines."""
        try:
            ws_resp = self.ipc.send("j/activeworkspace")
            ws: dict[str, Any] = json.loads(ws_resp)
            workspace_id = int(ws["id"])

            resp = self.ipc.send("j/clients")
            clients = json.loads(resp)
            baselines: dict[str, tuple[int, int]] = {}
            for w in clients:
                if not w.get("floating"):
                    continue
                wsw = w.get("workspace")
                if not isinstance(wsw, dict) or wsw.get("id") != workspace_id:
                    continue
                addr = w.get("address", "")
                at = w.get("at", [0, 0])
                if addr and len(at) >= 2:
                    baselines[addr] = (at[0], at[1])
            self.baselines = baselines
            self.baseline_workspace = workspace_id
            viewport = self._canvas_viewport(workspace_id)
            self.baseline_zoom = viewport.zoom if viewport.enabled else 1.0
            return True
        except Exception as e:
            log.warning("fetch baselines failed: %s", e)
            self.baselines = {}
            self.baseline_workspace = None
            self.baseline_zoom = 1.0
            return False

    def restore_baselines(self) -> None:
        """Move the snapshot's windows back to their pre-pan positions.

        Called on graceful shutdown so windows don't stay displaced.
        """
        if not self.baselines or self.baseline_workspace is None:
            return
        try:
            ws_id = int(self.baseline_workspace)
            lines = [
                LUA_DISPATCH_HELPER,
                f"local ws = hl.get_windows({{ floating = true, workspace = {ws_id} }})",
            ]
            lines.append("local bd = {")
            for addr, (bx, by) in self.baselines.items():
                safe_addr = _lua_escape(addr)
                lines.append(f'  ["{safe_addr}"] = {{{bx}, {by}}},')
            lines.append("}")
            lines.append("for _, w in ipairs(ws) do")
            lines.append("  local b = bd[tostring(w.address)]")
            lines.append("  if b then")
            lines.append(
                "    _canvas_dispatch(hl.dispatch(hl.dsp.window.move({"
                " x = b[1], y = b[2],"
                " relative = false, window = w })))"
            )
            lines.append("  end")
            lines.append("end")
            self.ipc.eval_lua("\n".join(lines))
            log.info("restored %d windows to pre-pan positions", len(self.baselines))
        except Exception as e:
            log.warning("restore baselines failed: %s", e)

    def move_windows_to_delta(self, total_dx: int, total_dy: int) -> None:
        """Move the workspace's floating windows to baseline + total_delta.

        Absolute positioning against the snapshot; scoped to the workspace
        captured at PAN_START.
        """
        if not self.baselines or self.baseline_workspace is None:
            return
        try:
            ws_id = int(self.baseline_workspace)
            zoom = self.baseline_zoom if self.baseline_zoom > 0 else 1.0
            world_dx = int(round(total_dx / zoom))
            world_dy = int(round(total_dy / zoom))
            lines = [
                LUA_DISPATCH_HELPER,
                f"local ws = hl.get_windows({{ floating = true, workspace = {ws_id} }})",
            ]
            lines.append("local bd = {")
            for addr, (bx, by) in self.baselines.items():
                safe_addr = _lua_escape(addr)
                lines.append(f'  ["{safe_addr}"] = {{{bx}, {by}}},')
            lines.append("}")
            lines.append("for _, w in ipairs(ws) do")
            lines.append("  local b = bd[tostring(w.address)]")
            lines.append("  if b then")
            lines.append(
                f"    _canvas_dispatch(hl.dispatch(hl.dsp.window.move({{"
                f" x = b[1] + {world_dx},"
                f" y = b[2] + {world_dy},"
                f" relative = false, window = w }})))"
            )
            lines.append("  end")
            lines.append("end")
            self.ipc.eval_lua("\n".join(lines))
        except Exception as e:
            log.warning("window move failed: %s", e)

    def edge_scroll_move(self, dx: int, dy: int) -> None:
        """Move all floating windows EXCEPT the dragged one by (dx, dy) relative.

        Camera follows the dragged window: other windows move opposite.
        Cursor at right edge → camera right → other windows move left.
        Scoped to the workspace active at EDGE_START.
        """
        if dx == 0 and dy == 0:
            return
        if self.edge_scroll_workspace is None:
            log.warning("edge-scroll move skipped: no workspace captured")
            return
        ws_id = int(self.edge_scroll_workspace)
        dragged = self.edge_scroll.dragged_addr
        zoom = self.edge_scroll.viewport_zoom
        if zoom <= 0:
            zoom = 1.0
        dx = int(round(dx / zoom))
        dy = int(round(dy / zoom))
        try:
            safe_addr = _lua_escape(dragged)
            lua = (
                f"{LUA_DISPATCH_HELPER}\n"
                f"local ws = hl.get_windows({{ floating = true, workspace = {ws_id} }})\n"
                f"for _, w in ipairs(ws) do\n"
                f'  if tostring(w.address) ~= "{safe_addr}" then\n'
                f"    _canvas_dispatch(hl.dispatch(hl.dsp.window.move({{"
                f" x = {dx}, y = {dy},"
                f" relative = true, window = w }})))\n"
                f"  end\n"
                f"end\n"
            )
            self.ipc.eval_lua(lua)
        except Exception as e:
            log.warning("edge-scroll move failed: %s", e)


def run() -> None:
    """Main entry point for the canvas daemon."""
    debug.enable_from_env()
    logging.basicConfig(
        level=logging.DEBUG if debug.enabled() else logging.INFO,
        format="%(name)s: %(message)s",
    )
    if debug.enabled():
        import os

        debug.dbg("BOOT", pid=os.getpid())

    log.info("loading config...")
    cfg = load()

    ipc = HyprIPC.from_env()
    state = PanningState(speed=cfg["speed"], max_speed=cfg.get("max_speed"))
    state.inverted = cfg["invert"]["enabled"]

    edge_cfg = cfg.get("edge_scroll", {})
    edge_scroll = EdgeScrollState(
        ramp_distance=edge_cfg.get("ramp_distance", 50),
        speed=edge_cfg.get("speed", 20.0),
        max_speed=edge_cfg.get("max_speed"),
        enabled=edge_cfg.get("enabled", True),
        grab_dead_zone=edge_cfg.get("grab_dead_zone", 5),
    )

    canvas_cfg = cfg.get("canvas", {})
    navigator = Navigator(
        ipc=ipc,
        protected_apps=cfg["navigation"]["protected_apps"],
        cooldown=cfg["navigation"]["cooldown"],
        preserve_geometry=bool(canvas_cfg.get("preserve_geometry", True)),
    )
    navigator.sync_canvas_viewports()

    daemon_state = DaemonState(
        panning=state, edge_scroll=edge_scroll, navigator=navigator, ipc=ipc
    )

    ipc_server = IpcServer(handler=daemon_state.handle_ipc)

    acquire_singleton(ipc_server.sock_path)

    stop_event = threading.Event()

    def _shutdown(signum: int, _frame: object) -> None:
        log.info("received signal %d, shutting down...", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _shutdown)

    ipc_thread = threading.Thread(target=ipc_server.serve, daemon=True)
    ipc_thread.start()

    cursor_thread = threading.Thread(
        target=cursor_poller, args=(state, edge_scroll, stop_event), daemon=True
    )
    cursor_thread.start()

    event_listener = EventListener(navigator, ipc, stop_event)
    event_listener.start()

    log.info("ready — SUPER+SHIFT+LMB to pan, SUPER+LMB to edge-scroll")

    target_interval = 1.0 / 60.0
    prev_time = time.monotonic()

    poller_died = False
    try:
        prev_total = (0, 0)
        while not stop_event.is_set():
            with daemon_state._operation_lock:
                daemon_state.handle_idle_pan_stop()

                if not state.pan_active:
                    prev_total = (0, 0)
                else:
                    total_dx, total_dy = state.get_total_delta()
                    if (
                        total_dx,
                        total_dy,
                    ) != (0, 0) and (total_dx, total_dy) != prev_total:
                        prev_total = (total_dx, total_dy)
                        try:
                            daemon_state.move_windows_to_delta(total_dx, total_dy)
                        except Exception as e:
                            log.warning("window move failed: %s", e)

                edge_scroll.check_idle_timeout()
                if edge_scroll.active:
                    es_dx, es_dy = edge_scroll.consume_delta()
                    if es_dx != 0 or es_dy != 0:
                        daemon_state.edge_scroll_move(es_dx, es_dy)

            if not state.poller_alive:
                poller_died = True
                log.error("cursor poller died — cannot track cursor position")
                break

            now = time.monotonic()
            elapsed = now - prev_time
            time.sleep(max(0, target_interval - elapsed))
            prev_time = time.monotonic()

    except KeyboardInterrupt as exc:
        log.info("shutting down: %s", exc)
    finally:
        stop_event.set()
        event_listener.stop()
        ipc_server.stop()
        cursor_thread.join(timeout=1)
        ipc_thread.join(timeout=1)
        with daemon_state._operation_lock:
            daemon_state.restore_baselines()

    if poller_died:
        # Exit non-zero so a supervisor (e.g. systemd Restart=on-failure)
        # restarts the daemon instead of leaving a zombie that answers
        # ping but can never pan again.
        raise SystemExit(1)
