"""Tests for canvas.hypr module — Hyprland IPC abstraction."""

from unittest.mock import MagicMock, patch

import pytest

from canvas.hypr import (
    CanvasViewport,
    HyprIPC,
    HyprIPCError,
    _hypr_socket2_path,
    eval_lua,
    get_cursor_pos,
    send,
)


def _make_ipc_with_mock(mock_sock: MagicMock) -> HyprIPC:
    """Create HyprIPC with a mock _connect that returns mock_sock."""
    ipc = HyprIPC("/tmp/test.sock")
    ipc._connect = lambda: mock_sock  # type: ignore[assignment]
    return ipc


def test_send_calls_socket():
    """send() connects, sends command, reads response."""
    mock_sock = MagicMock()
    mock_sock.recv.side_effect = [b"ok", b""]
    ipc = _make_ipc_with_mock(mock_sock)

    result = ipc.send("cursorpos")

    assert result == "ok"
    mock_sock.sendall.assert_called_once_with(b"cursorpos")


def test_eval_lua_prefixes_eval():
    """eval_lua prepends 'eval ' to lua code."""
    mock_sock = MagicMock()
    mock_sock.recv.side_effect = [b"ok", b""]
    ipc = _make_ipc_with_mock(mock_sock)

    result = ipc.eval_lua("hl.dispatch(hl.dsp.no_op())")

    assert result == "ok"
    mock_sock.sendall.assert_called_once_with(b"eval hl.dispatch(hl.dsp.no_op())")


def test_get_cursor_pos_parses_response():
    """get_cursor_pos parses 'X, Y' response."""
    mock_sock = MagicMock()
    mock_sock.recv.side_effect = [b"100, 200", b""]
    ipc = _make_ipc_with_mock(mock_sock)

    x, y = ipc.get_cursor_pos()

    assert x == 100
    assert y == 200


def test_send_closes_socket_after_response():
    """send() always closes the connection (server closes after each response)."""
    mock_sock = MagicMock()
    mock_sock.recv.side_effect = [b"ok", b""]
    ipc = _make_ipc_with_mock(mock_sock)

    result = ipc.send("cursorpos")

    assert result == "ok"
    mock_sock.close.assert_called_once()


def test_send_response_size_limit():
    """An oversized response aborts instead of consuming unbounded memory."""
    import canvas.hypr as hypr_mod

    mock_sock = MagicMock()
    chunk = b"x" * 4096
    mock_sock.recv.side_effect = lambda *_: chunk  # never returns EOF
    ipc = _make_ipc_with_mock(mock_sock)

    original = hypr_mod._MAX_RESPONSE
    hypr_mod._MAX_RESPONSE = 8192
    try:
        try:
            ipc.send("j/clients")
            raise AssertionError("should have raised ConnectionError")
        except ConnectionError as e:
            assert "size limit" in str(e)
    finally:
        hypr_mod._MAX_RESPONSE = original


def test_module_level_send_delegates_to_default():
    """Module-level send() delegates to default HyprIPC instance."""
    mock_sock = MagicMock()
    mock_sock.recv.side_effect = [b"module_ok", b""]

    with patch("canvas.hypr._get_default") as mock_get:
        ipc = _make_ipc_with_mock(mock_sock)
        mock_get.return_value = ipc
        result = send("cursorpos")

    assert result == "module_ok"


def test_module_level_eval_lua_delegates():
    """Module-level eval_lua() delegates to default HyprIPC instance."""
    mock_sock = MagicMock()
    mock_sock.recv.side_effect = [b"lua_ok", b""]

    with patch("canvas.hypr._get_default") as mock_get:
        ipc = _make_ipc_with_mock(mock_sock)
        mock_get.return_value = ipc
        result = eval_lua("print('hi')")

    assert result == "lua_ok"


def test_module_level_get_cursor_pos_delegates():
    """Module-level get_cursor_pos() delegates to default HyprIPC instance."""
    mock_sock = MagicMock()
    mock_sock.recv.side_effect = [b"42, 84", b""]

    with patch("canvas.hypr._get_default") as mock_get:
        ipc = _make_ipc_with_mock(mock_sock)
        mock_get.return_value = ipc
        x, y = get_cursor_pos()

    assert x == 42
    assert y == 84


def test_send_empty_response():
    """send() handles empty response from Hyprland."""
    mock_sock = MagicMock()
    mock_sock.recv.side_effect = [b""]
    ipc = _make_ipc_with_mock(mock_sock)

    result = ipc.send("cursorpos")

    assert result == ""


def test_send_raises_on_hyprland_error_response():
    """Hyprland's textual error response must not look like success."""
    mock_sock = MagicMock()
    mock_sock.recv.side_effect = [b"error: eval failed", b""]
    ipc = _make_ipc_with_mock(mock_sock)

    with pytest.raises(HyprIPCError, match="eval failed"):
        ipc.send("eval broken")


def test_send_connection_error():
    """send() raises when both persistent and fresh connections fail."""
    ipc = HyprIPC("/tmp/test.sock")
    ipc._connect = MagicMock(side_effect=ConnectionError("refused"))  # type: ignore[assignment]

    try:
        ipc.send("cursorpos")
        raise AssertionError("should have raised ConnectionError")
    except ConnectionError:
        pass


def test_get_cursor_pos_single_digit():
    """get_cursor_pos handles single-digit coordinates."""
    mock_sock = MagicMock()
    mock_sock.recv.side_effect = [b"0, 0", b""]
    ipc = _make_ipc_with_mock(mock_sock)

    x, y = ipc.get_cursor_pos()

    assert x == 0
    assert y == 0


def test_from_env_uses_hyprland_socket():
    """from_env() resolves socket path from HYPRLAND_INSTANCE_SIGNATURE."""
    with (
        patch("canvas.hypr.os.environ.get", return_value="test_sig"),
        patch("canvas.hypr.os.getuid", return_value=1000),
        patch("canvas.hypr.os.path.exists", return_value=True),
    ):
        ipc = HyprIPC.from_env()

    assert "test_sig" in ipc._socket_path


def test_socket2_strict_instance_does_not_fall_back_to_other_instance():
    exists = MagicMock(side_effect=lambda path: "/B/" in path)
    with (
        patch("canvas.hypr.os.environ.get", return_value="A"),
        patch("canvas.hypr.os.getuid", return_value=1000),
        patch("canvas.hypr.os.path.exists", exists),
        patch("canvas.hypr.os.path.isdir", return_value=True),
        patch("canvas.hypr.os.listdir", return_value=["B"]),
        pytest.raises(FileNotFoundError, match="current instance"),
    ):
        _hypr_socket2_path(strict_instance=True)

    exists.assert_called_once_with("/run/user/1000/hypr/A/.socket2.sock")


def test_socket2_strict_instance_path_can_reappear():
    exists = MagicMock(side_effect=[False, True])
    with (
        patch("canvas.hypr.os.environ.get", return_value="A"),
        patch("canvas.hypr.os.getuid", return_value=1000),
        patch("canvas.hypr.os.path.exists", exists),
        pytest.raises(FileNotFoundError, match="current instance"),
    ):
        _hypr_socket2_path(strict_instance=True)

    with (
        patch("canvas.hypr.os.environ.get", return_value="A"),
        patch("canvas.hypr.os.getuid", return_value=1000),
        patch("canvas.hypr.os.path.exists", exists),
    ):
        path = _hypr_socket2_path(strict_instance=True)

    assert path == "/run/user/1000/hypr/A/.socket2.sock"
    assert exists.call_count == 2


def test_get_active_window_geometry_parses():
    mock_sock = MagicMock()
    mock_sock.recv.side_effect = [
        b'{"address":"0xabc","at":[10,20],"size":[500,300]}',
        b"",
    ]
    ipc = _make_ipc_with_mock(mock_sock)

    geo = ipc.get_active_window_geometry()

    assert geo == ("0xabc", 10, 20, 500, 300)


def test_get_active_window_geometry_none_without_address():
    mock_sock = MagicMock()
    mock_sock.recv.side_effect = [b'{"at":[10,20],"size":[500,300]}', b""]
    ipc = _make_ipc_with_mock(mock_sock)

    assert ipc.get_active_window_geometry() is None


def test_get_active_window_geometry_none_on_malformed_fields():
    mock_sock = MagicMock()
    mock_sock.recv.side_effect = [
        b'{"address":"0xabc","at":[10],"size":[500,300]}',
        b"",
    ]
    ipc = _make_ipc_with_mock(mock_sock)

    assert ipc.get_active_window_geometry() is None


def test_module_level_get_active_window_geometry_delegates():
    mock_sock = MagicMock()
    mock_sock.recv.side_effect = [
        b'{"address":"0x9","at":[0,0],"size":[1,2]}',
        b"",
    ]

    from canvas.hypr import get_active_window_geometry

    with patch("canvas.hypr._get_default") as mock_get:
        ipc = _make_ipc_with_mock(mock_sock)
        mock_get.return_value = ipc
        geo = get_active_window_geometry()

    assert geo == ("0x9", 0, 0, 1, 2)


def test_canvas_viewport_round_trip():
    viewport = CanvasViewport(enabled=True, zoom=0.5, offset_x=100.0, offset_y=-50.0)
    sx, sy = viewport.world_to_screen(500.0, 350.0)
    assert (sx, sy) == (200.0, 200.0)
    assert viewport.screen_to_world(sx, sy) == (500.0, 350.0)


def test_canvas_viewport_round_trip_on_offset_monitor():
    viewport = CanvasViewport(
        enabled=True,
        zoom=0.5,
        offset_x=100.0,
        offset_y=-50.0,
        monitor_x=1920.0,
        monitor_y=120.0,
    )
    sx, sy = viewport.world_to_screen(2500.0, 700.0)
    assert viewport.screen_to_world(sx, sy) == (2500.0, 700.0)


def test_set_canvas_viewport_dispatches_zoom_action():
    ipc = HyprIPC("/tmp/test.sock")
    ipc.send = MagicMock(return_value="ok")  # type: ignore[method-assign]

    assert ipc.set_canvas_viewport("zoom-out", 7) is True
    ipc.send.assert_called_once_with("hypr-canvas zoom-out 7")


def test_set_canvas_viewport_rejects_unknown_action():
    ipc = HyprIPC("/tmp/test.sock")
    with pytest.raises(ValueError, match="invalid canvas viewport action"):
        ipc.set_canvas_viewport("resize-windows", 1)


def test_get_canvas_viewport_parses_camera_state():
    ipc = HyprIPC("/tmp/test.sock")
    ipc.send = MagicMock(  # type: ignore[method-assign]
        return_value='{"enabled":true,"zoom":0.5,"offset_x":120.0,"offset_y":-40.0,"monitor_x":1920.0,"monitor_y":120.0}'
    )

    viewport = ipc.get_canvas_viewport(3)
    assert viewport == CanvasViewport(True, 0.5, 120.0, -40.0, 1920.0, 120.0)
    ipc.send.assert_called_once_with("hypr-canvas status 3")


def test_get_canvas_viewport_invalid_zoom_falls_back_to_identity():
    ipc = HyprIPC("/tmp/test.sock")
    ipc.send = MagicMock(return_value='{"enabled":true,"zoom":1.5}')  # type: ignore[method-assign]

    assert ipc.get_canvas_viewport(3) == CanvasViewport()
