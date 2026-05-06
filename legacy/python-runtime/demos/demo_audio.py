#!/usr/bin/env python3
"""
Audio system smoke demo for the current YoYoPod stack.

This demo no longer relies on the removed `AudioScreen`. Instead it renders
audio state directly while exercising `AudioManager` and semantic input.
"""

import sys
import time
from datetime import datetime
from pathlib import Path

from loguru import logger

from yoyopod.audio.manager import AudioManager
from yoyopod_cli.pi.support.display import Display
from yoyopod_cli.pi.support.input import InputAction, get_input_manager

ACTION_MAP = {
    "a": InputAction.SELECT,
    "b": InputAction.BACK,
    "x": InputAction.UP,
    "y": InputAction.DOWN,
}

logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
)


def render_audio_status(
    display: Display,
    audio_manager: AudioManager,
    sound_name: str,
    status_message: str,
) -> None:
    """Render a compact audio status screen."""
    device_info = audio_manager.get_device_info()
    if audio_manager.is_playing:
        playback_state = "Playing"
        state_color = display.COLOR_GREEN
    elif audio_manager.is_paused:
        playback_state = "Paused"
        state_color = display.COLOR_YELLOW
    else:
        playback_state = "Stopped"
        state_color = display.COLOR_GRAY

    display.clear(display.COLOR_BLACK)
    display.status_bar(
        time_str=datetime.now().strftime("%H:%M"),
        battery_percent=85,
        signal_strength=3,
    )
    display.text("Audio Demo", 20, display.STATUS_BAR_HEIGHT + 18, color=display.COLOR_CYAN, font_size=20)
    display.text(f"File: {sound_name}", 20, 75, color=display.COLOR_WHITE, font_size=14)
    display.text(f"State: {playback_state}", 20, 105, color=state_color, font_size=16)
    display.text(
        f"Volume: {audio_manager.volume}% / {audio_manager.max_volume}%",
        20,
        135,
        color=display.COLOR_WHITE,
        font_size=14,
    )
    display.text(
        f"Device: {device_info.name if device_info else 'Unknown'}",
        20,
        165,
        color=display.COLOR_GRAY,
        font_size=12,
    )
    display.text(status_message[:28], 20, 195, color=display.COLOR_WHITE, font_size=12)
    display.text("A play/pause  X/Y volume  B exit", 20, display.HEIGHT - 18, color=display.COLOR_GRAY, font_size=10)
    display.update()


def main() -> int:
    """Run the audio demo."""
    logger.info("Starting YoYoPod audio demo")
    logger.info("=" * 50)

    display = Display(simulate="--simulate" in sys.argv)
    input_manager = get_input_manager(display.get_adapter(), simulate=display.simulate)
    if input_manager is None:
        logger.error("No input manager available for the detected display adapter")
        return 1

    audio_manager = AudioManager(max_volume=80, simulate=display.simulate)
    audio_manager.volume = 50

    sounds_dir = Path("assets/sounds")
    sound_files = sorted(sounds_dir.glob("*.wav")) if sounds_dir.exists() else []
    current_sound = sound_files[0] if sound_files else None

    if current_sound and audio_manager.load(current_sound):
        status_message = f"Loaded {current_sound.name}"
    elif current_sound:
        status_message = f"Failed to load {current_sound.name}"
    else:
        status_message = "No WAV files found in assets/sounds"

    running = True

    def refresh() -> None:
        render_audio_status(
            display,
            audio_manager,
            current_sound.name if current_sound else "None",
            status_message,
        )

    def on_select(_data=None) -> None:
        nonlocal status_message
        if not current_sound:
            status_message = "Add a WAV file to assets/sounds"
            refresh()
            return

        if audio_manager.is_playing:
            audio_manager.pause()
            status_message = f"Paused {current_sound.name}"
        elif audio_manager.is_paused:
            audio_manager.resume()
            status_message = f"Resumed {current_sound.name}"
        else:
            if audio_manager.current_file != current_sound:
                audio_manager.load(current_sound)
            if audio_manager.play():
                status_message = f"Playing {current_sound.name}"
            else:
                status_message = f"Playback failed for {current_sound.name}"
        refresh()

    def on_back(_data=None) -> None:
        nonlocal running, status_message
        running = False
        audio_manager.stop()
        status_message = "Exiting audio demo"
        refresh()

    def on_up(_data=None) -> None:
        nonlocal status_message
        audio_manager.volume_up()
        status_message = f"Volume increased to {audio_manager.volume}%"
        refresh()

    def on_down(_data=None) -> None:
        nonlocal status_message
        audio_manager.volume_down()
        status_message = f"Volume decreased to {audio_manager.volume}%"
        refresh()

    input_manager.on_action(InputAction.SELECT, on_select)
    input_manager.on_action(InputAction.BACK, on_back)
    input_manager.on_action(InputAction.UP, on_up)
    input_manager.on_action(InputAction.DOWN, on_down)
    input_manager.start()
    refresh()

    try:
        if display.simulate:
            logger.info("Simulation mode commands: a, b, x, y, quit")
            while running:
                try:
                    cmd = input("> ").strip().lower()
                except EOFError:
                    break

                if cmd in {"quit", "q", "exit"}:
                    break
                if cmd == "help":
                    logger.info("Commands: a, b, x, y, quit")
                    continue

                action = ACTION_MAP.get(cmd)
                if action is None:
                    logger.warning(f"Unknown command: {cmd}")
                    continue

                input_manager.simulate_action(action)
        else:
            logger.info("Audio demo running on hardware. Press Ctrl+C to exit.")
            while running:
                time.sleep(0.1)

    except KeyboardInterrupt:
        logger.info("Demo interrupted by user")
    finally:
        input_manager.stop()
        audio_manager.cleanup()
        display.cleanup()
        logger.info(f"Final volume: {audio_manager.volume}%")
        logger.info("Demo stopped")

    return 0


if __name__ == "__main__":
    sys.exit(main())
