"""Navigate between floating windows on the infinite canvas."""

import json
import logging
import re
import time
from typing import Any

from canvas import debug, toggle_state
from canvas.hypr import LUA_DISPATCH_HELPER, HyprIPC

log = logging.getLogger("canvas.navigation")

_VALID_ADDR = re.compile(r"^0x[0-9a-fA-F]+$")


def _safe_int(value: object, name: str) -> int:
    """Coerce to int, raising ValueError if impossible.

    Prevents accidental string interpolation into Lua — all values
    inserted into Lua f-strings MUST pass through this or _VALID_ADDR.
    """
    try:
        result: int = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsafe Lua value: {name}={value!r}") from exc
    return result


class Navigator:
    """Handles navigation between floating windows with auto-pan."""

    def __init__(
        self,
        ipc: HyprIPC,
        protected_apps: list[str],
        cooldown: float = 0.2,
        preserve_geometry: bool = True,
    ) -> None:
        self._ipc = ipc
        self._protected_apps = [a.lower() for a in protected_apps]
        self._cooldown = cooldown
        self._preserve_geometry = preserve_geometry
        self._last_nav_time = 0.0
        # workspace id -> snapshot of TILED windows before canvas ON.
        # Only these are tiled again on OFF, so windows that were already
        # floating before canvas mode survive.
        # workspace id -> last known FLOATING geometry per address.
        # Reapplied on the next ON so the canvas comes back where it was.
        self._canvas_mode_workspaces: dict[int, dict[str, dict[str, list[int]]]] = {}
        self._floating_geos: dict[int, dict[str, dict[str, list[int]]]] = {}
        # workspace id -> addresses of windows that were converted to floating
        # during this Canvas session (spawned during Canvas ON).
        # These should be tiled again on Canvas OFF.
        self._spawned_during_canvas: dict[int, set[str]] = {}
        raw = toggle_state.load()
        for ws, sections in raw.items():
            if isinstance(sections, list):
                # Legacy mocked load in tests: bare address list = tiled set
                self._canvas_mode_workspaces[ws] = {
                    str(a): {} for a in sections if isinstance(a, str)
                }
            elif isinstance(sections, dict) and (
                "active" in sections or "tiled" in sections or "floating" in sections
            ):
                tiled = sections.get("tiled", {})
                floating = sections.get("floating", {})
                if not isinstance(tiled, dict):
                    tiled = {}
                if not isinstance(floating, dict):
                    floating = {}
                active = sections.get("active", bool(tiled))
                if active is True:
                    self._canvas_mode_workspaces[ws] = dict(tiled)
                if floating:
                    self._floating_geos[ws] = dict(floating)
            elif isinstance(sections, dict):
                # Legacy v1 dict (addr->geo of tiled slots): keep addresses
                # for targeting, drop geometry (tiled slots are layout-owned).
                addrs: dict[str, dict[str, list[int]]] = {
                    a: {} for a in sections if isinstance(a, str)
                }
                if addrs:
                    self._canvas_mode_workspaces[ws] = addrs
            else:
                self._canvas_mode_workspaces[ws] = {}
        if debug.enabled():
            debug.dbg2(
                "STATE_LOAD",
                workspaces=sorted(raw.keys()),
                tiled={ws: len(s) for ws, s in self._canvas_mode_workspaces.items()},
                floating={ws: len(s) for ws, s in self._floating_geos.items()},
                preserve_geometry=self._preserve_geometry,
            )

    def is_canvas_active(self, workspace_id: int) -> bool:
        """Check if Canvas mode is active for a workspace."""
        return workspace_id in self._canvas_mode_workspaces

    def register_spawned_during_canvas(self, workspace_id: int, addr: str) -> None:
        """Register a window that was converted to floating during Canvas ON."""
        if workspace_id not in self._spawned_during_canvas:
            self._spawned_during_canvas[workspace_id] = set()
        self._spawned_during_canvas[workspace_id].add(addr)

    def unregister_window(self, addr: str) -> None:
        """Remove a window from all tracking state (closewindow event)."""
        for ws_id in list(self._canvas_mode_workspaces):
            self._canvas_mode_workspaces[ws_id].pop(addr, None)
        for ws_id in list(self._floating_geos):
            self._floating_geos[ws_id].pop(addr, None)
        for ws_id in list(self._spawned_during_canvas):
            self._spawned_during_canvas[ws_id].discard(addr)

    def get_spawn_geometry(self, workspace_id: int) -> tuple[int, int] | None:
        """Calculate spawn geometry for a new window during Canvas ON.

        Returns (width, height) based on median of original tiled windows,
        or None if no snapshot available.
        """
        snapshot = self._canvas_mode_workspaces.get(workspace_id, {})
        if not snapshot:
            return None
        widths = []
        heights = []
        for geo in snapshot.values():
            if isinstance(geo, dict) and geo:
                size = geo.get("size")
                if size and len(size) == 2:
                    widths.append(size[0])
                    heights.append(size[1])
        if not widths or not heights:
            return None
        widths.sort()
        heights.sort()
        mid_w = widths[len(widths) // 2]
        mid_h = heights[len(heights) // 2]
        return mid_w, mid_h

    @staticmethod
    def _window_center(w: dict[str, Any]) -> tuple[int, int]:
        return w["at"][0] + w["size"][0] // 2, w["at"][1] + w["size"][1] // 2

    @staticmethod
    def _window_bounds(w: dict[str, Any]) -> dict[str, int]:
        x, y = w["at"][0], w["at"][1]
        ww, wh = w["size"][0], w["size"][1]
        return {
            "left": x,
            "right": x + ww,
            "top": y,
            "bottom": y + wh,
            "center_x": x + ww // 2,
            "center_y": y + wh // 2,
        }

    @staticmethod
    def _overlap_h(b1: dict[str, int], b2: dict[str, int]) -> bool:
        return not (b1["right"] <= b2["left"] or b1["left"] >= b2["right"])

    @staticmethod
    def _overlap_v(b1: dict[str, int], b2: dict[str, int]) -> bool:
        return not (b1["bottom"] <= b2["top"] or b1["top"] >= b2["bottom"])

    def _find_spatial_target(
        self,
        floating: list[dict[str, Any]],
        current_bounds: dict[str, int],
        current_center: tuple[int, int],
        direction: str,
    ) -> dict[str, Any] | None:
        cx, cy = current_center
        candidates = [w for w in floating if not self._is_protected(w)]
        if not candidates:
            return None

        # Tier 1: overlapping band + direction
        aligned: list[tuple[dict[str, Any], int]] = []
        for w in candidates:
            b = self._window_bounds(w)
            wx, wy = b["center_x"], b["center_y"]
            if direction == "left" and self._overlap_v(current_bounds, b) and wx < cx:
                aligned.append((w, cx - wx))
            elif direction == "right" and self._overlap_v(current_bounds, b) and wx > cx:
                aligned.append((w, wx - cx))
            elif direction == "up" and self._overlap_h(current_bounds, b) and wy < cy:
                aligned.append((w, cy - wy))
            elif direction == "down" and self._overlap_h(current_bounds, b) and wy > cy:
                aligned.append((w, wy - cy))
        if aligned:
            return sorted(aligned, key=lambda x: x[1])[0][0]

        # Tier 2: any window in direction
        same_dir: list[tuple[dict[str, Any], int]] = []
        for w in candidates:
            b = self._window_bounds(w)
            wx, wy = b["center_x"], b["center_y"]
            if direction == "left" and wx < cx:
                same_dir.append((w, cx - wx))
            elif direction == "right" and wx > cx:
                same_dir.append((w, wx - cx))
            elif direction == "up" and wy < cy:
                same_dir.append((w, cy - wy))
            elif direction == "down" and wy > cy:
                same_dir.append((w, wy - cy))
        if same_dir:
            return sorted(same_dir, key=lambda x: x[1])[0][0]

        # Tier 3: wrap — farthest in opposite direction
        opp = {"left": "right", "right": "left", "up": "down", "down": "up"}[direction]
        wrap: list[tuple[dict[str, Any], int]] = []
        for w in candidates:
            b = self._window_bounds(w)
            wx, wy = b["center_x"], b["center_y"]
            if opp == "left" and wx < cx:
                wrap.append((w, cx - wx))
            elif opp == "right" and wx > cx:
                wrap.append((w, wx - cx))
            elif opp == "up" and wy < cy:
                wrap.append((w, cy - wy))
            elif opp == "down" and wy > cy:
                wrap.append((w, wy - cy))
        if wrap:
            return sorted(wrap, key=lambda x: x[1])[0][0]
        return None

    def navigate(self, direction: str) -> bool:
        """Navigate to the nearest floating window. False only on IPC failure."""
        current_time = time.monotonic()
        if current_time - self._last_nav_time < self._cooldown:
            return True
        self._last_nav_time = current_time

        workspace_id = self._get_active_workspace_id()
        if workspace_id is None:
            return False

        floating = self._get_floating_windows(workspace_id)
        if floating is None:
            return False
        if len(floating) <= 1:
            return True

        focused = self._get_focused_window()
        if focused is None:
            return False
        if "address" not in focused:
            return True

        current_addr = focused["address"]
        current_win = next((w for w in floating if w["address"] == current_addr), None)
        if current_win is None:
            return True

        current_bounds = self._window_bounds(current_win)
        current_center = self._window_center(current_win)

        target = self._find_spatial_target(floating, current_bounds, current_center, direction)
        # Fallback: circular index order (legacy behavior) when no spatial candidate
        target_addr: str | None = None
        if target is not None:
            target_addr = target["address"]
        else:
            # No window in that direction spatially — cycle by index (protected-aware)
            current_index = next(
                (i for i, w in enumerate(floating) if w["address"] == current_addr), -1
            )
            if current_index != -1:
                idx = current_index
                for _ in range(len(floating)):
                    if direction in ("right", "down"):
                        idx = (idx + 1) % len(floating)
                    else:
                        idx = (idx - 1) % len(floating)
                    if not self._is_protected(floating[idx]):
                        target_addr = floating[idx]["address"]
                        break

        if target_addr is None:
            return True

        center = self._get_monitor_center()
        if center is None:
            return False
        floating_updated = self._get_floating_windows(workspace_id)
        if floating_updated is None:
            return False
        center_x, center_y = center
        return self._pan_to_window(floating_updated, target_addr, center_x, center_y, workspace_id)

    def _persist_canvas_state(
        self,
        canvas_modes: dict[int, dict[str, dict[str, list[int]]]],
        floating_geos: dict[int, dict[str, dict[str, list[int]]]],
    ) -> None:
        workspaces = set(canvas_modes) | set(floating_geos)
        state: toggle_state.State = {}
        for ws in workspaces:
            if ws not in canvas_modes and ws not in floating_geos:
                continue
            state[ws] = {
                "active": ws in canvas_modes,
                "tiled": dict(canvas_modes.get(ws, {})),
                "floating": dict(floating_geos.get(ws, {})),
            }
        toggle_state.save(state)

    def canvas_toggle(self) -> str:
        # Backward-compat alias — single word `canvas-toggle` still means "all"
        return self.canvas_toggle_all()

    def canvas_toggle_all(self) -> str:
        workspace_id = self._get_active_workspace_id()
        if workspace_id is None:
            return "ERROR:NO_WORKSPACE"

        if workspace_id in self._canvas_mode_workspaces:
            snapshot = self._canvas_mode_workspaces[workspace_id]
            captured: dict[str, dict[str, list[int]]] = {}
            if self._preserve_geometry and snapshot:
                snapshot_result = self._snapshot_floating_geos(workspace_id, set(snapshot.keys()))
                if snapshot_result is None:
                    return "ERROR:SNAPSHOT_FAILED"
                captured = snapshot_result

            # Also include spawned-during-canvas windows in the tile operation
            spawned = self._spawned_during_canvas.get(workspace_id, set())
            all_to_tile = dict(snapshot)
            for addr in spawned:
                if addr not in all_to_tile:
                    all_to_tile[addr] = {}

            next_modes = dict(self._canvas_mode_workspaces)
            next_modes.pop(workspace_id, None)
            next_floating = dict(self._floating_geos)
            if self._preserve_geometry and captured:
                next_floating[workspace_id] = captured
            elif not self._preserve_geometry:
                next_floating.pop(workspace_id, None)

            # Persist the target state first. A persistence failure therefore
            # cannot leave the compositor tiled while memory still says ON.
            try:
                self._persist_canvas_state(next_modes, next_floating)
            except toggle_state.ToggleStateError as e:
                log.warning("canvas OFF state save failed: %s", e)
                return "ERROR:STATE_SAVE_FAILED"

            if all_to_tile and not self._tile_windows(workspace_id, all_to_tile):
                compositor_rollback = self._set_snapshot_floating(
                    workspace_id, all_to_tile, floating=True
                )
                if captured:
                    compositor_rollback = (
                        self._apply_floating_geos(workspace_id, captured) and compositor_rollback
                    )
                state_rollback = True
                try:
                    self._persist_canvas_state(self._canvas_mode_workspaces, self._floating_geos)
                except toggle_state.ToggleStateError as e:
                    log.error("canvas OFF state rollback failed: %s", e)
                    state_rollback = False
                if not state_rollback and not compositor_rollback:
                    return "ERROR:STATE_AND_COMPOSITOR_ROLLBACK_FAILED"
                if not state_rollback:
                    return "ERROR:STATE_ROLLBACK_FAILED"
                if not compositor_rollback:
                    return "ERROR:COMPOSITOR_ROLLBACK_FAILED"
                return "ERROR:TILE_FAILED"

            self._canvas_mode_workspaces = next_modes
            self._floating_geos = next_floating
            # Clear spawned tracking for this workspace
            self._spawned_during_canvas.pop(workspace_id, None)
            if debug.enabled():
                debug.dbg2(
                    "TOGGLE_OFF",
                    ws=workspace_id,
                    count=len(snapshot),
                    addrs=sorted(snapshot.keys()),
                )
                if debug.level() >= 2:
                    geos = {a: snapshot[a] for a in sorted(snapshot.keys())}
                    debug.dbg2("TOGGLE_OFF_DETAIL", ws=workspace_id, geos=geos)
            return "CANVAS_OFF"

        tiled_snapshot = self._snapshot_tiled_windows(workspace_id)
        if tiled_snapshot is None:
            return "ERROR:SNAPSHOT_FAILED"
        next_modes = dict(self._canvas_mode_workspaces)
        next_modes[workspace_id] = tiled_snapshot
        next_floating = dict(self._floating_geos)

        # Restore-on-ON can also target windows that were already floating and
        # therefore are absent from tiled_snapshot. Capture those separately so
        # a partial geometry failure can roll them back too.
        rollback_addresses = set(self._floating_geos.get(workspace_id, {})) - set(tiled_snapshot)
        rollback_geos: dict[str, dict[str, list[int]]] = {}
        if rollback_addresses:
            rollback_result = self._snapshot_floating_geos(workspace_id, rollback_addresses)
            if rollback_result is None:
                return "ERROR:SNAPSHOT_FAILED"
            rollback_geos = rollback_result

        try:
            self._persist_canvas_state(next_modes, next_floating)
        except toggle_state.ToggleStateError as e:
            log.warning("canvas ON state save failed: %s", e)
            return "ERROR:STATE_SAVE_FAILED"

        if not self._set_all_floating(workspace_id, floating=True):
            failure = "ERROR:FLOAT_FAILED"
        elif (
            not self._restore_tiled_geometry_as_floating(workspace_id, tiled_snapshot)
            or not self._restore_floating_geos(
                workspace_id, exclude_addresses=set(tiled_snapshot.keys())
            )
        ):
            failure = "ERROR:GEOMETRY_RESTORE_FAILED"
        else:
            failure = ""
        if failure:
            compositor_rollback = self._set_snapshot_floating(
                workspace_id, tiled_snapshot, floating=False
            )
            if rollback_geos:
                compositor_rollback = (
                    self._apply_floating_geos(workspace_id, rollback_geos) and compositor_rollback
                )
            state_rollback = True
            try:
                self._persist_canvas_state(self._canvas_mode_workspaces, self._floating_geos)
            except toggle_state.ToggleStateError as e:
                log.error("canvas ON state rollback failed: %s", e)
                state_rollback = False
            if not state_rollback and not compositor_rollback:
                return "ERROR:STATE_AND_COMPOSITOR_ROLLBACK_FAILED"
            if not state_rollback:
                return "ERROR:STATE_ROLLBACK_FAILED"
            if not compositor_rollback:
                return "ERROR:COMPOSITOR_ROLLBACK_FAILED"
            return failure

        self._canvas_mode_workspaces = next_modes
        self._floating_geos = next_floating
        if debug.enabled():
            debug.dbg2(
                "TOGGLE_ON",
                ws=workspace_id,
                count=len(tiled_snapshot),
                addrs=sorted(tiled_snapshot.keys()),
                preserve_geometry=self._preserve_geometry,
            )
            if debug.level() >= 2 and tiled_snapshot:
                debug.dbg2("TOGGLE_ON_DETAIL", ws=workspace_id, geos=tiled_snapshot)
        return "CANVAS_ON"

    def canvas_toggle_single(self) -> str:
        focused = self._get_focused_window()
        if focused is None or "address" not in focused:
            return "ERROR:NO_FOCUS"
        addr = str(focused["address"])
        if not _VALID_ADDR.match(addr):
            return "ERROR:BAD_ADDRESS"
        was_floating = bool(focused.get("floating"))
        try:
            lua = (
                f"{LUA_DISPATCH_HELPER}\n"
                f"local w = nil\n"
                f"for _, win in ipairs(hl.get_windows({{}})) do\n"
                f'  if tostring(win.address) == "{addr}" then w = win; break end\n'
                f"end\n"
                f"if w then _canvas_dispatch(hl.dispatch(hl.dsp.window.float({{"
                f' action = "toggle", window = w }}))) end'
            )
            self._ipc.eval_lua(lua)
        except Exception as e:
            log.warning("toggle single failed: %s", e)
            return "ERROR:TOGGLE_FAILED"
        return "TILED" if was_floating else "FLOATED"

    def _snapshot_tiled_windows(self, workspace_id: int) -> dict[str, dict[str, list[int]]] | None:
        """Snapshot of currently tiled windows on the workspace (pre-canvas state).

        When preserve_geometry is true, each entry stores at/size. Tiled
        coordinates are informational only (placement is layout-owned) and
        feed the row-major toggle order in _tile_windows.
        """
        try:
            resp = self._ipc.send("j/clients")
            clients: list[dict[str, Any]] = json.loads(resp)
            snap: dict[str, dict[str, list[int]]] = {}
            debug_details: dict[str, dict[str, Any]] = {} if debug.level() >= 2 else {}  # type: ignore[assignment]
            for w in clients:
                if w.get("floating"):
                    continue
                addr = w.get("address")
                if not addr or not isinstance(addr, str):
                    continue
                wsw = w.get("workspace")
                if not isinstance(wsw, dict) or wsw.get("id") != workspace_id:
                    continue
                if self._preserve_geometry:
                    at = w.get("at", [0, 0])
                    size = w.get("size", [0, 0])
                    try:
                        snap[addr] = {
                            "at": [int(at[0]), int(at[1])],
                            "size": [int(size[0]), int(size[1])],
                        }
                    except Exception:
                        snap[addr] = {}
                else:
                    snap[addr] = {}
                if debug.level() >= 2:
                    at = w.get("at", [0, 0])
                    size = w.get("size", [0, 0])
                    debug_details[addr] = {
                        "at": at,
                        "size": size,
                        "class": str(w.get("class", ""))[:40],
                        "title": str(w.get("title", ""))[:40],
                    }
            if debug.enabled():
                debug.dbg2(
                    "SNAPSHOT_CREATE",
                    ws=workspace_id,
                    count=len(snap),
                    addrs=sorted(snap.keys()),
                    preserve_geometry=self._preserve_geometry,
                )
                if debug.level() >= 2 and debug_details:
                    debug.dbg2("SNAPSHOT_CREATE_DETAIL", ws=workspace_id, details=debug_details)
            return snap
        except Exception as e:
            log.warning("snapshot tiled windows failed: %s", e)
            return None

    def _snapshot_floating_geos(
        self, workspace_id: int, addresses: set[str] | None = None
    ) -> dict[str, dict[str, list[int]]] | None:
        """Capture current FLOATING geometry for the given addresses.

        Unlike tiled slots (layout-owned), floating positions are
        authoritative — move/resize applies them exactly. These are the
        coordinates the next canvas ON restores. If addresses is None, capture
        every floating window on the workspace.
        """
        try:
            resp = self._ipc.send("j/clients")
            clients: list[dict[str, Any]] = json.loads(resp)
            geos: dict[str, dict[str, list[int]]] = {}
            for w in clients:
                if not w.get("floating"):
                    continue
                addr = w.get("address")
                if not isinstance(addr, str) or (addresses is not None and addr not in addresses):
                    continue
                wsw = w.get("workspace")
                if not isinstance(wsw, dict) or wsw.get("id") != workspace_id:
                    continue
                at = w.get("at", [0, 0])
                size = w.get("size", [0, 0])
                try:
                    geos[addr] = {
                        "at": [int(at[0]), int(at[1])],
                        "size": [int(size[0]), int(size[1])],
                    }
                except Exception:
                    continue
            if debug.enabled():
                debug.dbg2(
                    "FLOATING_SNAPSHOT",
                    ws=workspace_id,
                    count=len(geos),
                    addrs=sorted(geos.keys()),
                    geos=geos,
                )
            return geos
        except Exception as e:
            log.warning("snapshot floating geos failed: %s", e)
            return None

    def _restore_floating_geos(
        self, workspace_id: int, exclude_addresses: set[str] | None = None
    ) -> bool:
        """Move newly floated snapshot windows to stored floating geometry.

        Excludes addresses present in exclude_addresses (e.g., windows that
        were tiled and are now handled by the tiled snapshot geometry).
        """
        if not self._preserve_geometry:
            return True
        stored = self._floating_geos.get(workspace_id, {})
        return self._apply_floating_geos(workspace_id, stored, exclude_addresses)

    def _restore_tiled_geometry_as_floating(
        self, workspace_id: int, tiled_snapshot: dict[str, dict[str, list[int]]]
    ) -> bool:
        """Apply tiled snapshot geometry to newly-floated windows.

        Ensures windows that were tiled keep their exact visual geometry
        when entering canvas mode, rather than inheriting old canvas geometry
        or Hyprland's default floating placement.
        """
        if not self._preserve_geometry or not tiled_snapshot:
            return True
        try:
            resp = self._ipc.send("j/clients")
            clients: list[dict[str, Any]] = json.loads(resp)
            live = {
                str(w.get("address"))
                for w in clients
                if w.get("floating")
                and isinstance(w.get("workspace"), dict)
                and w.get("workspace", {}).get("id") == workspace_id
            }
        except Exception as e:
            log.warning("restore tiled geometry failed: %s", e)
            return False
        targets: dict[str, dict[str, list[int]]] = {}
        for addr in sorted(tiled_snapshot):
            if addr not in live or not _VALID_ADDR.match(addr):
                continue
            geo = tiled_snapshot[addr]
            if not isinstance(geo, dict) or not geo:
                continue
            try:
                at = [int(geo.get("at", [0, 0])[0]), int(geo.get("at", [0, 0])[1])]
                size = [int(geo.get("size", [0, 0])[0]), int(geo.get("size", [0, 0])[1])]
            except Exception:
                continue
            if at == [0, 0] and size == [0, 0]:
                continue
            targets[addr] = {"at": at, "size": size}
        if not targets:
            return True
        lines = [LUA_DISPATCH_HELPER, "local geos = {"]
        for addr, geo in targets.items():
            ax, ay = geo["at"]
            sw, sh = geo["size"]
            lines.append(f'  ["{addr}"] = {{at={{{ax},{ay}}}, size={{{sw},{sh}}}}},')
        lines.append("}")
        lines.append(
            f"local ws = hl.get_windows({{ floating = true, "
            f"workspace = {_safe_int(workspace_id, 'workspace_id')} }})"
        )
        lines.append("for _, w in ipairs(ws) do")
        lines.append("  local g = geos[tostring(w.address)]")
        lines.append("  if g then")
        lines.append(
            "    _canvas_dispatch(hl.dispatch(hl.dsp.window.resize({"
            " x = g.size[1], y = g.size[2], relative = false, window = w })))"
        )
        lines.append(
            "    _canvas_dispatch(hl.dispatch(hl.dsp.window.move({"
            " x = g.at[1], y = g.at[2], relative = false, window = w })))"
        )
        lines.append("  end")
        lines.append("end")
        if debug.enabled():
            debug.dbg2(
                "TILED_GEOMETRY_RESTORE",
                ws=workspace_id,
                count=len(targets),
                applied={a: targets[a] for a in sorted(targets)},
            )
        try:
            self._ipc.eval_lua("\n".join(lines))
            return True
        except Exception as e:
            log.warning("restore tiled geometry failed: %s", e)
            return False

    def _apply_floating_geos(
        self,
        workspace_id: int,
        stored: dict[str, dict[str, list[int]]],
        exclude_addresses: set[str] | None = None,
    ) -> bool:
        """Apply known floating geometry to live windows on one workspace."""
        if not stored:
            return True
        if exclude_addresses is None:
            exclude_addresses = set()
        try:
            resp = self._ipc.send("j/clients")
            clients: list[dict[str, Any]] = json.loads(resp)
            live = {
                str(w.get("address"))
                for w in clients
                if w.get("floating")
                and isinstance(w.get("workspace"), dict)
                and w.get("workspace", {}).get("id") == workspace_id
            }
        except Exception as e:
            log.warning("restore floating geos failed: %s", e)
            return False
        targets: dict[str, dict[str, list[int]]] = {}
        for addr in sorted(stored):
            if addr in exclude_addresses:
                continue
            if addr not in live or not _VALID_ADDR.match(addr):
                continue
            geo = stored[addr]
            if not isinstance(geo, dict):
                continue
            try:
                at = [int(geo.get("at", [0, 0])[0]), int(geo.get("at", [0, 0])[1])]
                size = [int(geo.get("size", [0, 0])[0]), int(geo.get("size", [0, 0])[1])]
            except Exception:
                continue
            if at == [0, 0] and size == [0, 0]:
                continue
            targets[addr] = {"at": at, "size": size}
        if not targets:
            return True
        lines = [LUA_DISPATCH_HELPER, "local geos = {"]
        for addr, geo in targets.items():
            ax, ay = geo["at"]
            sw, sh = geo["size"]
            lines.append(f'  ["{addr}"] = {{at={{{ax},{ay}}}, size={{{sw},{sh}}}}},')
        lines.append("}")
        lines.append(
            f"local ws = hl.get_windows({{ floating = true, "
            f"workspace = {_safe_int(workspace_id, 'workspace_id')} }})"
        )
        lines.append("for _, w in ipairs(ws) do")
        lines.append("  local g = geos[tostring(w.address)]")
        lines.append("  if g then")
        lines.append(
            "    _canvas_dispatch(hl.dispatch(hl.dsp.window.resize({"
            " x = g.size[1], y = g.size[2], relative = false, window = w })))"
        )
        lines.append(
            "    _canvas_dispatch(hl.dispatch(hl.dsp.window.move({"
            " x = g.at[1], y = g.at[2], relative = false, window = w })))"
        )
        lines.append("  end")
        lines.append("end")
        if debug.enabled():
            debug.dbg2(
                "FLOAT_RESTORE",
                ws=workspace_id,
                count=len(targets),
                applied={a: targets[a] for a in sorted(targets)},
            )
        try:
            self._ipc.eval_lua("\n".join(lines))
            return True
        except Exception as e:
            log.warning("restore floating geos failed: %s", e)
            return False

    @staticmethod
    def _toggle_order(snapshot: dict[str, dict[str, list[int]]]) -> list[str]:
        """Order snapshot addresses for tiling: row-major by saved position.

        The compositor rebuilds the tiled layout in toggle order, so feeding
        top-to-bottom, left-to-right approximates the original grid. Entries
        without usable coordinates fall back to plain address order.
        """
        positioned: list[tuple[int, int, str]] = []
        plain: list[str] = []
        for addr in snapshot:
            if not _VALID_ADDR.match(addr):
                continue
            geo = snapshot.get(addr, {})
            at = geo.get("at") if isinstance(geo, dict) else None
            try:
                y, x = int(at[1]), int(at[0])  # type: ignore[index]
                positioned.append((y, x, addr))
            except Exception:
                plain.append(addr)
        positioned.sort()
        return [a for _, _, a in positioned] + sorted(plain)

    def _set_snapshot_floating(
        self,
        workspace_id: int,
        snapshot: dict[str, dict[str, list[int]]],
        floating: bool,
    ) -> bool:
        """Set an exact snapshot to floating/tiled without toggling other windows."""
        ordered = self._toggle_order(snapshot)
        if not ordered:
            return True
        ws_id = _safe_int(workspace_id, "workspace_id")
        action = "enable" if floating else "disable"
        lines = [LUA_DISPATCH_HELPER, "local order = {"]
        lines.extend(f'  "{addr}",' for addr in ordered)
        lines.append("}")
        lines.append(f"local ws = hl.get_windows({{ workspace = {ws_id} }})")
        lines.append("for _, addr in ipairs(order) do")
        lines.append("  for _, w in ipairs(ws) do")
        lines.append("    if tostring(w.address) == addr then")
        lines.append(
            "      _canvas_dispatch(hl.dispatch(hl.dsp.window.float({ "
            f'action = "{action}", window = w }})))'
        )
        lines.append("      break")
        lines.append("    end")
        lines.append("  end")
        lines.append("end")
        try:
            self._ipc.eval_lua("\n".join(lines))
            return True
        except Exception as e:
            log.warning("snapshot floating rollback failed: %s", e)
            return False

    def _tile_windows(self, workspace_id: int, snapshot: dict[str, dict[str, list[int]]]) -> bool:
        """Tile exactly the windows recorded in the snapshot, leaving others floating.

        Plain per-window toggle: tiled placement is layout-owned, so no
        move/resize is attempted here (it would be discarded by the layout
        anyway). Floating geometry is preserved separately and reapplied on
        the next ON.
        """
        ordered = self._toggle_order(snapshot)
        if not ordered:
            if debug.enabled():
                debug.dbg2("TILE_START", ws=workspace_id, targets=0, addrs=[])
            return True
        ws_id = _safe_int(workspace_id, "workspace_id")
        if debug.enabled():
            debug.dbg2(
                "TILE_START",
                ws=workspace_id,
                targets=len(ordered),
                order=ordered,
            )
        if debug.level() >= 2:
            try:
                resp = self._ipc.send("j/clients")
                clients: list[dict[str, Any]] = json.loads(resp)
                live = {
                    w["address"]: {
                        "at": w.get("at"),
                        "size": w.get("size"),
                        "class": str(w.get("class", ""))[:30],
                        "title": str(w.get("title", ""))[:30],
                    }
                    for w in clients
                    if w.get("address") in snapshot
                }
                debug.dbg2("TILE_START_LIVE", ws=workspace_id, live=live)
            except Exception as e:
                debug.dbg2("TILE_START_LIVE_ERROR", ws=workspace_id, error=str(e))
        lines = [LUA_DISPATCH_HELPER, "local order = {"]
        lines.extend(f'  "{a}",' for a in ordered)
        lines.append("}")
        lines.append(f"local ws = hl.get_windows({{ floating = true, workspace = {ws_id} }})")
        lines.append("for _, addr in ipairs(order) do")
        lines.append("  for _, w in ipairs(ws) do")
        lines.append("    if tostring(w.address) == addr then")
        lines.append(
            "      _canvas_dispatch(hl.dispatch(hl.dsp.window.float({ "
            'action = "toggle", window = w })))'
        )
        lines.append("      break")
        lines.append("    end")
        lines.append("  end")
        lines.append("end")
        if debug.enabled():
            debug.dbg2("TILE_LUA", ws=workspace_id, lines=len(lines), preview="; ".join(lines[:2]))
        try:
            self._ipc.eval_lua("\n".join(lines))
            if debug.enabled():
                debug.dbg2("TILE_DONE", ws=workspace_id, targets=len(ordered))
            return True
        except Exception as e:
            log.warning("tile windows failed: %s", e)
            if debug.enabled():
                debug.dbg2("TILE_ERROR", ws=workspace_id, error=str(e))
            return False

    def _set_all_floating(self, workspace_id: int, floating: bool) -> bool:
        """Make every currently-tiled window on the workspace floating (canvas ON).

        The inverse is intentionally NOT done here: turning canvas off must
        tile only the windows recorded in the snapshot (_tile_windows), so
        windows that were already floating before canvas mode survive.
        """
        try:
            ws_id = _safe_int(workspace_id, "workspace_id")
            fl = "false" if floating else "true"
            if debug.enabled():
                try:
                    resp = self._ipc.send("j/clients")
                    clients: list[dict[str, Any]] = json.loads(resp)
                    tiled = [
                        w
                        for w in clients
                        if not w.get("floating")
                        and w.get("workspace", {}).get("id") == workspace_id
                    ]
                    debug.dbg2(
                        "FLOAT_START",
                        ws=workspace_id,
                        count=len(tiled),
                        addrs=sorted([str(w.get("address", "")) for w in tiled]),
                    )
                    if debug.level() >= 2 and tiled:
                        details = {
                            str(w["address"]): {
                                "at": w.get("at"),
                                "size": w.get("size"),
                                "class": str(w.get("class", ""))[:30],
                            }
                            for w in tiled
                            if w.get("address")
                        }
                        debug.dbg2("FLOAT_START_DETAIL", ws=workspace_id, details=details)
                except Exception as e:
                    log.debug("float debug snapshot unavailable: %s", e)
            lua = (
                f"{LUA_DISPATCH_HELPER}\n"
                f"local ws = hl.get_windows({{ floating = {fl}, workspace = {ws_id} }})\n"
                f"for _, w in ipairs(ws) do\n"
                f"  _canvas_dispatch(hl.dispatch(hl.dsp.window.float({{ "
                f'action = "toggle", window = w }})))\n'
                f"end"
            )
            self._ipc.eval_lua(lua)
            if debug.enabled():
                debug.dbg2("FLOAT_DONE", ws=workspace_id, floating=floating)
            return True
        except Exception as e:
            log.warning("set_all_floating failed: %s", e)
            if debug.enabled():
                debug.dbg2("FLOAT_ERROR", ws=workspace_id, error=str(e))
            return False

    def center_window(
        self,
        target_addr: str,
        workspace_id: int,
        cursor_x: int,
        cursor_y: int,
    ) -> bool:
        """Center a live target atomically without changing focus."""
        if not _VALID_ADDR.match(target_addr):
            return False
        center = self._get_monitor_center(cursor_x, cursor_y)
        if center is None:
            return False
        center_x, center_y = center
        safe_x = _safe_int(center_x, "center_x")
        safe_y = _safe_int(center_y, "center_y")
        ws_id = _safe_int(workspace_id, "workspace_id")
        lua = (
            f"{LUA_DISPATCH_HELPER}\n"
            f"local ws = hl.get_windows({{ floating = true, workspace = {ws_id} }})\n"
            f"local target = nil\n"
            f"for _, w in ipairs(ws) do\n"
            f'  if tostring(w.address) == "{target_addr}" then target = w; break end\n'
            f"end\n"
            f'if not target then error("center target no longer exists") end\n'
            f"local target_cx = target.at.x + math.floor(target.size.x / 2)\n"
            f"local target_cy = target.at.y + math.floor(target.size.y / 2)\n"
            f"local dx = {safe_x} - target_cx\n"
            f"local dy = {safe_y} - target_cy\n"
            f"for _, w in ipairs(ws) do\n"
            f"  _canvas_dispatch(hl.dispatch(hl.dsp.window.move({{"
            f" x = dx, y = dy, relative = true, window = w }})))\n"
            f"end"
        )
        try:
            self._ipc.eval_lua(lua)
            return True
        except Exception as e:
            log.warning("center window failed: %s", e)
            return False

    def _is_protected(self, window: dict[str, Any]) -> bool:
        """Check if window class matches a protected app."""
        window_class = window.get("class", "").lower()
        return any(app in window_class for app in self._protected_apps)

    def _pan_to_window(
        self,
        floating_windows: list[dict[str, Any]],
        target_addr: Any,
        center_x: int,
        center_y: int,
        workspace_id: int | None = None,
    ) -> bool:
        """Pan the workspace's floating windows so the target centers on monitor."""
        target = None
        for w in floating_windows:
            if w["address"] == target_addr:
                target = w
                break

        if target is None:
            return False

        target_cx = target["at"][0] + target["size"][0] // 2
        target_cy = target["at"][1] + target["size"][1] // 2

        dx = center_x - target_cx
        dy = center_y - target_cy

        safe_dx = _safe_int(dx, "dx")
        safe_dy = _safe_int(dy, "dy")

        ws_filter = ""
        if workspace_id is not None:
            ws_filter = f", workspace = {_safe_int(workspace_id, 'workspace_id')}"

        lua = (
            f"{LUA_DISPATCH_HELPER}\n"
            f"local ws = hl.get_windows({{ floating = true{ws_filter} }})\n"
            f"for _, w in ipairs(ws) do\n"
            f"  _canvas_dispatch(hl.dispatch(hl.dsp.window.move({{"
            f" x = {safe_dx}, y = {safe_dy},"
            f" relative = true, window = w }})))\n"
            f"end\n"
        )

        # Focus target by iterating floating windows and matching address
        # (avoids Lua injection from class names)
        if not self._is_protected(target):
            addr = target.get("address", "")
            if _VALID_ADDR.match(addr):
                lua += (
                    f"local _t = hl.get_windows({{ floating = true{ws_filter} }})\n"
                    f"for _, w in ipairs(_t) do\n"
                    f'  if tostring(w.address) == "{addr}" then\n'
                    f"    _canvas_dispatch(hl.dispatch(hl.dsp.focus({{ window = w }})))\n"
                    f"    break\n"
                    f"  end\n"
                    f"end\n"
                )

        try:
            self._ipc.eval_lua(lua)
            return True
        except Exception as e:
            log.warning("navigation pan failed: %s", e)
            return False

    def _get_active_workspace_id(self) -> int | None:
        try:
            resp = self._ipc.send("j/activeworkspace")
            ws: dict[str, Any] = json.loads(resp)
            return int(ws["id"])
        except Exception as e:
            log.debug("get_active_workspace_id failed: %s", e)
            return None

    def _get_floating_windows(self, workspace_id: int) -> list[dict[str, Any]] | None:
        try:
            resp = self._ipc.send("j/clients")
            clients: list[dict[str, Any]] = json.loads(resp)
            return [
                w
                for w in clients
                if w.get("floating")
                and (ws := w.get("workspace")) is not None
                and ws.get("id") == workspace_id
            ]
        except Exception as e:
            log.debug("get_floating_windows failed: %s", e)
            return None

    def _get_focused_window(self) -> dict[str, Any] | None:
        try:
            resp = self._ipc.send("j/activewindow")
            result: dict[str, Any] = json.loads(resp)
            return result
        except Exception as e:
            log.debug("get_focused_window failed: %s", e)
            return None

    def _get_monitor_center(
        self, cursor_x: int | None = None, cursor_y: int | None = None
    ) -> tuple[int, int] | None:
        try:
            resp = self._ipc.send("j/monitors")
            monitors: list[dict[str, Any]] = json.loads(resp)
            parsed: list[tuple[dict[str, Any], int, int, int, int]] = []
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
                parsed.append((monitor, x, y, width, height))

            if cursor_x is not None and cursor_y is not None:
                for _monitor, x, y, width, height in parsed:
                    if x <= cursor_x < x + width and y <= cursor_y < y + height:
                        return x + width // 2, y + height // 2
                return None

            for monitor, x, y, width, height in parsed:
                if monitor.get("focused", False):
                    return x + width // 2, y + height // 2
            if parsed:
                _monitor, x, y, width, height = parsed[0]
                return x + width // 2, y + height // 2
        except Exception as e:
            log.debug("get_monitor_center failed: %s", e)
        return None
