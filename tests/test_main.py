"""Tests for canvas.__main__ — CLI entry points."""

import contextlib
import sys
from unittest.mock import patch

from canvas.__main__ import ctl_main, daemon_main


def test_ctl_main_no_args_exits():
    with patch.object(sys, "argv", ["canvas-ctl"]):
        try:
            ctl_main()
            raise AssertionError("should have exited")
        except SystemExit as e:
            assert e.code == 2


def test_ctl_main_unknown_command_exits():
    with patch.object(sys, "argv", ["canvas-ctl", "foobar"]):
        try:
            ctl_main()
            raise AssertionError("should have exited")
        except SystemExit as e:
            assert e.code == 2


def test_ctl_main_valid_command_sends():
    """canvas-ctl with valid command calls send_command and prints response."""
    with (
        patch.object(sys, "argv", ["canvas-ctl", "ping"]),
        patch("canvas.ipc.send_command", return_value="PONG") as mock_send,
        patch("builtins.print") as mock_print,
    ):
        ctl_main()
        mock_send.assert_called_with("PING")
        mock_print.assert_called_with("PONG")


def test_ctl_main_center_cursor_command():
    """canvas-ctl center-cursor normalizes to CENTER_CURSOR."""
    with (
        patch.object(sys, "argv", ["canvas-ctl", "center-cursor"]),
        patch("canvas.ipc.send_command", return_value="OK") as mock_send,
    ):
        ctl_main()
        mock_send.assert_called_with("CENTER_CURSOR")


def test_ctl_main_canvas_toggle_without_workspace_preserves_legacy_command():
    with patch("canvas.ipc.send_command", return_value="CANVAS_ON") as mock_send:
        ctl_main(["canvas-toggle"])
        mock_send.assert_called_once_with("CANVAS_TOGGLE")


def test_ctl_main_canvas_toggle_with_workspace_sends_explicit_target():
    with patch("canvas.ipc.send_command", return_value="CANVAS_ON") as mock_send:
        ctl_main(["canvas-toggle", "2"])
        mock_send.assert_called_once_with("CANVAS_TOGGLE 2")


def test_ctl_main_canvas_toggle_all_accepts_optional_workspace():
    with patch("canvas.ipc.send_command", return_value="CANVAS_ON") as mock_send:
        ctl_main(["canvas-toggle-all"])
        mock_send.assert_called_once_with("CANVAS_TOGGLE_ALL")

    with patch("canvas.ipc.send_command", return_value="CANVAS_ON") as mock_send:
        ctl_main(["canvas-toggle-all", "4"])
        mock_send.assert_called_once_with("CANVAS_TOGGLE_ALL 4")


def test_ctl_main_canvas_toggle_rejects_invalid_workspace_without_ipc():
    for value in ("0", "-1", "abc"):
        with patch("canvas.ipc.send_command") as mock_send:
            try:
                ctl_main(["canvas-toggle", value])
                raise AssertionError("should have exited")
            except SystemExit as exc:
                assert exc.code == 2
            mock_send.assert_not_called()


def test_ctl_main_zoom_commands():
    for command, expected in [
        ("zoom-in", "ZOOM_IN"),
        ("zoom-out", "ZOOM_OUT"),
        ("zoom-reset", "ZOOM_RESET"),
    ]:
        with (
            patch.object(sys, "argv", ["canvas-ctl", command]),
            patch("canvas.ipc.send_command", return_value="OK") as mock_send,
        ):
            ctl_main()
            mock_send.assert_called_once_with(expected)


def test_ctl_main_edge_start_command():
    """canvas-ctl edge-start normalizes to EDGE_START."""
    with (
        patch.object(sys, "argv", ["canvas-ctl", "edge-start"]),
        patch("canvas.ipc.send_command", return_value="EDGE_ON") as mock_send,
    ):
        ctl_main()
        mock_send.assert_called_with("EDGE_START")


def test_ctl_main_no_response_no_print():
    """canvas-ctl exits 1 when send_command returns empty string."""
    with (
        patch.object(sys, "argv", ["canvas-ctl", "ping"]),
        patch("canvas.ipc.send_command", return_value=""),
        patch("builtins.print") as mock_print,
    ):
        try:
            ctl_main()
            raise AssertionError("should have exited")
        except SystemExit as e:
            assert e.code == 1
        mock_print.assert_called_once()


def test_ctl_main_error_response_exits():
    """canvas-ctl exits 1 when the daemon returns an ERROR response."""
    with (
        patch.object(sys, "argv", ["canvas-ctl", "ping"]),
        patch("canvas.ipc.send_command", return_value="ERROR: daemon not running"),
        patch("builtins.print"),
    ):
        try:
            ctl_main()
            raise AssertionError("should have exited")
        except SystemExit as e:
            assert e.code == 1


def test_daemon_main_calls_run():
    """daemon_main delegates to daemon.run()."""
    with patch("canvas.daemon.run") as mock_run:
        daemon_main([])
        mock_run.assert_called_once()


def test_ctl_main_help_lists_commands(capsys):
    """--help exits 0 and names every command (canonical list lives in code)."""
    with patch.object(sys, "argv", ["canvas-ctl", "--help"]):
        try:
            ctl_main()
            raise AssertionError("should have exited")
        except SystemExit as e:
            assert e.code == 0
    out = capsys.readouterr().out
    for name, _ in [
        ("ping", ""),
        ("status", ""),
        ("pan-start", ""),
        ("pan-stop", ""),
        ("nav-left", ""),
        ("nav-right", ""),
        ("nav-up", ""),
        ("nav-down", ""),
        ("center-cursor", ""),
        ("zoom-in", ""),
        ("zoom-out", ""),
        ("zoom-reset", ""),
        ("canvas-toggle", ""),
        ("canvas-toggle-all", ""),
        ("canvas-toggle-single", ""),
        ("toggle", ""),
        ("edge-start", ""),
        ("edge-stop", ""),
    ]:
        assert name in out


def test_ctl_main_version(capsys):
    """--version exits 0 and prints name + version from a single source."""
    from canvas import __version__

    with patch.object(sys, "argv", ["canvas-ctl", "--version"]):
        try:
            ctl_main()
            raise AssertionError("should have exited")
        except SystemExit as e:
            assert e.code == 0
    out = capsys.readouterr().out
    assert "canvas-ctl" in out and __version__ in out


def test_daemon_main_help_and_rejects_positional(capsys):
    """daemon --help exits 0; stray positionals exit 2 instead of starting."""
    with patch.object(sys, "argv", ["canvasd", "--help"]):
        try:
            daemon_main()
            raise AssertionError("should have exited")
        except SystemExit as e:
            assert e.code == 0
    with patch.object(sys, "argv", ["canvasd", "--help"]):
        try:
            daemon_main()
            raise AssertionError("should have exited")
        except SystemExit as e:
            assert e.code == 0
    with patch.object(sys, "argv", ["canvasd", "whatever"]):
        try:
            daemon_main()
            raise AssertionError("should have exited")
        except SystemExit as e:
            assert e.code == 2
    with (
        patch("canvas.daemon.run") as mock_run,
        patch.object(sys, "argv", ["canvasd", "--version"]),
        contextlib.suppress(SystemExit),
    ):
        daemon_main()
        mock_run.assert_not_called()
