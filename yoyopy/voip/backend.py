"""VoIP backend protocol and Linphone-backed implementation."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Callable, Optional, Protocol

from loguru import logger

from yoyopy.voip.types import (
    BackendStopped,
    CallState,
    CallStateChanged,
    IncomingCallDetected,
    RegistrationState,
    RegistrationStateChanged,
    VoIPConfig,
    VoIPEvent,
)


class VoIPBackend(Protocol):
    """Backend contract for SIP implementations used by VoIPManager."""

    def start(self) -> bool:
        """Start the backend process and begin emitting events."""

    def stop(self) -> None:
        """Stop the backend and release any resources."""

    def make_call(self, sip_address: str) -> bool:
        """Initiate an outgoing call."""

    def answer_call(self) -> bool:
        """Answer the current incoming call."""

    def reject_call(self) -> bool:
        """Reject the current incoming call."""

    def hangup(self) -> bool:
        """Terminate the current call."""

    def mute(self) -> bool:
        """Mute the current call microphone."""

    def unmute(self) -> bool:
        """Unmute the current call microphone."""

    def on_event(self, callback: Callable[[VoIPEvent], None]) -> None:
        """Register a typed backend-event listener."""


class LinphonecBackend:
    """Production VoIP backend that drives the linphonec subprocess."""

    def __init__(self, config: VoIPConfig) -> None:
        self.config = config
        self.process: Optional[subprocess.Popen] = None
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.event_callbacks: list[Callable[[VoIPEvent], None]] = []

    def on_event(self, callback: Callable[[VoIPEvent], None]) -> None:
        """Register a backend event callback."""

        self.event_callbacks.append(callback)

    def start(self) -> bool:
        """Start linphonec and begin monitoring its output."""

        if self.running:
            logger.warning("Linphone backend already running")
            return True

        try:
            if not self._generate_linphonerc():
                logger.warning(
                    "Failed to generate .linphonerc, attempting to use existing Linphone config"
                )

            self._configure_alsa_mixer()

            logger.info("Starting linphonec backend...")
            self.process = subprocess.Popen(
                [self.config.linphonec_path, "-d", "6"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self.running = True
            self.monitor_thread = threading.Thread(target=self._monitor_output, daemon=True)
            self.monitor_thread.start()

            time.sleep(2)
            self._send_command("status register")
            logger.info("Linphone backend started successfully")
            return True
        except Exception as exc:
            logger.error(f"Failed to start linphone backend: {exc}")
            self.running = False
            if self.process is not None:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=1)
                except Exception:
                    pass
                finally:
                    self.process = None
            return False

    def stop(self) -> None:
        """Stop the linphonec backend."""

        self.running = False

        if self.process is not None:
            try:
                self._send_command("quit")
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=1)
            except Exception as exc:
                logger.error(f"Error stopping linphone backend: {exc}")
            finally:
                self.process = None

        if self.monitor_thread is not None:
            self.monitor_thread.join(timeout=2)
            self.monitor_thread = None

    def make_call(self, sip_address: str) -> bool:
        """Initiate an outgoing call through linphonec."""

        return self._send_command(f"call {sip_address}")

    def answer_call(self) -> bool:
        """Answer the current call."""

        return self._send_command("answer")

    def reject_call(self) -> bool:
        """Reject the current incoming call."""

        return self._send_command("decline")

    def hangup(self) -> bool:
        """Terminate the current call."""

        return self._send_command("terminate")

    def mute(self) -> bool:
        """Mute the current call."""

        return self._send_command("mute")

    def unmute(self) -> bool:
        """Unmute the current call."""

        return self._send_command("unmute")

    def _emit(self, event: VoIPEvent) -> None:
        """Publish a typed event to registered backend listeners."""

        for callback in self.event_callbacks:
            try:
                callback(event)
            except Exception as exc:
                logger.error(f"Error in VoIP backend callback: {exc}")

    def _monitor_output(self) -> None:
        """Monitor linphonec output and emit typed backend events."""

        logger.debug("Linphone backend output monitor started")

        while self.running and self.process is not None:
            try:
                if self.process.stdout is None:
                    break

                line = self.process.stdout.readline()
                if not line:
                    if self.running and self.process.poll() is not None:
                        logger.warning("Linphone backend process terminated")
                        self.running = False
                        self._emit(BackendStopped(reason="process_terminated"))
                        break
                    continue

                line = line.strip()
                if not line:
                    continue

                for event in self._parse_output_line(line):
                    self._emit(event)
            except Exception as exc:
                logger.error(f"Error monitoring linphone output: {exc}")
                break

        logger.debug("Linphone backend output monitor stopped")

    def _parse_output_line(self, line: str) -> list[VoIPEvent]:
        """Parse one linphonec output line into typed events."""

        logger.debug(f"Linphone: {line}")
        events: list[VoIPEvent] = []

        registration_state = self._match_registration_state(line)
        if registration_state is not None:
            events.append(RegistrationStateChanged(state=registration_state))

        line_lower = line.lower()
        if "call" not in line_lower and "callsession" not in line_lower:
            return events

        caller_address = self._extract_caller_address(line)
        if "LinphoneCallIncoming" in line or "incoming" in line_lower:
            events.append(CallStateChanged(state=CallState.INCOMING))
            if caller_address:
                events.append(IncomingCallDetected(caller_address=caller_address))
        elif "outgoing" in line_lower:
            events.append(CallStateChanged(state=CallState.OUTGOING))
        elif (
            "connected" in line_lower
            or "streams running" in line_lower
            or "LinphoneCallConnected" in line
        ):
            events.append(CallStateChanged(state=CallState.CONNECTED))
        elif (
            "released" in line_lower
            or "ended" in line_lower
            or "LinphoneCallReleased" in line
        ):
            events.append(CallStateChanged(state=CallState.RELEASED))

        return events

    def _match_registration_state(self, line: str) -> Optional[RegistrationState]:
        """Match a linphone output line to a registration state."""

        if "Registration on" in line and "successful" in line:
            return RegistrationState.OK
        if "Registration on" in line and "failed" in line:
            return RegistrationState.FAILED
        if "Registration on" in line and "cleared" in line:
            return RegistrationState.CLEARED
        if "LinphoneRegistrationOk" in line or (
            "Registration successful" in line and "reason" in line
        ):
            return RegistrationState.OK
        if "LinphoneRegistrationProgress" in line:
            return RegistrationState.PROGRESS
        if "LinphoneRegistrationFailed" in line or (
            "Registration failed" in line and "reason" in line
        ):
            return RegistrationState.FAILED
        if "LinphoneRegistrationCleared" in line:
            return RegistrationState.CLEARED
        return None

    def _extract_caller_address(self, line: str) -> Optional[str]:
        """Extract a SIP caller address from a linphone output line."""

        if "[sip:" in line:
            start = line.find("[sip:")
            end = line.find("]", start)
            if start != -1 and end != -1:
                return line[start + 1:end]

        if "<sip:" in line:
            start = line.find("<sip:")
            end = line.find(">", start)
            if start != -1 and end != -1:
                return line[start + 1:end]

        line_lower = line.lower()
        if "from" not in line_lower or "sip:" not in line_lower:
            return None

        from_index = line_lower.find("from")
        if from_index == -1:
            return None

        after_from = line[from_index + len("from") :].strip()
        sip_index = after_from.lower().find("sip:")
        if sip_index == -1:
            return None

        candidate = after_from[sip_index:]
        end_pos = len(candidate)
        for marker in (" ", ",", "\t", "\n"):
            pos = candidate.find(marker)
            if pos != -1:
                end_pos = min(end_pos, pos)
        return candidate[:end_pos]

    def _configure_alsa_mixer(self) -> None:
        """Set ALSA mixer levels on the WM8960 sound card for VoIP audio."""

        card = "1"
        speaker_pct = min(100, max(0, self.config.speaker_volume))
        # Map 0-100 to 90-125 range
        speaker_raw = int(90 + speaker_pct * 0.35)
        capture_pct = min(100, max(0, self.config.mic_gain))
        # Map 0-100 to 16-35 range for capture volume (low to reduce speaker-mic echo)
        capture_raw = int(16 + capture_pct * 0.19)

        commands = [
            f"amixer -c {card} sset 'Speaker' {speaker_raw}",
            f"amixer -c {card} sset 'Playback' 255",
            f"amixer -c {card} sset 'Headphone' {speaker_raw}",
            f"amixer -c {card} sset 'Capture' {capture_raw}",
            f"amixer -c {card} sset 'ADC PCM' 195",
            f"amixer -c {card} sset 'Left Input Boost Mixer LINPUT1' 1",
            f"amixer -c {card} sset 'Right Input Boost Mixer RINPUT1' 1",
        ]

        for cmd in commands:
            try:
                subprocess.run(cmd, shell=True, capture_output=True, timeout=5)
            except Exception as exc:
                logger.warning(f"ALSA mixer command failed: {cmd}: {exc}")

        logger.info(
            f"ALSA mixer configured (speaker: {speaker_raw}/127, capture: {capture_raw}/63)"
        )

    def _generate_linphonerc(self) -> bool:
        """Generate the runtime linphonerc from the configured SIP settings."""

        if not self.config.sip_password_ha1 or not self.config.sip_identity:
            logger.warning("Cannot generate .linphonerc: missing HA1 hash or identity")
            return False

        try:
            linphonerc_path = os.path.expanduser("~/.linphonerc")
            config_content = f"""# Generated by YoyoPod LinphonecBackend
[sip]
sip_port=-1
sip_tcp_port=-1
sip_tls_port=-1
default_proxy=0
register_only_when_network_is_up=1
register_only_when_upnp_is_ok=0
guess_hostname=1
inc_timeout=30
in_call_timeout=0
delayed_timeout=4
use_info=0
use_rfc2833=1
use_ipv6=0
record_aware=0
media_encryption=srtp

[auth_info_0]
username={self.config.sip_username}
userid={self.config.sip_username}
ha1={self.config.sip_password_ha1}
realm={self.config.sip_server}
domain={self.config.sip_server}
algorithm=SHA-256
available_algorithms=SHA-256

[proxy_0]
reg_proxy=<sip:{self.config.sip_server};transport={self.config.transport}>
reg_identity={self.config.sip_identity}
reg_expires=3600
reg_sendregister=1
publish=0
dial_escape_plus=0
nat_policy_ref=ice_nat_policy

[nat_policy_0]
ref=ice_nat_policy
stun_server={self.config.stun_server if self.config.stun_server else 'stun.linphone.org'}
ice_enabled=1
turn_enabled=0
upnp_enabled=0

[rtp]
audio_rtp_port=7076-7100
video_rtp_port=9076-9100
audio_jitt_comp=60
video_jitt_comp=60
nortp_timeout=30
audio_adaptive_jitt_comp_enabled=1
video_adaptive_jitt_comp_enabled=1

[net]
download_bw=380
upload_bw=60
adaptive_rate_control=1
mtu=1300

[sound]
playback_dev_id={self.config.playback_dev_id}
ringer_dev_id={self.config.ringer_dev_id}
capture_dev_id={self.config.capture_dev_id}
media_dev_id={self.config.media_dev_id}
echocancellation=1
ec_tail_len=300
ec_delay=80
ec_framesize=128
echolimiter=1
el_type=mic
el_thres=0.01
el_force=25
el_sustain=50
el_transmit_thres=4
mic_gain_db={self.config.mic_gain * 0.3:.1f}
playback_gain_db={self.config.speaker_volume * 0.12 - 6:.1f}
ng_thres=0.05
ng_floorgain=0.001
"""

            with open(linphonerc_path, "w", encoding="utf-8") as handle:
                handle.write(config_content)

            logger.info(f"Generated .linphonerc at {linphonerc_path}")
            return True
        except Exception as exc:
            logger.error(f"Failed to generate .linphonerc: {exc}")
            return False

    def _send_command(self, command: str) -> bool:
        """Send a raw command to the linphonec process."""

        if self.process is None or self.process.stdin is None:
            logger.error("Cannot send command: linphone backend not running")
            return False

        try:
            self.process.stdin.write(f"{command}\n")
            self.process.stdin.flush()
            logger.debug(f"Sent command: {command}")
            return True
        except Exception as exc:
            logger.error(f"Failed to send command '{command}': {exc}")
            return False


class MockVoIPBackend:
    """Simple in-memory backend used for fast unit tests."""

    def __init__(self, start_result: bool = True) -> None:
        self.start_result = start_result
        self.running = False
        self.commands: list[str] = []
        self.event_callbacks: list[Callable[[VoIPEvent], None]] = []
        self.make_call_result = True
        self.answer_result = True
        self.reject_result = True
        self.hangup_result = True
        self.mute_result = True
        self.unmute_result = True

    def on_event(self, callback: Callable[[VoIPEvent], None]) -> None:
        """Register a backend event callback."""

        self.event_callbacks.append(callback)

    def emit(self, event: VoIPEvent) -> None:
        """Emit a synthetic backend event to registered listeners."""

        for callback in self.event_callbacks:
            callback(event)

    def start(self) -> bool:
        """Mark the backend as started."""

        self.running = self.start_result
        return self.start_result

    def stop(self) -> None:
        """Mark the backend as stopped."""

        self.running = False

    def make_call(self, sip_address: str) -> bool:
        """Record an outgoing call command."""

        self.commands.append(f"call {sip_address}")
        return self.make_call_result

    def answer_call(self) -> bool:
        """Record an answer command."""

        self.commands.append("answer")
        return self.answer_result

    def reject_call(self) -> bool:
        """Record a reject command."""

        self.commands.append("decline")
        return self.reject_result

    def hangup(self) -> bool:
        """Record a hangup command."""

        self.commands.append("terminate")
        return self.hangup_result

    def mute(self) -> bool:
        """Record a mute command."""

        self.commands.append("mute")
        return self.mute_result

    def unmute(self) -> bool:
        """Record an unmute command."""

        self.commands.append("unmute")
        return self.unmute_result
