"""Tests for the split FSM orchestration layer and derived runtime state."""

from yoyopy.coordinators.runtime import AppRuntimeState, CoordinatorRuntime
from yoyopy.fsm import (
    CallFSM,
    CallInterruptionPolicy,
    CallSessionState,
    MusicFSM,
    MusicState,
)


def _build_runtime() -> CoordinatorRuntime:
    """Create a minimal coordinator runtime for state-derivation tests."""
    return CoordinatorRuntime(
        music_fsm=MusicFSM(),
        call_fsm=CallFSM(),
        call_interruption_policy=CallInterruptionPolicy(),
        screen_manager=None,
        mopidy_client=None,
        now_playing_screen=None,
        call_screen=None,
        incoming_call_screen=None,
        outgoing_call_screen=None,
        in_call_screen=None,
        config={},
        config_manager=None,
    )


def test_music_fsm_transitions() -> None:
    """MusicFSM should support play, pause, and stop transitions."""
    fsm = MusicFSM()

    assert fsm.state == MusicState.IDLE
    assert fsm.transition("play")
    assert fsm.state == MusicState.PLAYING
    assert fsm.transition("pause")
    assert fsm.state == MusicState.PAUSED
    assert fsm.transition("play")
    assert fsm.state == MusicState.PLAYING
    assert fsm.transition("stop")
    assert fsm.state == MusicState.IDLE
    assert not fsm.transition("pause")


def test_call_fsm_transitions() -> None:
    """CallFSM should model incoming, outgoing, connect, and end flows."""
    fsm = CallFSM()

    assert fsm.state == CallSessionState.IDLE
    assert fsm.transition("incoming")
    assert fsm.state == CallSessionState.INCOMING
    assert fsm.transition("connect")
    assert fsm.state == CallSessionState.ACTIVE
    assert fsm.transition("end")
    assert fsm.state == CallSessionState.IDLE
    assert fsm.transition("dial")
    assert fsm.state == CallSessionState.OUTGOING
    assert fsm.transition("end")
    assert fsm.state == CallSessionState.IDLE
    assert not fsm.transition("connect")


def test_call_interruption_policy_pauses_and_resumes_music() -> None:
    """The interruption policy should remember whether playback was interrupted."""
    music_fsm = MusicFSM()
    policy = CallInterruptionPolicy()

    assert not policy.pause_for_call(music_fsm)
    assert not policy.should_auto_resume(auto_resume=True)

    assert music_fsm.transition("play")
    assert policy.pause_for_call(music_fsm)
    assert music_fsm.state == MusicState.PAUSED
    assert policy.should_auto_resume(auto_resume=True)
    assert not policy.should_auto_resume(auto_resume=False)

    policy.clear()
    assert not policy.music_interrupted_by_call


def test_runtime_state_is_derived_from_split_fsms() -> None:
    """CoordinatorRuntime should derive app state from music and call FSMs."""
    runtime = _build_runtime()

    state_change = runtime.set_ui_state(AppRuntimeState.MENU, trigger="test_menu")
    assert state_change.entered(AppRuntimeState.MENU)
    assert runtime.current_app_state == AppRuntimeState.MENU

    runtime.music_fsm.transition("play")
    state_change = runtime.sync_app_state("playback_playing")
    assert state_change.entered(AppRuntimeState.PLAYING)
    assert runtime.current_app_state == AppRuntimeState.PLAYING

    state_change = runtime.set_voip_ready(True)
    assert state_change.entered(AppRuntimeState.PLAYING_WITH_VOIP)
    assert runtime.current_app_state == AppRuntimeState.PLAYING_WITH_VOIP

    runtime.call_interruption_policy.pause_for_call(runtime.music_fsm)
    state_change = runtime.sync_app_state("auto_pause_for_call")
    assert state_change.entered(AppRuntimeState.PAUSED_BY_CALL)
    assert runtime.current_app_state == AppRuntimeState.PAUSED_BY_CALL

    runtime.call_fsm.transition("incoming")
    state_change = runtime.sync_app_state("incoming_call")
    assert state_change.entered(AppRuntimeState.CALL_INCOMING)
    assert runtime.current_app_state == AppRuntimeState.CALL_INCOMING

    runtime.call_fsm.transition("connect")
    state_change = runtime.sync_app_state("call_connected")
    assert state_change.entered(AppRuntimeState.CALL_ACTIVE_MUSIC_PAUSED)
    assert runtime.current_app_state == AppRuntimeState.CALL_ACTIVE_MUSIC_PAUSED

    runtime.call_fsm.transition("end")
    runtime.music_fsm.transition("play")
    runtime.call_interruption_policy.clear()
    state_change = runtime.sync_app_state("call_ended")
    assert state_change.entered(AppRuntimeState.PLAYING_WITH_VOIP)
    assert runtime.current_app_state == AppRuntimeState.PLAYING_WITH_VOIP


def test_runtime_returns_to_base_ui_state_when_music_and_calls_are_idle() -> None:
    """The derived app state should fall back to the current base UI state."""
    runtime = _build_runtime()

    runtime.set_ui_state(AppRuntimeState.PLAYLIST_BROWSER, trigger="browse_playlists")
    assert runtime.current_app_state == AppRuntimeState.PLAYLIST_BROWSER

    runtime.music_fsm.transition("play")
    runtime.sync_app_state("load_playlist")
    assert runtime.current_app_state == AppRuntimeState.PLAYING

    runtime.music_fsm.transition("stop")
    state_change = runtime.sync_app_state("stop")
    assert state_change.entered(AppRuntimeState.PLAYLIST_BROWSER)
    assert runtime.current_app_state == AppRuntimeState.PLAYLIST_BROWSER
