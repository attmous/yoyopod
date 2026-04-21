"""UI-owned screen construction and registration helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yoyopod.app import YoyoPodApp


def build_and_register_screens(app: "YoyoPodApp", *, logger: Any) -> None:
    """Create and register all screen instances for the running app."""
    assert app.display is not None
    assert app.context is not None
    assert app.screen_manager is not None

    from yoyopod.ui.screens.music.now_playing import (
        NowPlayingScreen,
        build_now_playing_actions,
        build_now_playing_state_provider,
    )
    from yoyopod.ui.screens.music.playlist import PlaylistScreen
    from yoyopod.ui.screens.music.recent import RecentTracksScreen
    from yoyopod.ui.screens.navigation.ask import AskScreen
    from yoyopod.ui.screens.navigation.home import HomeScreen
    from yoyopod.ui.screens.navigation.hub import HubScreen
    from yoyopod.ui.screens.navigation.listen import ListenScreen
    from yoyopod.ui.screens.navigation.menu import MenuScreen
    from yoyopod.ui.screens.system.power import (
        PowerScreen,
        build_power_screen_actions,
        build_power_screen_state_provider,
    )
    from yoyopod.ui.screens.voip.call_history import CallHistoryScreen
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

    display = app.display
    context = app.context
    screen_manager = app.screen_manager
    volume_controller = app.audio_volume_controller
    if volume_controller is None:
        raise RuntimeError("Audio volume controller is not initialized")

    menu_items = ["Listen", "Talk", "Ask", "Setup"]
    app.hub_screen = HubScreen(
        display,
        context,
        music_backend=app.music_backend,
        local_music_service=app.local_music_service,
        voip_manager=app.voip_manager,
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
            music_backend=app.music_backend,
        ),
        actions=build_now_playing_actions(
            context=context,
            music_backend=app.music_backend,
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
        voip_manager=app.voip_manager,
        people_directory=app.people_directory,
        call_history_store=app.call_history_store,
    )
    app.call_history_screen = CallHistoryScreen(
        display,
        context,
        voip_manager=app.voip_manager,
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
        voip_manager=app.voip_manager,
        people_directory=app.people_directory,
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
        voip_manager=app.voip_manager,
        caller_address="",
        caller_name="Unknown",
    )
    app.outgoing_call_screen = OutgoingCallScreen(
        display,
        context,
        voip_manager=app.voip_manager,
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
