"""Tests for mpv process lifecycle manager."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from yoyopod.backends.music.models import MusicConfig
from yoyopod.backends.music.process import MpvProcess


def _make_config(tmp_path: Path) -> MusicConfig:
    return MusicConfig(
        music_dir=tmp_path,
        mpv_socket=str(tmp_path / "mpv.sock"),
        mpv_binary="mpv",
        alsa_device="default",
    )


def test_spawn_builds_correct_command(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    proc = MpvProcess(config)
    with patch("yoyopod.backends.music.process.subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        assert proc.spawn() is True

        args = mock_popen.call_args[0][0]
        assert args[0] == "mpv"
        assert "--idle" in args
        assert "--no-video" in args
        assert f"--input-ipc-server={config.mpv_socket}" in args
        assert "--audio-device=alsa/default" in args


def test_is_alive_false_when_not_spawned(tmp_path: Path) -> None:
    proc = MpvProcess(_make_config(tmp_path))
    assert proc.is_alive() is False


def test_is_alive_true_when_running(tmp_path: Path) -> None:
    proc = MpvProcess(_make_config(tmp_path))
    with patch("yoyopod.backends.music.process.subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        proc.spawn()
        assert proc.is_alive() is True


def test_kill_terminates_and_cleans_socket(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    sock_path = Path(config.mpv_socket)
    sock_path.touch()
    proc = MpvProcess(config)
    with patch("yoyopod.backends.music.process.subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        proc.spawn()

        mock_process.poll.return_value = 0
        proc.kill()
        mock_process.terminate.assert_called_once()
        assert not sock_path.exists()


def test_respawn_kills_then_spawns(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    proc = MpvProcess(config)
    with patch("yoyopod.backends.music.process.subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        proc.spawn()

        mock_process.poll.return_value = 0
        assert proc.respawn() is True
        assert mock_process.terminate.call_count == 1
        assert mock_popen.call_count == 2

