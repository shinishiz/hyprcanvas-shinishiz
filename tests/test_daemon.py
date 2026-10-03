"""Tests for canvas.daemon — DaemonState and helper functions."""

import json
import threading
import time
from unittest.mock import MagicMock, call, patch

from canvas.daemon import DaemonState, EventListener, _lua_escape
from canvas.hypr import CanvasViewport
from canvas.navigation import Navigator
from canvas.panning import EdgeScrollParams, EdgeScrollState, PanningState


def _make_daemon_state(ipc: MagicMock | None = None) -> DaemonState:
    panning = PanningState(speed=1.0)
    edge_scroll = EdgeScrollState(ramp_distance=50, speed=20.0, enabled=True)
    navigator = MagicMock()
    if ipc is None:
        ipc = MagicMock()
    return DaemonState(panning=panning, edge_scroll=edge_scroll, navigator=navigator, ipc=ipc)


def _clients(clients_json: str) -> str:
    return clients_json


def test_handle_ipc_pan_start_fetches_baselines():
    """PAN_START fetches baselines and starts panning."""
    ipc = MagicMock()
    ipc.send.side_effect = [json.dumps({"id": 1}), "[]"]
    ds = _make_daemon_state(ipc)

    result = ds.handle_ipc("PAN_START")

    assert result == "PAN_ON"
    assert ds.panning.pan_active is True
    ipc.send.assert_any_call("j/clients")


def test_handle_ipc_pan_stop_clears_baselines():
    """PAN_STOP stops panning and clears baselines."""
    ds = _make_daemon_state()
    ds.panning.start_pan()
    ds.baselines = {"0x1": (100, 200)}

    result = ds.handle_ipc("PAN_STOP")

    assert result == "PAN_OFF"
    assert ds.panning.pan_active is False
    assert ds.baselines == {}


def test_handle_ipc_toggle():
    """TOGGLE flips inverted state."""
    ds = _make_daemon_state()
    ds.panning.inverted = True

    result = ds.handle_ipc("TOGGLE")
    assert result == "NORMAL"
    assert ds.panning.inverted is False

    result2 = ds.handle_ipc("TOGGLE")
    assert result2 == "INVERTED"
    assert ds.panning.inverted is True


def test_handle_ipc_canvas_toggle_legacy_and_explicit_workspace():
    ds = _make_daemon_state()
    ds.navigator.canvas_toggle.return_value = "CANVAS_OFF"

    assert ds.handle_ipc("CANVAS_TOGGLE") == "CANVAS_OFF"
    ds.navigator.canvas_toggle.assert_called_once_with(None)

    ds.navigator.canvas_toggle.reset_mock()
    assert ds.handle_ipc("CANVAS_TOGGLE 2") == "CANVAS_OFF"
    ds.navigator.canvas_toggle.assert_called_once_with(2)


def test_handle_ipc_canvas_toggle_all_legacy_and_explicit_workspace():
    ds = _make_daemon_state()
    ds.navigator.canvas_toggle_all.return_value = "CANVAS_ON"

    assert ds.handle_ipc("CANVAS_TOGGLE_ALL") == "CANVAS_ON"
    ds.navigator.canvas_toggle_all.assert_called_once_with(None)

    ds.navigator.canvas_toggle_all.reset_mock()
    assert ds.handle_ipc("CANVAS_TOGGLE_ALL 2") == "CANVAS_ON"
    ds.navigator.canvas_toggle_all.assert_called_once_with(2)


def test_handle_ipc_canvas_toggle_rejects_invalid_workspace():
    ds = _make_daemon_state()

    for cmd in (
        "CANVAS_TOGGLE 0",
        "CANVAS_TOGGLE -1",
        "CANVAS_TOGGLE abc",
        "CANVAS_TOGGLE 2 extra",
    ):
        assert ds.handle_ipc(cmd) == "ERROR:INVALID_WORKSPACE"

    ds.navigator.canvas_toggle.assert_not_called()


def test_handle_ipc_nav():
    """NAV_LEFT/NAV_RIGHT delegates to navigator."""
    ds = _make_daemon_state()

    assert ds.handle_ipc("NAV_LEFT") == "OK"
    ds.navigator.navigate.assert_called_with("left")

    assert ds.handle_ipc("NAV_RIGHT") == "OK"
    ds.navigator.navigate.assert_called_with("right")


def test_handle_ipc_ping():
    assert _make_daemon_state().handle_ipc("PING") == "PONG"


def test_handle_ipc_status():
    ds = _make_daemon_state()
    ds.panning.inverted = True
    assert ds.handle_ipc("STATUS") == "INVERTED IDLE"

    ds.panning.start_pan()
    assert ds.handle_ipc("STATUS") == "INVERTED PANNING"


def test_zoom_out_only_dispatches_for_active_canvas_workspace():
    ipc = MagicMock()
    ipc.send.return_value = '{"id":4}'
    ipc.set_canvas_viewport.return_value = True
    ds = _make_daemon_state(ipc)
    ds.navigator.is_canvas_active.return_value = True

    assert ds.handle_ipc("ZOOM_OUT") == "OK"
    ipc.set_canvas_viewport.assert_called_once_with("zoom-out", 4)


def test_zoom_is_rejected_outside_canvas():
    ipc = MagicMock()
    ipc.send.return_value = '{"id":4}'
    ds = _make_daemon_state(ipc)
    ds.navigator.is_canvas_active.return_value = False

    assert ds.handle_ipc("ZOOM_IN") == "ERROR:CANVAS_INACTIVE"
    ipc.set_canvas_viewport.assert_not_called()


def test_zoom_reset_reports_plugin_failure():
    ipc = MagicMock()
    ipc.send.return_value = '{"id":9}'
    ipc.set_canvas_viewport.return_value = False
    ds = _make_daemon_state(ipc)
    ds.navigator.is_canvas_active.return_value = True

    assert ds.handle_ipc("ZOOM_RESET") == "ERROR:ZOOM_UNAVAILABLE"
    ipc.set_canvas_viewport.assert_called_once_with("zoom-reset", 9)


def test_zoom_stops_active_pan_before_changing_camera():
    ipc = MagicMock()
    ipc.send.return_value = '{"id":2}'
    ipc.set_canvas_viewport.return_value = True
    ds = _make_daemon_state(ipc)
    ds.navigator.is_canvas_active.return_value = True
    ds.panning.start_pan()
    ds.baselines = {"0x1": (10, 20)}
    ds.baseline_workspace = 2

    assert ds.handle_ipc("ZOOM_OUT") == "OK"
    assert ds.panning.pan_active is False
    assert ds.baselines == {}
    assert ds.baseline_workspace is None


def test_handle_ipc_unknown():
    assert _make_daemon_state().handle_ipc("FOOBAR") == "UNKNOWN: FOOBAR"


def test_fetch_baselines_parses_clients():
    """fetch_baselines extracts floating window addresses and positions."""
    ipc = MagicMock()
    ipc.send.side_effect = [
        json.dumps({"id": 1}),
        _clients(
            '[{"address":"0xabc","floating":true,"at":[10,20],"workspace":{"id":1}},'
            '{"address":"0xdef","floating":false,"at":[30,40],"workspace":{"id":1}}]'
        ),
    ]
    ds = _make_daemon_state(ipc)

    ds.fetch_baselines()

    assert ds.baselines == {"0xabc": (10, 20)}
    assert ds.baseline_workspace == 1


def test_fetch_baselines_scoped_to_active_workspace():
    """Windows on other workspaces must not enter the baseline snapshot."""
    ipc = MagicMock()
    ipc.send.side_effect = [
        json.dumps({"id": 1}),
        _clients(
            '[{"address":"0xaaa","floating":true,"at":[1,2],"workspace":{"id":1}},'
            '{"address":"0xbbb","floating":true,"at":[3,4],"workspace":{"id":2}}]'
        ),
    ]
    ds = _make_daemon_state(ipc)

    ds.fetch_baselines()

    assert ds.baselines == {"0xaaa": (1, 2)}
    assert ds.baseline_workspace == 1


def test_fetch_baselines_empty_response():
    """fetch_baselines handles empty client list."""
    ipc = MagicMock()
    ipc.send.side_effect = [json.dumps({"id": 1}), "[]"]
    ds = _make_daemon_state(ipc)

    ds.fetch_baselines()

    assert ds.baselines == {}


def test_fetch_baselines_bad_json():
    """fetch_baselines handles invalid JSON gracefully."""
    ipc = MagicMock()
    ipc.send.return_value = "not json"
    ds = _make_daemon_state(ipc)

    ds.fetch_baselines()

    assert ds.baselines == {}
    assert ds.baseline_workspace is None


def test_restore_baselines_moves_windows_back():
    """restore_baselines sends Lua to move windows to original positions."""
    ipc = MagicMock()
    ipc.eval_lua.return_value = "ok"
    ds = _make_daemon_state(ipc)
    ds.baselines = {"0xabc": (100, 200)}
    ds.baseline_workspace = 4

    ds.restore_baselines()

    ipc.eval_lua.assert_called_once()
    lua_code = ipc.eval_lua.call_args[0][0]
    assert "0xabc" in lua_code
    assert "b[1]" in lua_code
    assert "relative = false" in lua_code
    assert "workspace = 4" in lua_code


def test_restore_baselines_skips_when_empty():
    """restore_baselines does nothing if no baselines recorded."""
    ipc = MagicMock()
    ds = _make_daemon_state(ipc)

    ds.restore_baselines()

    ipc.eval_lua.assert_not_called()


def test_move_windows_to_delta():
    """move_windows_to_delta generates Lua with correct offsets and workspace scope."""
    ipc = MagicMock()
    ipc.eval_lua.return_value = "ok"
    ds = _make_daemon_state(ipc)
    ds.baselines = {"0xabc": (100, 200)}
    ds.baseline_workspace = 2

    ds.move_windows_to_delta(50, -30)

    ipc.eval_lua.assert_called_once()
    lua_code = ipc.eval_lua.call_args[0][0]
    assert "b[1] + 50" in lua_code
    assert "b[2] + -30" in lua_code
    assert "relative = false" in lua_code
    assert "workspace = 2" in lua_code


def test_move_windows_to_delta_scales_screen_delta_into_world_space():
    ipc = MagicMock()
    ipc.eval_lua.return_value = "ok"
    ds = _make_daemon_state(ipc)
    ds.baselines = {"0xabc": (100, 200)}
    ds.baseline_workspace = 2
    ds.baseline_zoom = 0.5

    ds.move_windows_to_delta(100, -50)

    lua_code = ipc.eval_lua.call_args[0][0]
    assert "b[1] + 200" in lua_code
    assert "b[2] + -100" in lua_code


def test_move_windows_to_delta_without_workspace_is_noop():
    """Without a captured workspace (failed fetch) no Lua must be dispatched."""
    ipc = MagicMock()
    ds = _make_daemon_state(ipc)
    ds.baselines = {"0xabc": (100, 200)}
    ds.baseline_workspace = None

    ds.move_windows_to_delta(50, 30)

    ipc.eval_lua.assert_not_called()


def test_lua_escape():
    """_lua_escape handles backslashes, quotes, and newlines."""
    assert _lua_escape("hello") == "hello"
    assert _lua_escape('a"b') == 'a\\"b'
    assert _lua_escape("a\\b") == "a\\\\b"
    assert _lua_escape("a\nb") == "a\\nb"
    assert _lua_escape("0x1a2b") == "0x1a2b"


def test_fetch_baselines_window_without_at():
    """fetch_baselines uses default [0,0] when 'at' field missing."""
    ipc = MagicMock()
    ipc.send.side_effect = [
        json.dumps({"id": 1}),
        _clients('[{"address":"0xabc","floating":true,"workspace":{"id":1}}]'),
    ]
    ds = _make_daemon_state(ipc)

    ds.fetch_baselines()

    assert ds.baselines == {"0xabc": (0, 0)}


def test_fetch_baselines_window_with_empty_address():
    """fetch_baselines skips windows with empty address."""
    ipc = MagicMock()
    ipc.send.side_effect = [
        json.dumps({"id": 1}),
        _clients('[{"address":"","floating":true,"at":[10,20]}]'),
    ]
    ds = _make_daemon_state(ipc)

    ds.fetch_baselines()

    assert ds.baselines == {}


def test_fetch_baselines_ipc_error():
    """fetch_baselines handles IPC send failure gracefully."""
    ipc = MagicMock()
    ipc.send.side_effect = ConnectionError("socket failed")
    ds = _make_daemon_state(ipc)

    ds.fetch_baselines()

    assert ds.baselines == {}


def test_restore_baselines_ipc_error():
    """restore_baselines handles IPC eval_lua failure gracefully."""
    ipc = MagicMock()
    ipc.eval_lua.side_effect = ConnectionError("socket failed")
    ds = _make_daemon_state(ipc)
    ds.baselines = {"0xabc": (100, 200)}

    ds.restore_baselines()  # should not raise

    assert ds.baselines == {"0xabc": (100, 200)}


def test_move_windows_to_delta_ipc_error():
    """move_windows_to_delta handles IPC failure gracefully."""
    ipc = MagicMock()
    ipc.eval_lua.side_effect = ConnectionError("socket failed")
    ds = _make_daemon_state(ipc)
    ds.baselines = {"0xabc": (100, 200)}

    ds.move_windows_to_delta(50, 50)  # should not raise


def test_fetch_baselines_multiple_floating():
    """fetch_baselines correctly extracts multiple floating windows."""
    ipc = MagicMock()
    ipc.send.side_effect = [
        json.dumps({"id": 1}),
        _clients(
            '[{"address":"0xaaa","floating":true,"at":[10,20],"workspace":{"id":1}},'
            '{"address":"0xbbb","floating":true,"at":[300,400],"workspace":{"id":1}},'
            '{"address":"0xccc","floating":false,"at":[500,600],"workspace":{"id":1}}]'
        ),
    ]
    ds = _make_daemon_state(ipc)

    ds.fetch_baselines()

    assert ds.baselines == {"0xaaa": (10, 20), "0xbbb": (300, 400)}


def _clients_json(windows_json: str) -> str:
    """Helper: wrap a raw clients JSON for side_effect sequences."""
    return windows_json


def test_handle_ipc_edge_start():
    """EDGE_START grabs the floating window under the cursor."""
    ipc = MagicMock()
    ipc.send.side_effect = [
        json.dumps({"id": 3}),
        _clients_json(
            '[{"address":"0xabc","floating":true,"at":[100,200],"size":[500,300],'
            '"workspace":{"id":3}}]'
        ),
        json.dumps({"address": "0xabc"}),
        '[{"focused":true,"x":0,"y":0,"width":1920,"height":1080}]',
    ]
    ds = _make_daemon_state(ipc)

    with patch("canvas.daemon.get_cursor_pos", return_value=(350, 350)):
        result = ds.handle_ipc("EDGE_START")
        assert result == "EDGE_ON"
        assert ds.edge_scroll.active is True
        assert ds.edge_scroll.dragged_addr == "0xabc"
        assert ds.edge_scroll_workspace == 3


def test_handle_ipc_edge_start_focus_mismatch_refuses():
    """Press inside bounding rect but Hyprland focused another window →
    the click landed on border/gap and no drag will engage. Must not arm."""
    ipc = MagicMock()
    ipc.send.side_effect = [
        json.dumps({"id": 1}),
        _clients_json(
            '[{"address":"0xabc","floating":true,"at":[100,200],"size":[500,300],'
            '"workspace":{"id":1}}]'
        ),
        json.dumps({"address": "0xfocused_elsewhere"}),
    ]
    ds = _make_daemon_state(ipc)

    with patch("canvas.daemon.get_cursor_pos", return_value=(350, 350)):
        result = ds.handle_ipc("EDGE_START")

    assert result == "EDGE_NO_WINDOW"
    assert ds.edge_scroll.active is False


def test_handle_ipc_edge_start_no_window():
    """Cursor over empty desktop → no activation, even with a focused window."""
    ipc = MagicMock()
    ipc.send.side_effect = [json.dumps({"id": 1}), "[]"]
    ds = _make_daemon_state(ipc)

    with patch("canvas.daemon.get_cursor_pos", return_value=(500, 500)):
        result = ds.handle_ipc("EDGE_START")

    assert result == "EDGE_NO_WINDOW"
    assert ds.edge_scroll.active is False


def test_handle_ipc_edge_start_ignores_offscreen_focused_window():
    """Regression: a stale-focused off-screen window must never drive the camera.

    Old behavior: geometry came from j/activewindow, grab offsets were
    computed against an invisible window, and any drag attempt sent the
    camera chasing it at max speed. Now the window must be under the
    cursor to activate at all.
    """
    ipc = MagicMock()
    ipc.send.side_effect = [
        json.dumps({"id": 1}),
        _clients_json(
            # only floating window sits far off-screen; cursor clicks empty space
            '[{"address":"0xdead","floating":true,"at":[2500,390],"size":[500,300],'
            '"workspace":{"id":1}}]'
        ),
    ]
    ds = _make_daemon_state(ipc)

    with (
        patch("canvas.daemon.get_cursor_pos", return_value=(960, 540)),
        patch("canvas.daemon.log") as _,
    ):
        result = ds.handle_ipc("EDGE_START")

    assert result == "EDGE_NO_WINDOW"
    assert ds.edge_scroll.active is False


def test_handle_ipc_edge_start_picks_window_under_cursor():
    """Two floating windows — the one containing the cursor is dragged."""
    ipc = MagicMock()
    ipc.send.side_effect = [
        json.dumps({"id": 1}),
        _clients_json(
            '[{"address":"0xaaa","floating":true,"at":[100,100],"size":[400,300],'
            '"workspace":{"id":1}},'
            '{"address":"0xbbb","floating":true,"at":[600,100],"size":[400,300],'
            '"workspace":{"id":1}}]'
        ),
        json.dumps({"address": "0xbbb"}),
        '[{"focused":true,"x":0,"y":0,"width":1920,"height":1080}]',
    ]
    ds = _make_daemon_state(ipc)

    with patch("canvas.daemon.get_cursor_pos", return_value=(800, 200)):
        result = ds.handle_ipc("EDGE_START")

    assert result == "EDGE_ON"
    assert ds.edge_scroll.dragged_addr == "0xbbb"


def test_handle_ipc_edge_start_overlap_last_wins():
    """Overlapping floating windows → last match (topmost guess) is dragged."""
    ipc = MagicMock()
    ipc.send.side_effect = [
        json.dumps({"id": 1}),
        _clients_json(
            '[{"address":"0xaaa","floating":true,"at":[100,100],"size":[400,300],'
            '"workspace":{"id":1}},'
            '{"address":"0xbbb","floating":true,"at":[150,150],"size":[400,300],'
            '"workspace":{"id":1}}]'
        ),
        json.dumps({"address": "0xbbb"}),
        '[{"focused":true,"x":0,"y":0,"width":1920,"height":1080}]',
    ]
    ds = _make_daemon_state(ipc)

    with patch("canvas.daemon.get_cursor_pos", return_value=(300, 250)):
        result = ds.handle_ipc("EDGE_START")

    assert result == "EDGE_ON"
    assert ds.edge_scroll.dragged_addr == "0xbbb"


def test_find_window_at_cursor_skips_hidden_and_fullscreen_overlaps():
    """Pinned windows stay movable; hidden/fullscreen clients are skipped."""
    clients = [
        {
            "address": "0xvisible",
            "floating": True,
            "at": [100, 100],
            "size": [400, 300],
            "workspace": {"id": 1},
        },
        {
            "address": "0xhidden",
            "floating": True,
            "hidden": True,
            "at": [100, 100],
            "size": [400, 300],
            "workspace": {"id": 1},
        },
        {
            "address": "0xpinned",
            "floating": True,
            "pinned": True,
            "at": [100, 100],
            "size": [400, 300],
            "workspace": {"id": 1},
        },
        {
            "address": "0xfullscreen",
            "floating": True,
            "fullscreen": 1,
            "at": [100, 100],
            "size": [400, 300],
            "workspace": {"id": 1},
        },
    ]
    ipc = MagicMock()
    ipc.send.return_value = json.dumps(clients)
    ds = _make_daemon_state(ipc)

    found = ds._find_window_at_cursor(300, 250, 1)

    assert found is not None
    assert found["address"] == "0xpinned"


def test_handle_ipc_edge_start_tiled_only_under_cursor():
    """A tiled window under the cursor is not canvas-draggable."""
    ipc = MagicMock()
    ipc.send.side_effect = [
        json.dumps({"id": 1}),
        _clients_json(
            '[{"address":"0xtile","floating":false,"at":[100,100],"size":[400,300],'
            '"workspace":{"id":1}}]'
        ),
    ]
    ds = _make_daemon_state(ipc)

    with patch("canvas.daemon.get_cursor_pos", return_value=(300, 250)):
        result = ds.handle_ipc("EDGE_START")

    assert result == "EDGE_NO_WINDOW"
    assert ds.edge_scroll.active is False


def test_handle_ipc_edge_start_ignores_other_workspace_window():
    """Floating window containing the cursor point but on another workspace → skip."""
    ipc = MagicMock()
    ipc.send.side_effect = [
        json.dumps({"id": 2}),
        _clients_json(
            '[{"address":"0xws1","floating":true,"at":[100,100],"size":[400,300],'
            '"workspace":{"id":1}}]'
        ),
    ]
    ds = _make_daemon_state(ipc)

    with patch("canvas.daemon.get_cursor_pos", return_value=(300, 250)):
        result = ds.handle_ipc("EDGE_START")

    assert result == "EDGE_NO_WINDOW"


def test_handle_ipc_edge_start_no_workspace():
    """EDGE_START without a resolvable workspace must not activate."""
    ipc = MagicMock()
    ipc.send.side_effect = [Exception("workspace query failed")]
    ds = _make_daemon_state(ipc)

    with patch("canvas.daemon.get_cursor_pos", return_value=(350, 350)):
        result = ds.handle_ipc("EDGE_START")

    assert result == "EDGE_NO_WORKSPACE"
    assert ds.edge_scroll.active is False


def test_handle_ipc_edge_start_no_monitor():
    """EDGE_START without monitor geometry must not activate edge-scroll."""
    ipc = MagicMock()
    ipc.send.side_effect = [
        json.dumps({"id": 3}),
        _clients_json(
            '[{"address":"0xabc","floating":true,"at":[100,200],"size":[500,300],'
            '"workspace":{"id":3}}]'
        ),
        json.dumps({"address": "0xabc"}),
        Exception("monitors query failed"),
    ]
    ds = _make_daemon_state(ipc)

    with patch("canvas.daemon.get_cursor_pos", return_value=(350, 350)):
        result = ds.handle_ipc("EDGE_START")

    assert result == "EDGE_NO_MONITOR"
    assert ds.edge_scroll.active is False


def test_handle_ipc_edge_stop():
    """EDGE_STOP deactivates edge-scroll."""
    ds = _make_daemon_state()
    ds.edge_scroll.start(
        EdgeScrollParams(
            dragged_addr="0xabc",
            win_x=100,
            win_y=200,
            win_w=500,
            win_h=300,
            cursor_x=350,
            cursor_y=350,
        )
    )

    result = ds.handle_ipc("EDGE_STOP")
    assert result == "EDGE_OFF"
    assert ds.edge_scroll.active is False


def test_edge_scroll_move_excludes_dragged():
    """edge_scroll_move generates Lua that excludes dragged window, workspace-scoped."""
    ipc = MagicMock()
    ipc.eval_lua.return_value = "ok"
    ds = _make_daemon_state(ipc)
    ds.edge_scroll.start(
        EdgeScrollParams(
            dragged_addr="0xabc",
            win_x=100,
            win_y=200,
            win_w=500,
            win_h=300,
            cursor_x=350,
            cursor_y=350,
        )
    )
    ds.edge_scroll_workspace = 5

    ds.edge_scroll_move(10, -5)

    ipc.eval_lua.assert_called_once()
    lua_code = ipc.eval_lua.call_args[0][0]
    assert "0xabc" in lua_code
    assert "~=" in lua_code
    assert "relative = true" in lua_code
    assert "workspace = 5" in lua_code
    assert "_canvas_dispatch" in lua_code


def test_edge_scroll_move_without_workspace_is_noop():
    """Without a captured workspace edge moves must never dispatch."""
    ipc = MagicMock()
    ds = _make_daemon_state(ipc)
    ds.edge_scroll.start(
        EdgeScrollParams(
            dragged_addr="0xabc",
            win_x=100,
            win_y=200,
            win_w=500,
            win_h=300,
            cursor_x=350,
            cursor_y=350,
        )
    )
    ds.edge_scroll_workspace = None

    ds.edge_scroll_move(10, -5)

    ipc.eval_lua.assert_not_called()


def test_edge_scroll_move_zero_delta_is_noop():
    """edge_scroll_move with (0,0) does nothing."""
    ipc = MagicMock()
    ds = _make_daemon_state(ipc)
    ds.edge_scroll.start(
        EdgeScrollParams(
            dragged_addr="0xabc",
            win_x=100,
            win_y=200,
            win_w=500,
            win_h=300,
            cursor_x=350,
            cursor_y=350,
        )
    )

    ds.edge_scroll_move(0, 0)

    ipc.eval_lua.assert_not_called()


def _make_event_listener(
    navigator: MagicMock | None = None, ipc: MagicMock | None = None
):
    stop_event = threading.Event()
    nav = navigator or MagicMock()
    if ipc is None:
        ipc = MagicMock()
    return EventListener(navigator=nav, ipc=ipc, stop_event=stop_event)


def _fake_event_socket(
    reads: list[bytes | BaseException],
    *,
    stop_event: threading.Event | None = None,
    connect_error: OSError | None = None,
) -> MagicMock:
    sock = MagicMock()
    queue = list(reads)

    def recv(_size: int) -> bytes:
        if queue:
            item = queue.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        if stop_event is not None:
            stop_event.set()
        return b""

    sock.recv.side_effect = recv
    if connect_error is not None:
        sock.connect.side_effect = connect_error
    return sock


def test_event_listener_start_stop():
    """EventListener starts and stops cleanly."""
    ipc = MagicMock()
    navigator = MagicMock()
    stop_event = threading.Event()
    listener = EventListener(navigator=navigator, ipc=ipc, stop_event=stop_event)
    with patch.object(listener, "_run", side_effect=lambda: stop_event.wait()):
        listener.start()
        assert listener._thread is not None
        assert listener._thread.is_alive()
        listener.stop()
        assert not listener._thread.is_alive()


def test_event_listener_start_while_alive_does_not_duplicate_thread():
    listener = _make_event_listener()
    with patch.object(listener, "_run", side_effect=lambda: listener._stop_event.wait()):
        listener.start()
        first_thread = listener._thread
        listener.start()

        assert listener._thread is first_thread
        listener.stop()


def test_event_listener_missing_startup_path_retries_then_connects():
    listener = _make_event_listener()
    sock = _fake_event_socket([], stop_event=listener._stop_event)
    wait = MagicMock(return_value=False)
    listener._stop_event.wait = wait  # type: ignore[method-assign]

    with (
        patch(
            "canvas.daemon._hypr_socket2_path",
            side_effect=[FileNotFoundError("missing"), "/tmp/socket2"],
        ) as resolver,
        patch("canvas.daemon.socket.socket", return_value=sock),
    ):
        listener._run()

    assert resolver.call_args_list == [call(strict_instance=True), call(strict_instance=True)]
    wait.assert_called_once_with(0.25)
    sock.connect.assert_called_once_with("/tmp/socket2")
    sock.close.assert_called_once()


def test_event_listener_connection_refused_closes_socket_and_retries():
    listener = _make_event_listener()
    refused = _fake_event_socket([], connect_error=ConnectionRefusedError(111, "refused"))
    connected = _fake_event_socket([], stop_event=listener._stop_event)
    wait = MagicMock(return_value=False)
    listener._stop_event.wait = wait  # type: ignore[method-assign]

    with (
        patch("canvas.daemon._hypr_socket2_path", return_value="/tmp/socket2") as resolver,
        patch("canvas.daemon.socket.socket", side_effect=[refused, connected]),
    ):
        listener._run()

    assert resolver.call_count == 2
    wait.assert_called_once_with(0.25)
    refused.close.assert_called_once()
    connected.close.assert_called_once()


def test_event_listener_eof_reconnects_and_stays_alive_until_stop():
    listener = _make_event_listener()
    first = _fake_event_socket([b"closewindow>>aaa\n", b""])
    release = threading.Event()
    second_seen = threading.Event()
    second = MagicMock()
    second_reads = iter([b"closewindow>>bbb\n"])

    def second_recv(_size: int) -> bytes:
        try:
            return next(second_reads)
        except StopIteration:
            release.wait(timeout=1)
            raise OSError("closed") from None

    second.recv.side_effect = second_recv
    second.close.side_effect = release.set

    def record_line(line: str) -> None:
        if line == "closewindow>>bbb":
            second_seen.set()

    with (
        patch("canvas.daemon._hypr_socket2_path", return_value="/tmp/socket2"),
        patch("canvas.daemon.socket.socket", side_effect=[first, second]),
        patch.object(listener, "_handle_line", side_effect=record_line) as handle,
    ):
        listener.start()
        assert second_seen.wait(timeout=1)
        assert listener._thread is not None
        assert listener._thread.is_alive()
        listener.stop()

    assert [c.args[0] for c in handle.call_args_list] == [
        "closewindow>>aaa",
        "closewindow>>bbb",
    ]
    first.close.assert_called_once()
    assert second.close.call_count >= 1


def test_event_listener_connection_reset_reconnects():
    listener = _make_event_listener()
    first = _fake_event_socket([ConnectionResetError(104, "reset")])
    second = _fake_event_socket([b"closewindow>>bbb\n"], stop_event=listener._stop_event)
    wait = MagicMock(return_value=False)
    listener._stop_event.wait = wait  # type: ignore[method-assign]

    with (
        patch("canvas.daemon._hypr_socket2_path", return_value="/tmp/socket2"),
        patch("canvas.daemon.socket.socket", side_effect=[first, second]),
        patch.object(listener, "_handle_line") as handle,
    ):
        listener._run()

    handle.assert_called_once_with("closewindow>>bbb")
    wait.assert_called_once_with(0.25)
    first.close.assert_called_once()
    second.close.assert_called_once()


def test_event_listener_partial_read_same_connection_is_preserved():
    listener = _make_event_listener()
    sock = _fake_event_socket(
        [b"openwindow>>ABC", b",2,kitty,kitty\n"],
        stop_event=listener._stop_event,
    )

    with (
        patch("canvas.daemon._hypr_socket2_path", return_value="/tmp/socket2"),
        patch("canvas.daemon.socket.socket", return_value=sock),
        patch.object(listener, "_handle_line") as handle,
    ):
        listener._run()

    handle.assert_called_once_with("openwindow>>ABC,2,kitty,kitty")


def test_event_listener_partial_read_does_not_cross_reconnect():
    listener = _make_event_listener()
    first = _fake_event_socket([b"openwindow>>STALE_PARTIAL", b""])
    second = _fake_event_socket(
        [b"openwindow>>REAL_EVENT\n"],
        stop_event=listener._stop_event,
    )
    listener._stop_event.wait = MagicMock(return_value=False)  # type: ignore[method-assign]

    with (
        patch("canvas.daemon._hypr_socket2_path", return_value="/tmp/socket2"),
        patch("canvas.daemon.socket.socket", side_effect=[first, second]),
        patch.object(listener, "_handle_line") as handle,
    ):
        listener._run()

    handle.assert_called_once_with("openwindow>>REAL_EVENT")


def test_event_listener_multiple_events_in_one_recv_preserve_order():
    listener = _make_event_listener()
    sock = _fake_event_socket(
        [b"closewindow>>aaa\nclosewindow>>bbb\nclosewindow>>ccc\n"],
        stop_event=listener._stop_event,
    )

    with (
        patch("canvas.daemon._hypr_socket2_path", return_value="/tmp/socket2"),
        patch("canvas.daemon.socket.socket", return_value=sock),
        patch.object(listener, "_handle_line") as handle,
    ):
        listener._run()

    assert [c.args[0] for c in handle.call_args_list] == [
        "closewindow>>aaa",
        "closewindow>>bbb",
        "closewindow>>ccc",
    ]


def test_event_listener_handler_exception_does_not_kill_connection(caplog):
    listener = _make_event_listener()
    sock = _fake_event_socket(
        [b"openwindow>>bad\nclosewindow>>good\n"],
        stop_event=listener._stop_event,
    )

    with (
        patch("canvas.daemon._hypr_socket2_path", return_value="/tmp/socket2"),
        patch("canvas.daemon.socket.socket", return_value=sock),
        patch.object(listener, "_handle_line", side_effect=[RuntimeError("boom"), None]) as handle,
    ):
        listener._run()

    assert handle.call_count == 2
    assert "EventListener handler failed for event openwindow" in caplog.text
    assert "RuntimeError: boom" in caplog.text
    sock.connect.assert_called_once()


def test_event_listener_stop_interrupts_backoff_without_retry():
    stop_event = threading.Event()
    listener = EventListener(navigator=MagicMock(), ipc=MagicMock(), stop_event=stop_event)
    entered_backoff = threading.Event()
    real_wait = stop_event.wait

    def tracked_wait(delay: float | None = None) -> bool:
        entered_backoff.set()
        return real_wait(delay)

    stop_event.wait = tracked_wait  # type: ignore[method-assign]

    with (
        patch("canvas.daemon._EVENT_RECONNECT_DELAYS", (60.0,)),
        patch(
            "canvas.daemon._hypr_socket2_path",
            side_effect=FileNotFoundError("missing"),
        ) as resolver,
    ):
        listener.start()
        assert entered_backoff.wait(timeout=1)
        listener.stop()

    assert listener._thread is not None
    assert not listener._thread.is_alive()
    resolver.assert_called_once_with(strict_instance=True)


def test_event_listener_stop_between_attempts_does_not_create_socket():
    listener = _make_event_listener()

    def resolve_then_stop(*, strict_instance: bool) -> str:
        assert strict_instance is True
        listener._stop_event.set()
        return "/tmp/socket2"

    with (
        patch("canvas.daemon._hypr_socket2_path", side_effect=resolve_then_stop),
        patch("canvas.daemon.socket.socket") as socket_factory,
    ):
        listener._run()

    socket_factory.assert_not_called()


def test_event_listener_openwindow_tiled_converts_to_floating():
    """openwindow for tiled window on Canvas workspace converts to floating with geometry."""
    ipc = MagicMock()
    navigator = MagicMock()
    navigator.is_canvas_active.return_value = True
    navigator.get_spawn_geometry.return_value = (800, 600)
    navigator.get_canvas_visual_center.return_value = (960.0, 540.0)
    stop_event = threading.Event()
    listener = EventListener(navigator=navigator, ipc=ipc, stop_event=stop_event)

    # Mock j/clients to return a tiled window
    client = {
        "address": "0xabc123",
        "floating": False,
        "at": [100, 200],
        "size": [800, 600],
        "monitor": 0,
        "workspace": {"id": 1},
        "hidden": False,
        "fullscreen": False,
    }
    ipc.send.return_value = json.dumps([client])

    # Simulate openwindow event
    listener._handle_openwindow("abc123,workspace1,kitty,Title")

    # Should have called eval_lua with float + resize + move
    assert ipc.eval_lua.called
    lua_code = ipc.eval_lua.call_args[0][0]
    assert "float" in lua_code
    assert "resize" in lua_code
    assert "move" in lua_code
    # Uses spawn geometry (800x600) and centers it
    assert "x = 800, y = 600" in lua_code
    assert "x = 560.0, y = 240.0" in lua_code
    navigator.get_canvas_visual_center.assert_called_once_with(1, 0)
    navigator.register_spawned_during_canvas.assert_called_once_with(1, "0xabc123")


def test_event_listener_openwindow_already_floating_ignored():
    """openwindow for already floating window does nothing."""
    ipc = MagicMock()
    navigator = MagicMock()
    navigator.is_canvas_active.return_value = True
    stop_event = threading.Event()
    listener = EventListener(navigator=navigator, ipc=ipc, stop_event=stop_event)

    client = {
        "address": "0xabc123",
        "floating": True,  # Already floating
        "at": [100, 200],
        "size": [800, 600],
        "workspace": {"id": 1},
    }
    ipc.send.return_value = json.dumps([client])

    listener._handle_openwindow("abc123,workspace1,kitty,Title")

    # Should NOT call eval_lua
    ipc.eval_lua.assert_not_called()
    navigator.register_spawned_during_canvas.assert_not_called()


def test_event_listener_openwindow_workspace_not_canvas_ignored():
    """openwindow on non-Canvas workspace is ignored."""
    ipc = MagicMock()
    navigator = MagicMock()
    navigator.is_canvas_active.return_value = False
    stop_event = threading.Event()
    listener = EventListener(navigator=navigator, ipc=ipc, stop_event=stop_event)

    client = {
        "address": "0xabc123",
        "floating": False,
        "at": [100, 200],
        "size": [800, 600],
        "workspace": {"id": 99},
    }
    ipc.send.return_value = json.dumps([client])

    listener._handle_openwindow("abc123,workspace1,kitty,Title")

    ipc.eval_lua.assert_not_called()
    navigator.register_spawned_during_canvas.assert_not_called()


def test_event_listener_openwindow_retry_on_missing_client():
    """openwindow retries if client not yet in j/clients."""
    ipc = MagicMock()
    navigator = MagicMock()
    navigator.is_canvas_active.return_value = True
    navigator.get_spawn_geometry.return_value = (800, 600)
    navigator.get_canvas_visual_center.return_value = (960.0, 540.0)
    stop_event = threading.Event()
    listener = EventListener(navigator=navigator, ipc=ipc, stop_event=stop_event)

    # Test the retry logic directly by calling _process_new_window
    # First call: empty clients
    ipc.send.return_value = json.dumps([])
    listener._process_new_window("0xabc123", attempt=0)

    # Should have scheduled a retry
    with listener._pending_lock:
        assert "0xabc123" in listener._pending_retries
        attempt, deadline = listener._pending_retries["0xabc123"]
        assert attempt == 1

    # Manually set deadline to past to force immediate retry
    with listener._pending_lock:
        listener._pending_retries["0xabc123"] = (1, time.monotonic() - 1)

    # Now process the retry
    client = {
        "address": "0xabc123",
        "floating": False,
        "at": [100, 200],
        "size": [800, 600],
        "monitor": 0,
        "workspace": {"id": 1},
        "hidden": False,
        "fullscreen": False,
    }
    ipc.send.return_value = json.dumps([client])
    listener._process_pending_retries()

    # Should have called eval_lua
    assert ipc.eval_lua.called


def _run_openwindow_with_real_navigator(
    *,
    client: dict,
    monitors: list[dict],
    spawn_geometry: tuple[int, int] | None,
    viewport: CanvasViewport | None = None,
) -> tuple[str, Navigator]:
    ipc = MagicMock()

    def send(command: str) -> str:
        if command == "j/clients":
            return json.dumps([client])
        if command == "j/monitors":
            return json.dumps(monitors)
        raise AssertionError(f"unexpected IPC command: {command}")

    ipc.send.side_effect = send
    ipc.get_canvas_viewport.return_value = viewport or CanvasViewport()
    with patch(
        "canvas.navigation.toggle_state.load",
        return_value={1: {"active": True, "tiled": {}, "floating": {}}},
    ):
        navigator = Navigator(ipc=ipc, protected_apps=[], cooldown=0.0)
    with patch.object(navigator, "get_spawn_geometry", return_value=spawn_geometry):
        listener = EventListener(
            navigator=navigator,
            ipc=ipc,
            stop_event=threading.Event(),
        )
        listener._handle_openwindow("abc123,workspace1,kitty,Title")

    assert ipc.eval_lua.called
    return ipc.eval_lua.call_args.args[0], navigator


def _spawn_client(
    *,
    at: list[int] | None = None,
    size: list[int] | None = None,
    monitor: int = 0,
) -> dict:
    return {
        "address": "0xabc123",
        "floating": False,
        "at": at or [100, 200],
        "size": size or [800, 600],
        "monitor": monitor,
        "workspace": {"id": 1},
        "hidden": False,
        "fullscreen": False,
    }


def _monitor(
    *,
    monitor_id: int = 0,
    x: int = 0,
    y: int = 0,
    width: int = 1920,
    height: int = 1080,
    scale: float = 1.0,
    transform: int = 0,
) -> dict:
    return {
        "id": monitor_id,
        "focused": monitor_id == 0,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "scale": scale,
        "transform": transform,
    }


def test_event_listener_openwindow_second_monitor_uses_global_offset():
    lua, _nav = _run_openwindow_with_real_navigator(
        client=_spawn_client(monitor=1),
        monitors=[_monitor(), _monitor(monitor_id=1, x=1920)],
        spawn_geometry=(800, 600),
    )

    assert "x = 2480.0, y = 240.0" in lua


def test_event_listener_openwindow_non_1080_monitor_uses_real_center():
    lua, _nav = _run_openwindow_with_real_navigator(
        client=_spawn_client(),
        monitors=[_monitor(width=2560, height=1440)],
        spawn_geometry=(800, 600),
    )

    assert "x = 880.0, y = 420.0" in lua


def test_event_listener_openwindow_fractional_scale_uses_logical_center():
    lua, _nav = _run_openwindow_with_real_navigator(
        client=_spawn_client(),
        monitors=[_monitor(width=2560, height=1440, scale=1.25)],
        spawn_geometry=(800, 600),
    )

    assert "x = 624.0, y = 276.0" in lua


def test_event_listener_openwindow_rotated_monitor_swaps_axes():
    lua, _nav = _run_openwindow_with_real_navigator(
        client=_spawn_client(),
        monitors=[_monitor(width=2560, height=1440, transform=1)],
        spawn_geometry=(800, 600),
    )

    assert "x = 320.0, y = 980.0" in lua


def test_event_listener_openwindow_pan_zoom_uses_world_center():
    lua, _nav = _run_openwindow_with_real_navigator(
        client=_spawn_client(monitor=1),
        monitors=[_monitor(), _monitor(monitor_id=1, x=1920)],
        spawn_geometry=(800, 600),
        viewport=CanvasViewport(
            enabled=True,
            zoom=0.5,
            offset_x=100.0,
            offset_y=-50.0,
            monitor_x=1920.0,
            monitor_y=0.0,
        ),
    )

    assert "x = 3540.0, y = 730.0" in lua


def test_event_listener_openwindow_missing_monitor_uses_current_window_center():
    lua, _nav = _run_openwindow_with_real_navigator(
        client=_spawn_client(at=[100, 200], size=[900, 700], monitor=99),
        monitors=[_monitor()],
        spawn_geometry=(800, 600),
    )

    assert "x = 150.0, y = 250.0" in lua


def test_event_listener_openwindow_size_fallback_keeps_cap_and_new_center():
    lua, _nav = _run_openwindow_with_real_navigator(
        client=_spawn_client(size=[1600, 900]),
        monitors=[_monitor(width=2560, height=1440)],
        spawn_geometry=None,
    )

    assert "x = 1200, y = 800" in lua
    assert "x = 680.0, y = 320.0" in lua


def test_event_listener_closewindow_removes_from_state():
    """closewindow removes address from navigator state."""
    ipc = MagicMock()
    navigator = MagicMock()
    stop_event = threading.Event()
    listener = EventListener(navigator=navigator, ipc=ipc, stop_event=stop_event)

    listener._handle_closewindow("0xabc123")

    navigator.unregister_window.assert_called_once_with("0xabc123")


def test_event_listener_closewindow_cancels_pending_retry():
    """closewindow cancels any pending retry for that address."""
    ipc = MagicMock()
    navigator = MagicMock()
    navigator.is_canvas_active.return_value = True
    stop_event = threading.Event()
    listener = EventListener(navigator=navigator, ipc=ipc, stop_event=stop_event)

    # Trigger a retry
    ipc.send.return_value = json.dumps([])  # Empty -> triggers retry
    listener._handle_openwindow("abc123,workspace1,kitty,Title")

    # Now closewindow should cancel the retry
    listener._handle_closewindow("0xabc123")

    # Retry should be cancelled (no eval_lua should be called later)
    navigator.unregister_window.assert_called_once_with("0xabc123")


def test_event_listener_movewindowv2_parses_and_normalizes():
    ipc = MagicMock()
    navigator = MagicMock()
    client = {
        "address": "0xabcdef",
        "workspace": {"id": 6},
        "floating": True,
        "at": [10, 20],
        "size": [300, 200],
    }
    ipc.send.return_value = json.dumps([client])
    listener = _make_event_listener(navigator=navigator, ipc=ipc)

    listener._handle_line("movewindowv2>>ABCDEF,6,6")

    navigator.handle_window_moved.assert_called_once_with("0xabcdef", 6, "6", client)


def test_event_listener_movewindowv2_malformed_payload_ignored():
    ipc = MagicMock()
    navigator = MagicMock()
    listener = _make_event_listener(navigator=navigator, ipc=ipc)

    for line in (
        "movewindowv2>>",
        "movewindowv2>>abcdef,6",
        "movewindowv2>>not-hex,6,6",
        "movewindowv2>>abcdef,nope,6",
        "movewindowv2>>abcdef,0,0",
        "movewindowv2>>abcdef,-1,special",
        "movewindowv2>>abcdef,6,",
    ):
        listener._handle_line(line)

    ipc.send.assert_not_called()
    navigator.handle_window_moved.assert_not_called()


def test_event_listener_legacy_movewindow_is_not_processed():
    ipc = MagicMock()
    navigator = MagicMock()
    listener = _make_event_listener(navigator=navigator, ipc=ipc)

    listener._handle_line("movewindow>>abcdef,6")

    ipc.send.assert_not_called()
    navigator.handle_window_moved.assert_not_called()


def test_event_listener_movewindowv2_stale_destination_ignored():
    ipc = MagicMock()
    navigator = MagicMock()
    ipc.send.return_value = json.dumps(
        [{"address": "0xabcdef", "workspace": {"id": 3}, "floating": True}]
    )
    listener = _make_event_listener(navigator=navigator, ipc=ipc)

    listener._handle_line("movewindowv2>>abcdef,6,6")

    ipc.send.assert_called_once_with("j/clients")
    navigator.handle_window_moved.assert_not_called()
