"""Domain-owned music manager for playback and output-device state."""

import subprocess
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, List, Optional

from loguru import logger


@lru_cache(maxsize=1)
def _load_pygame_mixer() -> object | None:
    """Import pygame.mixer only when a music-manager instance needs it."""

    try:
        return import_module("pygame.mixer")
    except ImportError:
        logger.warning("pygame not available - audio will be simulated")
        return None


class AudioDevice(Enum):
    """Audio output device types."""
    BUILT_IN = "built-in"
    USB = "usb"
    BLUETOOTH = "bluetooth"
    HDMI = "hdmi"


@dataclass
class AudioDeviceInfo:
    """Information about an audio device."""
    name: str
    device_type: AudioDevice
    card_number: int = 0
    device_number: int = 0
    is_available: bool = True


class MusicManager:
    """
    Manage music playback and volume state for local media.

    Uses pygame.mixer for audio playback with ALSA backend on Linux.
    Provides volume control with parental limiting.
    """

    # Audio settings
    SAMPLE_RATE = 44100
    CHANNELS = 2  # Stereo
    BUFFER_SIZE = 2048

    def __init__(
        self,
        max_volume: int = 80,  # Parental limit
        simulate: bool = False
    ) -> None:
        """
        Initialize the audio manager.

        Args:
            max_volume: Maximum volume limit (0-100), default 80% for parental control
            simulate: If True, run in simulation mode without actual audio
        """
        self._pygame_mixer: Any | None = None if simulate else _load_pygame_mixer()
        self.simulate = simulate or self._pygame_mixer is None
        self.max_volume = max(0, min(100, max_volume))
        self._volume = 50  # Current volume (0-100)
        self.is_playing = False
        self.is_paused = False
        self.current_file: Optional[Path] = None
        self.current_device: Optional[AudioDeviceInfo] = None

        # Volume change callbacks
        self.volume_callbacks: List[Callable[[int], None]] = []

        # Initialize pygame mixer
        if not self.simulate:
            try:
                self._mixer().init(
                    frequency=self.SAMPLE_RATE,
                    size=-16,  # 16-bit
                    channels=self.CHANNELS,
                    buffer=self.BUFFER_SIZE
                )
                logger.info(f"Audio system initialized (max volume: {self.max_volume}%)")
            except Exception as e:
                logger.error(f"Failed to initialize audio: {e}")
                logger.info("Falling back to simulation mode")
                self.simulate = True
        else:
            logger.info("Audio running in simulation mode")

        # Detect available audio devices
        self._detect_devices()

    def _mixer(self) -> Any:
        """Return the pygame mixer module when real audio is active."""

        if self._pygame_mixer is None:
            raise RuntimeError("pygame.mixer is unavailable while audio simulation is disabled")
        return self._pygame_mixer

    def _detect_devices(self) -> List[AudioDeviceInfo]:
        """
        Detect available audio devices.

        Returns:
            List of available audio devices
        """
        devices = []

        if self.simulate:
            # Simulated devices
            devices.append(AudioDeviceInfo(
                name="Built-in Audio",
                device_type=AudioDevice.BUILT_IN,
                is_available=True
            ))
        else:
            # Try to detect ALSA devices on Linux
            try:
                result = subprocess.run(
                    ['aplay', '-l'],
                    capture_output=True,
                    text=True,
                    timeout=2
                )

                if result.returncode == 0:
                    # Parse aplay output
                    for line in result.stdout.split('\n'):
                        if 'card' in line.lower():
                            # Simple parsing - just detect that devices exist
                            devices.append(AudioDeviceInfo(
                                name="Built-in Audio",
                                device_type=AudioDevice.BUILT_IN,
                                is_available=True
                            ))
                            break
            except (subprocess.TimeoutExpired, FileNotFoundError):
                logger.warning("Could not detect audio devices")
                # Assume built-in is available
                devices.append(AudioDeviceInfo(
                    name="Built-in Audio",
                    device_type=AudioDevice.BUILT_IN,
                    is_available=True
                ))

        if devices:
            self.current_device = devices[0]
            logger.info(f"Using audio device: {self.current_device.name}")

        return devices

    @property
    def volume(self) -> int:
        """Get current volume (0-100)."""
        return self._volume

    @volume.setter
    def volume(self, value: int) -> None:
        """
        Set volume with parental limit enforcement.

        Args:
            value: Volume level (0-100)
        """
        # Enforce parental limit
        value = max(0, min(value, self.max_volume))

        if value != self._volume:
            self._volume = value

            # Update pygame mixer volume (0.0 to 1.0)
            if not self.simulate:
                pygame_volume = value / 100.0
                self._mixer().music.set_volume(pygame_volume)

            logger.info(f"Volume set to {value}% (max: {self.max_volume}%)")

            # Fire callbacks
            for callback in self.volume_callbacks:
                try:
                    callback(value)
                except Exception as e:
                    logger.error(f"Error in volume callback: {e}")

    def volume_up(self, step: int = 5) -> int:
        """
        Increase volume.

        Args:
            step: Amount to increase (default 5%)

        Returns:
            New volume level
        """
        self.volume = self._volume + step
        return self._volume

    def volume_down(self, step: int = 5) -> int:
        """
        Decrease volume.

        Args:
            step: Amount to decrease (default 5%)

        Returns:
            New volume level
        """
        self.volume = self._volume - step
        return self._volume

    def on_volume_change(self, callback: Callable[[int], None]) -> None:
        """
        Register callback for volume changes.

        Args:
            callback: Function to call when volume changes (receives new volume)
        """
        self.volume_callbacks.append(callback)
        logger.debug("Registered volume change callback")

    def load(self, file_path: Path) -> bool:
        """
        Load an audio file.

        Args:
            file_path: Path to audio file (MP3, WAV, OGG)

        Returns:
            True if loaded successfully, False otherwise
        """
        if not file_path.exists():
            logger.error(f"Audio file not found: {file_path}")
            return False

        if self.simulate:
            logger.info(f"[SIMULATED] Loading audio: {file_path.name}")
            self.current_file = file_path
            return True

        try:
            self._mixer().music.load(str(file_path))
            self.current_file = file_path
            logger.info(f"Loaded audio: {file_path.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to load audio {file_path}: {e}")
            return False

    def play(self, loops: int = 0) -> bool:
        """
        Play the currently loaded audio.

        Args:
            loops: Number of times to loop (-1 for infinite, 0 for once)

        Returns:
            True if playback started, False otherwise
        """
        if not self.current_file:
            logger.warning("No audio file loaded")
            return False

        if self.simulate:
            logger.info(f"[SIMULATED] Playing: {self.current_file.name}")
            self.is_playing = True
            self.is_paused = False
            return True

        try:
            self._mixer().music.play(loops=loops)
            self.is_playing = True
            self.is_paused = False
            logger.info(f"Playing: {self.current_file.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to play audio: {e}")
            return False

    def pause(self) -> None:
        """Pause playback."""
        if not self.is_playing:
            logger.warning("Nothing is playing")
            return

        if self.simulate:
            logger.info("[SIMULATED] Paused playback")
            self.is_paused = True
            self.is_playing = False
            return

        try:
            self._mixer().music.pause()
            self.is_paused = True
            self.is_playing = False
            logger.info("Paused playback")
        except Exception as e:
            logger.error(f"Failed to pause: {e}")

    def resume(self) -> None:
        """Resume paused playback."""
        if not self.is_paused:
            logger.warning("Nothing is paused")
            return

        if self.simulate:
            logger.info("[SIMULATED] Resumed playback")
            self.is_paused = False
            self.is_playing = True
            return

        try:
            self._mixer().music.unpause()
            self.is_paused = False
            self.is_playing = True
            logger.info("Resumed playback")
        except Exception as e:
            logger.error(f"Failed to resume: {e}")

    def stop(self) -> None:
        """Stop playback."""
        if self.simulate:
            logger.info("[SIMULATED] Stopped playback")
            self.is_playing = False
            self.is_paused = False
            return

        try:
            self._mixer().music.stop()
            self.is_playing = False
            self.is_paused = False
            logger.info("Stopped playback")
        except Exception as e:
            logger.error(f"Failed to stop: {e}")

    def get_position(self) -> float:
        """
        Get current playback position in seconds.

        Returns:
            Current position in seconds (0.0 if not playing or simulated)
        """
        if self.simulate:
            return 0.0

        try:
            # pygame.mixer.music.get_pos() returns milliseconds
            pos_ms = self._mixer().music.get_pos()
            return pos_ms / 1000.0 if pos_ms >= 0 else 0.0
        except Exception as e:
            logger.error(f"Failed to get position: {e}")
            return 0.0

    def is_busy(self) -> bool:
        """
        Check if audio is currently playing.

        Returns:
            True if audio is playing, False otherwise
        """
        if self.simulate:
            return self.is_playing

        try:
            return self._mixer().music.get_busy()
        except Exception as e:
            logger.error(f"Failed to check if busy: {e}")
            return False

    def set_max_volume(self, max_volume: int) -> None:
        """
        Set the maximum volume (parental control).

        Args:
            max_volume: Maximum volume (0-100)
        """
        self.max_volume = max(0, min(100, max_volume))
        logger.info(f"Max volume set to {self.max_volume}%")

        # If current volume exceeds new max, reduce it
        if self._volume > self.max_volume:
            self.volume = self.max_volume

    def get_device_info(self) -> Optional[AudioDeviceInfo]:
        """Get information about the current audio device."""
        return self.current_device

    def cleanup(self) -> None:
        """Clean up audio resources."""
        if not self.simulate:
            try:
                mixer = self._mixer()
                mixer.music.stop()
                mixer.quit()
                logger.info("Audio system cleaned up")
            except Exception as e:
                logger.error(f"Error during audio cleanup: {e}")


# Backward compatibility: preserve historical public class name.
AudioManager = MusicManager
