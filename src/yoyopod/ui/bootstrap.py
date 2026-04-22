"""UI-owned screen construction and registration helpers."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yoyopod.app import YoyoPodApp


def build_and_register_screens(app: "YoyoPodApp", *, logger: Any) -> None:
    """Create and register all screen instances for the running app."""
    assert app.display is not None
    assert app.context is not None
    assert app.screen_manager is not None

    from yoyopod.ui.screens.music.now_playing import (
        NowPlayingSnapshot,
        NowPlayingScreen,
        build_now_playing_actions,
        build_now_playing_state_provider,
    )
    from yoyopod.ui.screens.music.playlist import PlaylistScreen
    from yoyopod.ui.screens.music.recent import RecentTracksScreen
    from yoyopod.ui.screens.navigation.ask import AskScreen
    from yoyopod.ui.screens.navigation.home import HomeScreen
    from yoyopod.ui.screens.navigation.hub import (
        HubListenSnapshot,
        HubScreen,
        build_hub_listen_subtitle_provider,
    )
    from yoyopod.ui.screens.navigation.listen import ListenScreen
    from yoyopod.ui.screens.navigation.menu import MenuScreen
    from yoyopod.ui.screens.system.power import (
        PowerScreen,
        build_power_screen_actions,
        build_power_screen_state_provider,
    )
    from yoyopod.ui.screens.voip.call_history import CallHistoryScreen
    from yoyopod.ui.screens.voip.call_actions import CallActions
    from yoyopod.ui.screens.voip.contact_list import ContactListScreen
    from yoyopod.ui.screens.voip.in_call import InCallScreen
    from yoyopod.ui.screens.voip.incoming_call import IncomingCallScreen
    from yoyopod.ui.screens.voip.outgoing_call import OutgoingCallScreen
    from yoyopod.ui.screens.voip.quick_call import CallScreen
    from yoyopod.ui.screens.voip.talk_contact import TalkContactScreen
    from yoyopod.ui.screens.voip.voice_note import (
        VoiceNoteScreen,
        build_voice_note_actions,
        build_voice_note_state_provider,
    )
    from yoyopod.coordinators.voice import (
        VoiceCommandExecutor,
        VoiceRuntimeCoordinator,
        VoiceSettingsResolver,
    )
    from yoyopod.voice.models import VoiceSettings

    HUB_LISTEN_PLAYLIST_CACHE_SECONDS = 30.0
    cached_playlist_count: int | None = None
    cached_playlist_count_valid_until = 0.0

    display = app.display
    context = app.context
    screen_manager = app.screen_manager
    volume_controller = app.audio_volume_controller
    if volume_controller is None:
        raise RuntimeError("Audio volume controller is not initialized")

    def _playback_snapshot() -> NowPlayingSnapshot:
        if app.playback_coordinator is not None:
            snapshot = app.playback_coordinator.get_playback_snapshot()
            return NowPlayingSnapshot(
                is_connected=snapshot.is_connected,
                track=snapshot.track,
                playback_state=snapshot.playback_state,
                time_position=snapshot.time_position,
            )

        if app.music_backend is not None:
            if not app.music_backend.is_connected:
                return NowPlayingSnapshot(is_connected=False)
            return NowPlayingSnapshot(
                is_connected=True,
                track=app.music_backend.get_current_track(),
                playback_state=app.music_backend.get_playback_state(),
                time_position=float(app.music_backend.get_time_position()),
            )

        track = context.get_current_track()
        playback_state = "stopped"
        if context.media.playback.is_playing:
            playback_state = "playing"
        elif context.media.playback.is_paused:
            playback_state = "paused"
        time_position = 0.0
        if track is not None and track.length > 0:
            time_position = context.get_playback_progress() * track.length
        return NowPlayingSnapshot(
            is_connected=True,
            track=track,
            playback_state=playback_state,
            time_position=time_position,
        )

    def _hub_listen_snapshot() -> HubListenSnapshot:
        """Return cached playback + library snapshot data for the hub card."""

        def _playlist_count() -> int | None:
            nonlocal cached_playlist_count, cached_playlist_count_valid_until

            if time.monotonic() < cached_playlist_count_valid_until:
                return cached_playlist_count

            playlist_count: int | None = None
            if app.playback_coordinator is not None:
                playlist_count = app.playback_coordinator.get_playlist_count()
            elif app.local_music_service is not None and app.local_music_service.is_available:
                try:
                    playlist_count = app.local_music_service.playlist_count()
                except Exception:
                    playlist_count = None
            cached_playlist_count = playlist_count
            cached_playlist_count_valid_until = time.monotonic() + HUB_LISTEN_PLAYLIST_CACHE_SECONDS
            return playlist_count

        snapshot = _playback_snapshot()
        return HubListenSnapshot(
            is_connected=snapshot.is_connected,
            track=snapshot.track,
            playback_state=snapshot.playback_state,
            playlist_count=_playlist_count(),
        )

    def _list_callable_contacts():
        if app.call_coordinator is not None:
            return app.call_coordinator.list_callable_contacts()
        if app.people_directory is None:
            return []
        contacts = list(app.people_directory.get_callable_contacts(gsm_enabled=False))
        favorites = [contact for contact in contacts if contact.favorite]
        others = [contact for contact in contacts if not contact.favorite]
        return favorites + others

    def _make_call(sip_address: str, contact_name: str | None = None) -> bool:
        if app.call_coordinator is not None:
            return app.call_coordinator.make_call(sip_address, contact_name=contact_name)
        if app.voip_manager is None:
            return False
        return bool(app.voip_manager.make_call(sip_address, contact_name=contact_name))

    def _answer_call() -> bool:
        if app.call_coordinator is not None:
            return app.call_coordinator.answer_call()
        if app.voip_manager is None:
            return False
        return bool(app.voip_manager.answer_call())

    def _reject_call() -> bool:
        if app.call_coordinator is not None:
            return app.call_coordinator.reject_call()
        if app.voip_manager is None:
            return False
        return bool(app.voip_manager.reject_call())

    def _hangup_call() -> bool:
        if app.call_coordinator is not None:
            return app.call_coordinator.hangup_call()
        if app.voip_manager is None:
            return False
        return bool(app.voip_manager.hangup())

    def _ready_to_call() -> bool:
        if app.call_coordinator is not None:
            return app.call_coordinator.is_ready_to_call()
        if app.voip_manager is None:
            return False
        return bool(app.voip_manager.running and app.voip_manager.registered)

    def _toggle_playback() -> None:
        if app.playback_coordinator is not None:
            app.playback_coordinator.toggle_playback()
            return
        context.toggle_playback()

    def _previous_track() -> None:
        if app.playback_coordinator is not None:
            app.playback_coordinator.previous_track()
            return
        context.previous_track()

    def _next_track() -> None:
        if app.playback_coordinator is not None:
            app.playback_coordinator.next_track()
            return
        context.next_track()

    call_actions = CallActions(
        answer_call=_answer_call,
        reject_call=_reject_call,
        hangup_call=_hangup_call,
        make_call=_make_call,
    )

    menu_items = ["Listen", "Talk", "Ask", "Setup"]
    app.hub_screen = HubScreen(
        display,
        context,
        listen_subtitle_provider=build_hub_listen_subtitle_provider(
            display,
            snapshot_provider=_hub_listen_snapshot,
        ),
    )
    app.menu_screen = MenuScreen(display, context, items=menu_items)
    app.home_screen = HomeScreen(display, context)
    app.listen_screen = ListenScreen(
        display,
        context,
        music_service=app.local_music_service,
    )
    voice_cfg = app.config_manager.get_voice_settings() if app.config_manager is not None else None
    app.voice_runtime = VoiceRuntimeCoordinator(
        context=context,
        settings_resolver=VoiceSettingsResolver(
            context=context,
            config_manager=app.config_manager,
            settings_provider=lambda: VoiceSettings(
                commands_enabled=(
                    app.context.voice.commands_enabled if app.context is not None else True
                ),
                ai_requests_enabled=(
                    app.context.voice.ai_requests_enabled if app.context is not None else True
                ),
                screen_read_enabled=(
                    app.context.voice.screen_read_enabled if app.context is not None else False
                ),
                stt_enabled=(app.context.voice.stt_enabled if app.context is not None else True),
                tts_enabled=(app.context.voice.tts_enabled if app.context is not None else True),
                mic_muted=(app.context.voice.mic_muted if app.context is not None else False),
                output_volume=volume_controller.get_output_volume()
                or (app.context.voice.output_volume if app.context is not None else 50),
                stt_backend=voice_cfg.assistant.stt_backend if voice_cfg is not None else "vosk",
                tts_backend=(
                    voice_cfg.assistant.tts_backend if voice_cfg is not None else "espeak-ng"
                ),
                vosk_model_path=(
                    voice_cfg.assistant.vosk_model_path
                    if voice_cfg is not None
                    else "models/vosk-model-small-en-us"
                ),
                vosk_model_keep_loaded=(
                    voice_cfg.assistant.vosk_model_keep_loaded if voice_cfg is not None else True
                ),
                speaker_device_id=(
                    app.context.voice.speaker_device_id
                    if app.context is not None and app.context.voice.speaker_device_id is not None
                    else (
                        voice_cfg.audio.speaker_device_id.strip() or None
                        if voice_cfg is not None
                        else None
                    )
                ),
                capture_device_id=(
                    app.context.voice.capture_device_id
                    if app.context is not None and app.context.voice.capture_device_id is not None
                    else (
                        voice_cfg.audio.capture_device_id.strip() or None
                        if voice_cfg is not None
                        else None
                    )
                ),
                sample_rate_hz=(
                    voice_cfg.assistant.sample_rate_hz if voice_cfg is not None else 16000
                ),
                record_seconds=voice_cfg.assistant.record_seconds if voice_cfg is not None else 4,
                tts_rate_wpm=voice_cfg.assistant.tts_rate_wpm if voice_cfg is not None else 155,
                tts_voice=voice_cfg.assistant.tts_voice if voice_cfg is not None else "en",
            ),
        ),
        command_executor=VoiceCommandExecutor(
            context=context,
            config_manager=app.config_manager,
            people_directory=app.people_directory,
            voip_manager=app.voip_manager,
            volume_up_action=volume_controller.volume_up,
            volume_down_action=volume_controller.volume_down,
            mute_action=(app.voip_manager.mute if app.voip_manager is not None else None),
            unmute_action=(app.voip_manager.unmute if app.voip_manager is not None else None),
            play_music_action=(
                app.local_music_service.shuffle_all if app.local_music_service is not None else None
            ),
        ),
    )
    app.ask_screen = AskScreen(
        display,
        context,
        config_manager=app.config_manager,
        people_directory=app.people_directory,
        voip_manager=app.voip_manager,
        volume_up_action=volume_controller.volume_up,
        volume_down_action=volume_controller.volume_down,
        mute_action=(app.voip_manager.mute if app.voip_manager is not None else None),
        unmute_action=(app.voip_manager.unmute if app.voip_manager is not None else None),
        play_music_action=(
            app.local_music_service.shuffle_all if app.local_music_service is not None else None
        ),
        voice_runtime=app.voice_runtime,
    )
    app.power_screen = PowerScreen(
        display,
        context,
        state_provider=build_power_screen_state_provider(
            power_manager=app.power_manager,
            network_manager=app.network_manager,
            status_provider=app.get_status,
            playback_device_options_provider=(
                app.audio_device_catalog.playback_devices
                if app.audio_device_catalog is not None
                else None
            ),
            capture_device_options_provider=(
                app.audio_device_catalog.capture_devices
                if app.audio_device_catalog is not None
                else None
            ),
        ),
        actions=build_power_screen_actions(
            network_manager=app.network_manager,
            refresh_voice_device_options_action=(
                app.audio_device_catalog.refresh_async
                if app.audio_device_catalog is not None
                else None
            ),
            persist_speaker_device_action=(
                app.config_manager.set_voice_speaker_device_id
                if app.config_manager is not None
                else None
            ),
            persist_capture_device_action=(
                app.config_manager.set_voice_capture_device_id
                if app.config_manager is not None
                else None
            ),
            volume_up_action=volume_controller.volume_up,
            volume_down_action=volume_controller.volume_down,
            mute_action=(app.voip_manager.mute if app.voip_manager is not None else None),
            unmute_action=(app.voip_manager.unmute if app.voip_manager is not None else None),
        ),
    )
    app.now_playing_screen = NowPlayingScreen(
        display,
        context,
        state_provider=build_now_playing_state_provider(
            context=context,
            snapshot_provider=_playback_snapshot,
        ),
        actions=build_now_playing_actions(
            context=context,
            toggle_playback_action=_toggle_playback,
            previous_track_action=_previous_track,
            next_track_action=_next_track,
        ),
    )
    app.playlist_screen = PlaylistScreen(
        display,
        context,
        music_service=app.local_music_service,
    )
    app.recent_tracks_screen = RecentTracksScreen(
        display,
        context,
        music_service=app.local_music_service,
    )
    app.call_screen = CallScreen(
        display,
        context,
        contacts_provider=_list_callable_contacts,
        call_history_store=app.call_history_store,
    )
    app.call_history_screen = CallHistoryScreen(
        display,
        context,
        actions=call_actions,
        ready_to_call_provider=_ready_to_call,
        call_history_store=app.call_history_store,
    )
    app.talk_contact_screen = TalkContactScreen(
        display,
        context,
        voip_manager=app.voip_manager,
    )
    app.contact_list_screen = ContactListScreen(
        display,
        context,
        contacts_provider=_list_callable_contacts,
        actions=call_actions,
    )
    app.voice_note_screen = VoiceNoteScreen(
        display,
        context,
        state_provider=build_voice_note_state_provider(
            context=context,
            voip_manager=app.voip_manager,
        ),
        actions=build_voice_note_actions(voip_manager=app.voip_manager),
    )
    app.incoming_call_screen = IncomingCallScreen(
        display,
        context,
        actions=call_actions,
        caller_address="",
        caller_name="Unknown",
    )
    app.outgoing_call_screen = OutgoingCallScreen(
        display,
        context,
        actions=call_actions,
        callee_address="",
        callee_name="Unknown",
    )
    app.in_call_screen = InCallScreen(
        display,
        context,
        voip_manager=app.voip_manager,
    )

    screen_manager.register_screen("hub", app.hub_screen)
    screen_manager.register_screen("home", app.home_screen)
    screen_manager.register_screen("menu", app.menu_screen)
    screen_manager.register_screen("listen", app.listen_screen)
    screen_manager.register_screen("ask", app.ask_screen)
    screen_manager.register_screen("power", app.power_screen)
    screen_manager.register_screen("now_playing", app.now_playing_screen)
    screen_manager.register_screen("playlists", app.playlist_screen)
    screen_manager.register_screen("recent_tracks", app.recent_tracks_screen)
    screen_manager.register_screen("call", app.call_screen)
    screen_manager.register_screen("talk_contact", app.talk_contact_screen)
    screen_manager.register_screen("call_history", app.call_history_screen)
    screen_manager.register_screen("contacts", app.contact_list_screen)
    screen_manager.register_screen("voice_note", app.voice_note_screen)
    screen_manager.register_screen("incoming_call", app.incoming_call_screen)
    screen_manager.register_screen("outgoing_call", app.outgoing_call_screen)
    screen_manager.register_screen("in_call", app.in_call_screen)
    logger.info("    - Whisplay root: hub")

    logger.info("  All screens registered")
    logger.info("    - Listen flow: listen, playlists, recent_tracks, now_playing")
    logger.info("    - Ask flow: ask")
    logger.info("    - Power screen: power")
    logger.info(
        "    - VoIP screens: call, talk_contact, call_history, contacts, voice_note, incoming_call, outgoing_call, in_call"
    )
    logger.info("    - Navigation: home, menu")
