"""Cloud manager for device auth, remote config, cache, and operator status."""

from __future__ import annotations

import json
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import unquote, urlparse

from loguru import logger

from yoyopod.backends.cloud import CloudClientError, CloudDeviceClient, DeviceMqttClient
from yoyopod.integrations.cloud.models import CloudAccessToken, CloudStatusSnapshot

if TYPE_CHECKING:
    from yoyopod.core.application import YoyoPodApp
    from yoyopod.config import ConfigManager


class CloudManager:
    """Own device provisioning, auth refresh, config sync, and MQTT telemetry."""

    _NETWORK_RETRY_DELAYS_SECONDS = (30.0, 60.0, 120.0, 300.0)
    _INVALID_CREDENTIALS_CODES = {"invalid_credentials", "invalid_device"}
    _TOKEN_RETRY_CODES = {"unauthorized", "token_revoked"}
    _DEFAULT_TICK_INTERVAL_SECONDS = 1.0

    def __init__(
        self,
        *,
        app: "YoyoPodApp",
        config_manager: "ConfigManager",
        client: CloudDeviceClient | None = None,
    ) -> None:
        self.app = app
        self.config_manager = config_manager
        backend = config_manager.get_cloud_settings().backend
        self._custom_client = client is not None
        self.client = client or CloudDeviceClient(
            base_url=backend.api_base_url,
            auth_path=backend.auth_path,
            refresh_path=backend.refresh_path,
            config_path_template=backend.config_path_template,
            contacts_bootstrap_path_template=backend.contacts_bootstrap_path_template,
            timeout_seconds=backend.timeout_seconds,
        )
        self.status = CloudStatusSnapshot()
        self._access_token: CloudAccessToken | None = None
        self._next_auth_attempt_at = 0.0
        self._next_refresh_at = 0.0
        self._next_config_poll_at = 0.0
        self._next_tick_at = 0.0
        self._tick_interval_seconds = self._DEFAULT_TICK_INTERVAL_SECONDS
        self._network_retry_index = 0
        self._secrets_fingerprint: tuple[bool, int, int] | None = None
        self._last_persisted_status_payload: dict[str, Any] | None = None
        self._request_in_flight = False
        self._provisioning_generation = 0
        self._mqtt: DeviceMqttClient | None = None
        self._next_battery_report_at = 0.0
        self._contacts_bootstrap_attempted = False
        self._playback_callbacks_bound = False
        self._remote_playback_session: dict[str, Any] | None = None
        self._remote_playback_activation_generation = 0
        self._recent_remote_command_ids: deque[str] = deque(maxlen=32)
        self._last_remote_playback_state: str | None = None

    def prepare_boot(self) -> None:
        """Load secrets/cache and start MQTT before the runtime loop begins."""

        self._bind_playback_callbacks()
        self._reload_provisioning(force=True, now=time.monotonic())
        self._next_tick_at = 0.0

    def tick(self, now: float | None = None) -> None:
        """Advance auth/config sync on the coordinator loop."""

        monotonic_now = time.monotonic() if now is None else now
        if monotonic_now < self._next_tick_at:
            return
        self._next_tick_at = monotonic_now + max(0.1, self._tick_interval_seconds)
        self._reload_provisioning(force=False, now=monotonic_now)

        if not self._is_backend_configured():
            self.status.cloud_state = "offline"
            self.status.backend_reachable = None
            self._persist_status()
            self._sync_context_state()
            return

        if self.status.provisioning_state != "provisioned":
            self._persist_status()
            self._sync_context_state()
            return

        if self._request_in_flight:
            return

        if self._access_token is None:
            if monotonic_now >= self._next_auth_attempt_at:
                self._start_authentication(monotonic_now)
            return

        if monotonic_now >= self._next_refresh_at:
            self._start_refresh_token(monotonic_now)
            return

        if monotonic_now >= self._next_config_poll_at:
            self._start_fetch_remote_config(monotonic_now)

    def note_network_change(self, *, connected: bool) -> None:
        """Wake auth/config work when connectivity changes."""

        if not connected:
            self.status.cloud_state = "offline"
            self.status.backend_reachable = False
            self._sync_context_state()
            self._persist_status()
            return

        if self.status.provisioning_state != "provisioned":
            return

        now = time.monotonic()
        if self._access_token is None:
            self._next_auth_attempt_at = now
        else:
            self._next_config_poll_at = now
        self._next_tick_at = 0.0
        self._persist_status()

    def request_immediate_poll(self) -> None:
        """Reset the config-poll timer so the next tick polls immediately."""

        self._next_config_poll_at = 0.0
        self._next_tick_at = 0.0

    def publish_battery(self, *, level: int, charging: bool, now: float) -> None:
        """Send a battery telemetry event via MQTT if the interval has elapsed."""

        if self._mqtt is None or not self._mqtt.is_connected:
            return
        if now < self._next_battery_report_at:
            return
        interval = self.config_manager.get_cloud_settings().backend.battery_report_interval_seconds
        if self._mqtt.publish_battery(level=level, charging=charging):
            self._next_battery_report_at = now + max(1, interval)

    def publish_heartbeat(self, *, firmware_version: str | None = None) -> None:
        """Send a heartbeat event via MQTT."""

        if self._mqtt is not None and self._mqtt.is_connected:
            self._mqtt.publish_heartbeat(firmware_version=firmware_version)

    def sync_context_state(self) -> None:
        """Push the latest cloud/max-volume state into AppContext when available."""

        self._sync_context_state()

    def export_status(self) -> dict[str, Any]:
        """Return the current redacted cloud status as a dict."""

        return self.status.to_dict()

    def stop(self) -> None:
        """Persist the latest status and stop MQTT on shutdown."""

        self._persist_status()
        if self._mqtt is not None:
            self._mqtt.stop()

    def _queue_main_thread_callback(
        self,
        callback: Callable[[], None],
        *,
        safety: bool = False,
    ) -> None:
        """Schedule coordinator-thread work through runtime loop dispatch."""

        runtime_loop = getattr(self.app, "runtime_loop", None)
        queue_callback = getattr(runtime_loop, "queue_main_thread_callback", None)
        if callable(queue_callback):
            queue_callback(callback, safety=safety)
            return

        legacy_callback = getattr(self.app, "_queue_main_thread_callback", None)
        if callable(legacy_callback):
            try:
                legacy_callback(callback, safety=safety)
            except TypeError:
                legacy_callback(callback)
            return

        callback()

    def _get_output_volume(self, *, refresh_system: bool) -> int | None:
        """Read the current shared output volume."""

        volume_controller = getattr(self.app, "audio_volume_controller", None)
        if volume_controller is not None:
            return volume_controller.get_output_volume(refresh_system=refresh_system)

        legacy_getter = getattr(self.app, "get_output_volume", None)
        if callable(legacy_getter):
            return legacy_getter(refresh_system=refresh_system)

        context = getattr(self.app, "context", None)
        playback = getattr(context, "playback", None)
        volume = getattr(playback, "volume", None)
        return int(volume) if isinstance(volume, int) else None

    def _set_output_volume(self, volume: int) -> bool:
        """Update the shared output volume."""

        volume_controller = getattr(self.app, "audio_volume_controller", None)
        if volume_controller is not None:
            return volume_controller.set_output_volume(volume)

        legacy_setter = getattr(self.app, "set_output_volume", None)
        if callable(legacy_setter):
            return bool(legacy_setter(volume))

        context = getattr(self.app, "context", None)
        if context is not None and hasattr(context, "set_volume"):
            context.set_volume(volume)
            return True
        return False

    def _reload_provisioning(self, *, force: bool, now: float) -> None:
        """Reload runtime secrets when the provisioning file changes."""

        fingerprint = self._current_secrets_fingerprint()
        if not force and fingerprint == self._secrets_fingerprint:
            return

        previous_device_id = self.status.device_id
        self._secrets_fingerprint = fingerprint
        self._provisioning_generation += 1
        self.config_manager.load_cloud_config()
        if not self._custom_client:
            backend = self.config_manager.get_cloud_settings().backend
            self.client = CloudDeviceClient(
                base_url=backend.api_base_url,
                auth_path=backend.auth_path,
                refresh_path=backend.refresh_path,
                config_path_template=backend.config_path_template,
                contacts_bootstrap_path_template=backend.contacts_bootstrap_path_template,
                timeout_seconds=backend.timeout_seconds,
            )

        device_id = self.config_manager.get_cloud_device_id().strip()
        device_secret = self.config_manager.get_cloud_device_secret().strip()
        self.status.device_id = device_id
        self.status.backend_reachable = None
        self.status.last_error_summary = ""
        self.status.updated_at = self._utc_now()
        self._access_token = None
        self._next_refresh_at = 0.0
        self._next_config_poll_at = 0.0
        self._network_retry_index = 0
        self._contacts_bootstrap_attempted = False
        if self._mqtt is not None:
            self._mqtt.stop()
            self._mqtt = None

        if self.config_manager.cloud_secrets_error:
            self.status.provisioning_state = "invalid_provisioning"
            self.status.cloud_state = "degraded"
            self.status.config_source = "none"
            self.status.last_error_summary = self.config_manager.cloud_secrets_error
            self.status.unapplied_keys = []
            self.status.config_version = 0
            self._sync_context_state()
            self._persist_status()
            return

        if not device_id and not device_secret:
            self.status.provisioning_state = "unprovisioned"
            self.status.cloud_state = "offline"
            self.status.config_source = "none"
            self.status.unapplied_keys = []
            self.status.config_version = 0
            self._sync_context_state()
            self._persist_status()
            return

        if not device_id or not device_secret:
            self.status.provisioning_state = "invalid_provisioning"
            self.status.cloud_state = "degraded"
            self.status.config_source = "none"
            self.status.last_error_summary = (
                "Provisioning file must contain device_id and device_secret"
            )
            self.status.unapplied_keys = []
            self.status.config_version = 0
            self._sync_context_state()
            self._persist_status()
            return

        self.status.provisioning_state = "provisioned"
        self.status.cloud_state = "offline"
        self._start_mqtt()
        if device_id != previous_device_id:
            self.status.config_source = "none"
            self.status.unapplied_keys = []
            self.status.config_version = 0
            self.status.last_successful_sync = None

        self._load_cached_config()
        self._next_auth_attempt_at = now
        self._sync_context_state()
        self._persist_status()

    def _start_authentication(self, now: float) -> None:
        self.status.cloud_state = "authenticating"
        self.status.updated_at = self._utc_now()
        self._sync_context_state()
        self._persist_status()

        self._request_in_flight = True
        self._start_worker(
            name="cloud-auth",
            work=lambda: self._run_authentication(
                device_id=self.config_manager.get_cloud_device_id().strip(),
                device_secret=self.config_manager.get_cloud_device_secret().strip(),
                generation=self._provisioning_generation,
            ),
        )

    def _start_refresh_token(self, now: float) -> None:
        if self._access_token is None:
            self._next_auth_attempt_at = now
            return

        access_token = self._access_token.access_token
        self._request_in_flight = True
        self._start_worker(
            name="cloud-refresh",
            work=lambda: self._run_refresh_token(
                access_token=access_token,
                generation=self._provisioning_generation,
            ),
        )

    def _start_fetch_remote_config(self, now: float) -> None:
        if self._access_token is None:
            self._next_auth_attempt_at = now
            return

        access_token = self._access_token.access_token
        device_id = self.config_manager.get_cloud_device_id().strip()
        self._request_in_flight = True
        self._start_worker(
            name="cloud-config-fetch",
            work=lambda: self._run_fetch_remote_config(
                access_token=access_token,
                device_id=device_id,
                generation=self._provisioning_generation,
            ),
        )

    def _run_authentication(self, *, device_id: str, device_secret: str, generation: int) -> None:
        try:
            token = self.client.authenticate(device_id=device_id, device_secret=device_secret)
        except CloudClientError as exc:
            self._queue_main_thread_callback(
                lambda exc=exc, generation=generation, device_id=device_id, completed_at=time.monotonic(): self._complete_authentication(
                    device_id=device_id,
                    generation=generation,
                    completed_at=completed_at,
                    error=exc,
                )
            )
            return
        except Exception as exc:
            error = CloudClientError(str(exc))
            self._queue_main_thread_callback(
                lambda error=error, generation=generation, device_id=device_id, completed_at=time.monotonic(): self._complete_authentication(
                    device_id=device_id,
                    generation=generation,
                    completed_at=completed_at,
                    error=error,
                )
            )
            return

        self._queue_main_thread_callback(
            lambda token=token, generation=generation, device_id=device_id, completed_at=time.monotonic(): self._complete_authentication(
                device_id=device_id,
                generation=generation,
                completed_at=completed_at,
                token=token,
            )
        )

    def _complete_authentication(
        self,
        *,
        device_id: str,
        generation: int,
        completed_at: float,
        token: CloudAccessToken | None = None,
        error: CloudClientError | None = None,
    ) -> None:
        self._request_in_flight = False
        if not self._matches_current_provisioning(device_id=device_id, generation=generation):
            return

        if error is not None:
            self._handle_auth_error(error, now=completed_at)
            return

        assert token is not None
        self._access_token = token
        self.status.backend_reachable = True
        self.status.cloud_state = (
            "ready" if self.status.config_source != "none" else "authenticating"
        )
        self._schedule_refresh(token, now=completed_at)
        self._next_config_poll_at = completed_at
        self._network_retry_index = 0
        self.status.last_error_summary = ""
        self._persist_status()
        self._sync_context_state()

    def _run_refresh_token(self, *, access_token: str, generation: int) -> None:
        try:
            token = self.client.refresh(access_token=access_token)
        except CloudClientError as exc:
            self._queue_main_thread_callback(
                lambda exc=exc, generation=generation, access_token=access_token, completed_at=time.monotonic(): self._complete_refresh_token(
                    access_token=access_token,
                    generation=generation,
                    completed_at=completed_at,
                    error=exc,
                )
            )
            return
        except Exception as exc:
            error = CloudClientError(str(exc))
            self._queue_main_thread_callback(
                lambda error=error, generation=generation, access_token=access_token, completed_at=time.monotonic(): self._complete_refresh_token(
                    access_token=access_token,
                    generation=generation,
                    completed_at=completed_at,
                    error=error,
                )
            )
            return

        self._queue_main_thread_callback(
            lambda token=token, generation=generation, access_token=access_token, completed_at=time.monotonic(): self._complete_refresh_token(
                access_token=access_token,
                generation=generation,
                completed_at=completed_at,
                token=token,
            )
        )

    def _complete_refresh_token(
        self,
        *,
        access_token: str,
        generation: int,
        completed_at: float,
        token: CloudAccessToken | None = None,
        error: CloudClientError | None = None,
    ) -> None:
        self._request_in_flight = False
        if not self._matches_current_request(access_token=access_token, generation=generation):
            return

        if error is not None:
            if error.error_code in self._TOKEN_RETRY_CODES or (
                error.status_code == 401 and not error.error_code
            ):
                self._access_token = None
                self._next_auth_attempt_at = completed_at
                self.status.cloud_state = "authenticating"
                self.status.last_error_summary = ""
                self._persist_status()
                self._sync_context_state()
                return
            self._handle_network_or_backend_error(error, now=completed_at)
            return

        assert token is not None
        self._access_token = token
        self.status.backend_reachable = True
        self.status.cloud_state = "ready"
        self.status.last_error_summary = ""
        self._schedule_refresh(token, now=completed_at)
        self._persist_status()
        self._sync_context_state()

    def _run_fetch_remote_config(
        self, *, access_token: str, device_id: str, generation: int
    ) -> None:
        try:
            payload = self.client.fetch_config(access_token=access_token, device_id=device_id)
        except CloudClientError as exc:
            self._queue_main_thread_callback(
                lambda exc=exc, generation=generation, access_token=access_token, device_id=device_id, completed_at=time.monotonic(): self._complete_fetch_remote_config(
                    access_token=access_token,
                    device_id=device_id,
                    generation=generation,
                    completed_at=completed_at,
                    error=exc,
                )
            )
            return
        except Exception as exc:
            error = CloudClientError(str(exc))
            self._queue_main_thread_callback(
                lambda error=error, generation=generation, access_token=access_token, device_id=device_id, completed_at=time.monotonic(): self._complete_fetch_remote_config(
                    access_token=access_token,
                    device_id=device_id,
                    generation=generation,
                    completed_at=completed_at,
                    error=error,
                )
            )
            return

        self._queue_main_thread_callback(
            lambda payload=payload, generation=generation, access_token=access_token, device_id=device_id, completed_at=time.monotonic(): self._complete_fetch_remote_config(
                access_token=access_token,
                device_id=device_id,
                generation=generation,
                completed_at=completed_at,
                payload=payload,
            )
        )

    def _complete_fetch_remote_config(
        self,
        *,
        access_token: str,
        device_id: str,
        generation: int,
        completed_at: float,
        payload: dict[str, Any] | None = None,
        error: CloudClientError | None = None,
    ) -> None:
        self._request_in_flight = False
        if not self._matches_current_request(
            access_token=access_token,
            generation=generation,
            device_id=device_id,
        ):
            return

        if error is not None:
            if error.error_code in self._TOKEN_RETRY_CODES or (
                error.status_code == 401 and not error.error_code
            ):
                self._access_token = None
                self._next_auth_attempt_at = completed_at
                self.status.cloud_state = "authenticating"
                self.status.last_error_summary = ""
                self._persist_status()
                self._sync_context_state()
                return
            self._handle_network_or_backend_error(error, now=completed_at)
            return

        assert payload is not None
        config_version = int(payload.get("config_version") or 0)
        self._apply_cloud_contacts(payload)
        runtime_payload = {key: value for key, value in payload.items() if key != "contacts"}
        unapplied_keys = self.config_manager.apply_cloud_overrides(runtime_payload)
        self._apply_runtime_side_effects(payload)
        self.status.backend_reachable = True
        self.status.cloud_state = "ready"
        self.status.config_source = "live"
        self.status.config_version = config_version
        self.status.last_successful_sync = self._utc_now()
        self.status.last_error_summary = ""
        self.status.unapplied_keys = unapplied_keys
        self._next_config_poll_at = completed_at + max(
            1,
            self.config_manager.get_cloud_settings().backend.config_poll_interval_seconds,
        )
        self._network_retry_index = 0
        self._write_cache(
            payload=payload,
            config_version=config_version,
            source="live",
            unapplied_keys=unapplied_keys,
        )
        self._persist_status()
        self._sync_context_state()
        from yoyopod import __version__

        self.publish_heartbeat(firmware_version=__version__)
        self._maybe_bootstrap_local_contacts(payload=payload, completed_at=completed_at)

    def _start_worker(self, *, name: str, work: Callable[[], None]) -> None:
        """Run one cloud control-plane worker on the shared `io` pool.

        Used for short, latency-sensitive cloud work (auth, token refresh,
        config sync, contacts bootstrap, MQTT). Long-running media downloads
        must use :meth:`_start_media_worker` so they cannot starve this pool.
        """

        del name  # Background pool uses its own thread names; the label aids only diagnostics.
        self.app.background.io.submit(work)

    def _start_media_worker(self, *, name: str, work: Callable[[], None]) -> None:
        """Run one cloud media/download worker on the dedicated `media` pool.

        Long-running media downloads (``store_media``, remote playback asset
        fetch) must not starve control-plane work on the shared `io` pool.
        Control-plane callers set ``_request_in_flight=True`` before queuing,
        so a queued (not yet running) auth/refresh/config task suppresses
        subsequent cloud ticks until a worker frees up — that pathway is
        broken if media downloads occupy all `io` workers.
        """

        del name  # Background pool uses its own thread names; the label aids only diagnostics.
        self.app.background.media.submit(work)

    def _matches_current_provisioning(self, *, device_id: str, generation: int) -> bool:
        return (
            generation == self._provisioning_generation
            and device_id == self.config_manager.get_cloud_device_id().strip()
            and self.status.provisioning_state == "provisioned"
        )

    def _matches_current_request(
        self,
        *,
        access_token: str,
        generation: int,
        device_id: str | None = None,
    ) -> bool:
        if not self._matches_current_provisioning(
            device_id=device_id or self.config_manager.get_cloud_device_id().strip(),
            generation=generation,
        ):
            return False
        return self._access_token is not None and self._access_token.access_token == access_token

    def _handle_auth_error(self, exc: CloudClientError, *, now: float) -> None:
        if exc.error_code == "device_unclaimed":
            self.status.backend_reachable = True
            self.status.cloud_state = "unclaimed"
            self.status.last_error_summary = "Device has not been claimed yet"
            self._next_auth_attempt_at = now + max(
                1,
                self.config_manager.get_cloud_settings().backend.claim_retry_seconds,
            )
        elif exc.error_code in self._INVALID_CREDENTIALS_CODES:
            self.status.backend_reachable = True
            self.status.cloud_state = "degraded"
            self.status.last_error_summary = "Invalid device credentials"
            self._next_auth_attempt_at = float("inf")
        else:
            self._handle_network_or_backend_error(exc, now=now)
            return

        self._persist_status()
        self._sync_context_state()

    def _handle_network_or_backend_error(self, exc: CloudClientError, *, now: float) -> None:
        status_code = exc.status_code or 0
        reachable = exc.status_code is not None
        self.status.backend_reachable = True if status_code >= 400 else False
        self.status.cloud_state = "offline" if not reachable or status_code >= 500 else "degraded"
        self.status.last_error_summary = str(exc)
        delay = self._NETWORK_RETRY_DELAYS_SECONDS[
            min(self._network_retry_index, len(self._NETWORK_RETRY_DELAYS_SECONDS) - 1)
        ]
        self._network_retry_index = min(
            self._network_retry_index + 1,
            len(self._NETWORK_RETRY_DELAYS_SECONDS) - 1,
        )
        if self._access_token is None:
            self._next_auth_attempt_at = now + delay
        else:
            self._next_refresh_at = now + delay
            self._next_config_poll_at = now + delay
        self._persist_status()
        self._sync_context_state()

    def _schedule_refresh(self, token: CloudAccessToken, *, now: float) -> None:
        threshold_seconds = min(token.lifetime_seconds * 0.2, 2 * 60 * 60)
        refresh_at_epoch = max(token.issued_at_epoch, token.expires_at_epoch - threshold_seconds)
        seconds_until_refresh = max(0.0, refresh_at_epoch - time.time())
        self._next_refresh_at = now + seconds_until_refresh

    def _apply_runtime_side_effects(self, payload: dict[str, Any]) -> None:
        audio = payload.get("audio", {})
        if not isinstance(audio, dict):
            audio = {}

        if self.app.context is not None:
            self.app.context.settings["max_volume"] = self.config_manager.get_max_output_volume()

        if "max_volume" in audio:
            max_volume = self.config_manager.get_max_output_volume()
            current = self._get_output_volume(refresh_system=False)
            if current is not None and current > max_volume:
                self._set_output_volume(max_volume)
            elif self.app.context is not None and self.app.context.voice.output_volume > max_volume:
                self.app.context.set_volume(max_volume)

        if "default_volume" in audio:
            max_volume = self.config_manager.get_max_output_volume()
            default_volume = min(self.config_manager.get_default_output_volume(), max_volume)
            self._set_output_volume(default_volume)

        if self.app.voip_manager is not None:
            self.app.voip_manager.config.voice_note_max_duration_seconds = (
                self.config_manager.get_voice_note_max_duration_seconds()
            )
            current_volume = self._get_output_volume(refresh_system=False)
            if current_volume is not None:
                self.app.voip_manager.config.output_volume = current_volume

        self._sync_context_state()

    def _apply_cloud_contacts(self, payload: dict[str, Any]) -> None:
        """Merge cloud-managed contacts into the mutable people directory."""

        contacts_payload = payload.get("contacts", {})
        if not isinstance(contacts_payload, dict):
            return

        entries = contacts_payload.get("entries", [])
        if not isinstance(entries, list):
            return

        if self.app.people_directory is None:
            logger.warning("Skipping cloud contacts sync because no people directory is loaded")
            return

        self.app.people_directory.merge_cloud_contacts(entries)

    def _local_contacts_bootstrap_entries(self) -> list[dict[str, Any]]:
        """Build one bootstrap payload from non-cloud local contacts."""

        if self.app.people_directory is None:
            return []

        local_contacts = self.app.people_directory.get_local_contacts()
        if not local_contacts:
            return []

        quick_dial_by_address = {
            str(address): int(slot)
            for slot, address in self.app.people_directory.speed_dial.items()
            if str(address).strip()
        }

        entries: list[dict[str, Any]] = []
        for contact in local_contacts:
            entries.append(
                {
                    "name": contact.name,
                    "phoneNumber": contact.phone_number.strip() or None,
                    "sipAddress": contact.sip_address.strip() or None,
                    "relationship": contact.notes.strip() or None,
                    "isPrimary": bool(contact.favorite),
                    "canCall": bool(contact.can_call),
                    "canReceive": bool(contact.can_receive),
                    "quickDial": quick_dial_by_address.get(contact.sip_address.strip()),
                }
            )
        return entries

    def _payload_has_backend_contacts(self, payload: dict[str, Any]) -> bool:
        contacts_payload = payload.get("contacts", {})
        if not isinstance(contacts_payload, dict):
            return False
        entries = contacts_payload.get("entries", [])
        return isinstance(entries, list) and len(entries) > 0

    def _maybe_bootstrap_local_contacts(
        self, *, payload: dict[str, Any], completed_at: float
    ) -> None:
        """Upload local seeded contacts once when the backend still has none."""

        if self._contacts_bootstrap_attempted:
            return
        if self._payload_has_backend_contacts(payload):
            return
        if self._access_token is None:
            return

        entries = self._local_contacts_bootstrap_entries()
        if not entries:
            self._contacts_bootstrap_attempted = True
            return

        self._contacts_bootstrap_attempted = True
        self._request_in_flight = True
        access_token = self._access_token.access_token
        device_id = self.config_manager.get_cloud_device_id().strip()
        generation = self._provisioning_generation
        self._start_worker(
            name="cloud-contacts-bootstrap",
            work=lambda: self._run_bootstrap_contacts(
                access_token=access_token,
                device_id=device_id,
                generation=generation,
                entries=entries,
            ),
        )

    def _run_bootstrap_contacts(
        self,
        *,
        access_token: str,
        device_id: str,
        generation: int,
        entries: list[dict[str, Any]],
    ) -> None:
        try:
            payload = self.client.bootstrap_contacts(
                access_token=access_token,
                device_id=device_id,
                entries=entries,
            )
        except CloudClientError as exc:
            self._queue_main_thread_callback(
                lambda exc=exc, generation=generation, access_token=access_token, device_id=device_id, completed_at=time.monotonic(): self._complete_bootstrap_contacts(
                    access_token=access_token,
                    device_id=device_id,
                    generation=generation,
                    completed_at=completed_at,
                    error=exc,
                )
            )
            return
        except Exception as exc:
            error = CloudClientError(str(exc))
            self._queue_main_thread_callback(
                lambda error=error, generation=generation, access_token=access_token, device_id=device_id, completed_at=time.monotonic(): self._complete_bootstrap_contacts(
                    access_token=access_token,
                    device_id=device_id,
                    generation=generation,
                    completed_at=completed_at,
                    error=error,
                )
            )
            return

        self._queue_main_thread_callback(
            lambda payload=payload, generation=generation, access_token=access_token, device_id=device_id, completed_at=time.monotonic(): self._complete_bootstrap_contacts(
                access_token=access_token,
                device_id=device_id,
                generation=generation,
                completed_at=completed_at,
                payload=payload,
            )
        )

    def _complete_bootstrap_contacts(
        self,
        *,
        access_token: str,
        device_id: str,
        generation: int,
        completed_at: float,
        payload: dict[str, Any] | None = None,
        error: CloudClientError | None = None,
    ) -> None:
        self._request_in_flight = False
        if not self._matches_current_request(
            access_token=access_token,
            generation=generation,
            device_id=device_id,
        ):
            return

        if error is not None:
            logger.warning("Cloud contact bootstrap failed for {}: {}", device_id, error)
            return

        imported_count = int((payload or {}).get("importedCount") or 0)
        skipped_count = int((payload or {}).get("skippedCount") or 0)
        logger.info(
            "Cloud contact bootstrap completed for {} (imported={}, skipped={})",
            device_id,
            imported_count,
            skipped_count,
        )
        if imported_count > 0:
            self._next_config_poll_at = completed_at

    def _load_cached_config(self) -> None:
        cache_path = self._cache_path()
        if not cache_path.exists():
            return

        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Failed to read cloud config cache {}: {}", cache_path, exc)
            return

        if not isinstance(payload, dict):
            logger.warning("Ignoring malformed cloud config cache {}", cache_path)
            return

        cached_device_id = str(payload.get("device_id") or "")
        current_device_id = self.config_manager.get_cloud_device_id().strip()
        if cached_device_id != current_device_id:
            logger.warning(
                "Ignoring cloud config cache for mismatched device id (cache={}, current={})",
                cached_device_id,
                current_device_id,
            )
            return

        raw_payload = payload.get("raw_payload", {})
        if not isinstance(raw_payload, dict):
            logger.warning("Ignoring malformed cloud config cache payload {}", cache_path)
            return

        self._apply_cloud_contacts(raw_payload)
        runtime_payload = {key: value for key, value in raw_payload.items() if key != "contacts"}
        unapplied_keys = self.config_manager.apply_cloud_overrides(runtime_payload)
        self._apply_runtime_side_effects(raw_payload)
        self.status.config_source = "cache"
        self.status.config_version = int(payload.get("config_version") or 0)
        self.status.unapplied_keys = unapplied_keys

    def _write_cache(
        self,
        *,
        payload: dict[str, Any],
        config_version: int,
        source: str,
        unapplied_keys: list[str],
    ) -> None:
        cache_path = self._cache_path()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_payload = {
            "device_id": self.config_manager.get_cloud_device_id().strip(),
            "config_version": config_version,
            "fetched_at": self._utc_now(),
            "source": source,
            "raw_payload": payload,
            "unapplied_keys": list(unapplied_keys),
        }
        try:
            cache_path.write_text(
                json.dumps(cache_payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Failed to persist cloud config cache {}: {}", cache_path, exc)

    def _persist_status(self) -> None:
        status_path = self._status_path()
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_payload = self.status.to_dict()
        status_payload["updated_at"] = None
        if status_payload == self._last_persisted_status_payload:
            return
        self.status.updated_at = self._utc_now()
        status_json = json.dumps(self.status.to_dict(), indent=2, sort_keys=True)
        try:
            status_path.write_text(status_json, encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to persist cloud status {}: {}", status_path, exc)
            return
        self._last_persisted_status_payload = status_payload

    def _sync_context_state(self) -> None:
        if self.app.context is None:
            return
        self.app.context.settings["max_volume"] = self.config_manager.get_max_output_volume()
        self.app.context.update_cloud_status(
            device_id=self.status.device_id,
            provisioning_state=self.status.provisioning_state,
            cloud_state=self.status.cloud_state,
            config_source=self.status.config_source,
            config_version=self.status.config_version,
            backend_reachable=self.status.backend_reachable,
            last_successful_sync=self.status.last_successful_sync,
            last_error_summary=self.status.last_error_summary,
            unapplied_keys=self.status.unapplied_keys,
        )

    def _start_mqtt(self) -> None:
        backend = self.config_manager.get_cloud_settings().backend
        if self._mqtt is not None:
            self._mqtt.stop()
            self._mqtt = None
        if not backend.mqtt_broker_host.strip():
            logger.info("MQTT broker host not configured — telemetry events disabled")
            return

        device_id = self.config_manager.get_cloud_device_id().strip()
        if not device_id:
            logger.info("Device not provisioned — MQTT telemetry deferred")
            return

        self._mqtt = DeviceMqttClient(
            broker_host=backend.mqtt_broker_host,
            device_id=device_id,
            port=backend.mqtt_broker_port,
            username=backend.mqtt_username or None,
            password=backend.mqtt_password or None,
            use_tls=backend.mqtt_use_tls,
            transport=backend.mqtt_transport,
            command_callback=self._handle_mqtt_command,
        )
        self._mqtt.start()
        logger.info(
            "MQTT client started -> {}:{} (device={})",
            backend.mqtt_broker_host,
            backend.mqtt_broker_port,
            device_id,
        )

    def _handle_mqtt_command(self, command: dict[str, Any]) -> None:
        cmd_type = command.get("command") or command.get("type", "unknown")
        logger.info("MQTT command received from backend: {}", cmd_type)
        self._queue_main_thread_callback(lambda cmd=command: self._apply_mqtt_command(cmd))

    def _apply_mqtt_command(self, command: dict[str, Any]) -> None:
        cmd_type = str(command.get("command") or command.get("type") or "").strip()
        if cmd_type == "fetch_config":
            self._next_config_poll_at = 0.0
            logger.info("MQTT: backend requested immediate config fetch")
        elif cmd_type in {"play_track", "stop", "pause", "resume"}:
            self._apply_playback_command(command)
        elif cmd_type == "store_media":
            self._apply_store_media_command(command)
        else:
            logger.info("MQTT: unhandled command type {}", cmd_type)

    def _bind_playback_callbacks(self) -> None:
        if self._playback_callbacks_bound:
            return

        music_backend = getattr(self.app, "music_backend", None)
        if music_backend is None:
            return

        track_change = getattr(music_backend, "on_track_change", None)
        if callable(track_change):
            track_change(self._handle_music_track_change)

        playback_change = getattr(music_backend, "on_playback_state_change", None)
        if callable(playback_change):
            playback_change(self._handle_music_playback_state_change)

        self._playback_callbacks_bound = True

    def _apply_playback_command(self, command: dict[str, Any]) -> None:
        mqtt = self._mqtt
        music_backend = getattr(self.app, "music_backend", None)
        command_id = str(command.get("commandId") or command.get("command_id") or "").strip()
        cmd_type = str(command.get("command") or command.get("type") or "").strip()
        payload = command.get("payload")
        payload = payload if isinstance(payload, dict) else {}

        if not command_id:
            return

        if mqtt is None or not mqtt.is_connected:
            return

        if command_id in self._recent_remote_command_ids:
            mqtt.publish_ack(command_id=command_id, ok=True, payload={"duplicate": True})
            return

        if music_backend is None or not getattr(music_backend, "is_connected", False):
            mqtt.publish_ack(
                command_id=command_id,
                ok=False,
                reason="playback_backend_error",
            )
            return

        if cmd_type == "play_track":
            media_url = str(payload.get("mediaUrl") or payload.get("media_url") or "").strip()
            track_id = str(payload.get("trackId") or payload.get("track_id") or "").strip()
            if not media_url or not track_id:
                mqtt.publish_ack(command_id=command_id, ok=False, reason="invalid_command")
                return

            stop_playback = getattr(music_backend, "stop_playback", None)
            if callable(stop_playback):
                stop_playback()

            self._remote_playback_activation_generation += 1
            self._remote_playback_session = {
                "command_id": command_id,
                "track_id": track_id,
                "title": payload.get("title"),
                "artist": payload.get("artist"),
                "duration_ms": payload.get("durationMs"),
                "media_url": media_url,
                "cached_path": None,
                "activation_generation": self._remote_playback_activation_generation,
                "activation_pending": True,
                "stop_requested": False,
            }
            self._recent_remote_command_ids.append(command_id)
            mqtt.publish_ack(command_id=command_id, ok=True, payload={"command": cmd_type})
            self._publish_playback_event(
                "buffering",
                command_id=command_id,
                payload={"trackId": track_id, "positionMs": 0},
            )

            self._last_remote_playback_state = "buffering"
            activation_generation = self._remote_playback_activation_generation
            checksum_sha256 = (
                str(payload.get("checksumSha256") or payload.get("checksum_sha256") or "").strip()
                or None
            )
            self._start_media_worker(
                name=f"cloud-playback-fetch-{command_id[:8]}",
                work=lambda: self._run_prepare_remote_playback_asset(
                    command_id=command_id,
                    track_id=track_id,
                    media_url=media_url,
                    checksum_sha256=checksum_sha256,
                    activation_generation=activation_generation,
                ),
            )
            return

        session = self._remote_playback_session
        if session is None:
            mqtt.publish_ack(command_id=command_id, ok=False, reason="invalid_command")
            return

        operation = {
            "stop": getattr(music_backend, "stop_playback", None),
            "pause": getattr(music_backend, "pause", None),
            "resume": getattr(music_backend, "play", None),
        }.get(cmd_type)

        if cmd_type == "stop":
            session["stop_requested"] = True

        if not callable(operation) or not operation():
            mqtt.publish_ack(command_id=command_id, ok=False, reason="playback_backend_error")
            self._publish_playback_event(
                "failed",
                command_id=session["command_id"],
                payload={
                    "trackId": session["track_id"],
                    "reason": "playback_backend_error",
                },
            )
            return

        self._recent_remote_command_ids.append(command_id)
        mqtt.publish_ack(command_id=command_id, ok=True, payload={"command": cmd_type})

    def _handle_music_track_change(self, track: Any) -> None:
        if self._remote_playback_session is None or track is None:
            return

        if self._remote_playback_session.get(
            "activation_pending"
        ) and not self._remote_playback_session.get("cached_path"):
            return

        current_uri = getattr(track, "uri", None)
        session_uri = self._remote_playback_session.get("cached_path")
        current_path = self._normalize_local_media_path(current_uri)
        session_path = self._normalize_local_media_path(session_uri)
        track_id = str(self._remote_playback_session.get("track_id") or "").strip()
        normalized_current_uri = str(current_uri or "")
        is_file_like_uri = (
            normalized_current_uri.startswith("file://")
            or "/" in normalized_current_uri
            or bool(Path(normalized_current_uri).suffix)
        )

        if current_path is not None and session_path is not None:
            if current_path == session_path or current_path.name == session_path.name:
                self._remote_playback_session["activation_pending"] = False
                return

        if track_id and track_id in normalized_current_uri:
            self._remote_playback_session["activation_pending"] = False
            return

        if not is_file_like_uri:
            return

        if current_uri and session_uri and current_uri != session_uri:
            self._remote_playback_session = None
            self._last_remote_playback_state = None

    @staticmethod
    def _normalize_local_media_path(value: Any) -> Path | None:
        if value in (None, ""):
            return None

        normalized = str(value).strip()
        if not normalized:
            return None

        if normalized.startswith("file://"):
            normalized = unquote(urlparse(normalized).path)

        try:
            return Path(normalized).expanduser().resolve(strict=False)
        except Exception:
            return Path(normalized)

    def _handle_music_playback_state_change(self, state: str) -> None:
        session = self._remote_playback_session
        if session is None:
            return

        if (
            state == "stopped"
            and session.get("activation_pending")
            and not session.get("cached_path")
        ):
            return

        position_ms = self._current_playback_position_ms()
        duration_ms = session.get("duration_ms")
        event_type = state

        if state == "playing" and session.get("playing_started_at_monotonic") is None:
            session["playing_started_at_monotonic"] = time.monotonic()
            session["activation_pending"] = False
        elif state in {"paused", "buffering"}:
            session["activation_pending"] = False

        if state == "stopped":
            started_at_monotonic = session.get("playing_started_at_monotonic")
            elapsed_ms = None
            if isinstance(started_at_monotonic, (int, float)):
                elapsed_ms = int(max(0.0, (time.monotonic() - started_at_monotonic) * 1000))

            if (
                not session.get("stop_requested")
                and isinstance(duration_ms, int)
                and duration_ms > 0
                and elapsed_ms is not None
                and elapsed_ms >= max(0, duration_ms - 2500)
            ):
                event_type = "completed"
            elif (
                isinstance(duration_ms, int)
                and duration_ms > 0
                and position_ms >= max(0, duration_ms - 2500)
            ):
                event_type = "completed"
            self._remote_playback_session = None
            self._last_remote_playback_state = None
        else:
            self._last_remote_playback_state = state

        self._publish_playback_event(
            event_type,
            command_id=session["command_id"],
            payload={
                "trackId": session["track_id"],
                "positionMs": position_ms,
            },
        )

    def _current_playback_position_ms(self) -> int:
        music_backend = getattr(self.app, "music_backend", None)
        if music_backend is None:
            return 0

        getter = getattr(music_backend, "get_time_position", None)
        if not callable(getter):
            return 0

        try:
            return int(getter())
        except Exception:
            return 0

    def _publish_playback_event(
        self,
        event_type: str,
        *,
        command_id: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if self._mqtt is None or not self._mqtt.is_connected:
            return

        event_payload: dict[str, Any] = {
            "messageType": "playback.event",
            "commandId": command_id,
            "deviceId": self.config_manager.get_cloud_device_id().strip(),
            "eventType": event_type,
            "occurredAt": self._utc_now(),
            "payload": payload or {},
        }
        self._mqtt.publish_playback_event(event_payload)

    def _publish_media_library_event(
        self,
        event_type: str,
        *,
        command_id: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if self._mqtt is None or not self._mqtt.is_connected:
            return

        event_payload: dict[str, Any] = {
            "messageType": "media_library.event",
            "commandId": command_id,
            "deviceId": self.config_manager.get_cloud_device_id().strip(),
            "eventType": event_type,
            "occurredAt": self._utc_now(),
            "payload": payload or {},
        }
        self._mqtt.publish_event("media_library", event_payload)

    def _run_prepare_remote_playback_asset(
        self,
        *,
        command_id: str,
        track_id: str,
        media_url: str,
        checksum_sha256: str | None,
        activation_generation: int,
    ) -> None:
        try:
            cached_asset = self._prepare_remote_playback_asset_for_media_backend(
                track_id=track_id,
                media_url=media_url,
                checksum_sha256=checksum_sha256,
            )
        except Exception as exc:
            logger.warning("Remote playback fetch failed for {}: {}", track_id, exc)
            self._queue_main_thread_callback(
                lambda exc=exc: self._complete_prepare_remote_playback_asset(
                    command_id=command_id,
                    track_id=track_id,
                    activation_generation=activation_generation,
                    error=exc,
                )
            )
            return

        self._queue_main_thread_callback(
            lambda cached_asset=cached_asset: self._complete_prepare_remote_playback_asset(
                command_id=command_id,
                track_id=track_id,
                activation_generation=activation_generation,
                cached_asset=cached_asset,
            )
        )

    def _complete_prepare_remote_playback_asset(
        self,
        *,
        command_id: str,
        track_id: str,
        activation_generation: int,
        cached_asset: Any | None = None,
        error: Exception | None = None,
    ) -> None:
        session = self._remote_playback_session
        if (
            session is None
            or session.get("command_id") != command_id
            or session.get("track_id") != track_id
            or session.get("activation_generation") != activation_generation
        ):
            return

        if error is not None:
            self._remote_playback_session = None
            self._last_remote_playback_state = None
            self._publish_playback_event(
                "failed",
                command_id=command_id,
                payload={
                    "trackId": track_id,
                    "reason": "media_fetch_failed",
                },
            )
            return

        music_backend = getattr(self.app, "music_backend", None)
        if music_backend is None or not getattr(music_backend, "is_connected", False):
            self._remote_playback_session = None
            self._last_remote_playback_state = None
            self._publish_playback_event(
                "failed",
                command_id=command_id,
                payload={
                    "trackId": track_id,
                    "reason": "playback_backend_error",
                },
            )
            return

        if session.get("stop_requested"):
            self._remote_playback_session = None
            self._last_remote_playback_state = None
            self._publish_playback_event(
                "stopped",
                command_id=command_id,
                payload={
                    "trackId": track_id,
                    "positionMs": 0,
                },
            )
            return

        session["cached_path"] = cached_asset.path
        if not music_backend.load_tracks([cached_asset.path]):
            self._remote_playback_session = None
            self._last_remote_playback_state = None
            self._publish_playback_event(
                "failed",
                command_id=command_id,
                payload={
                    "trackId": track_id,
                    "reason": "decode_failed",
                },
            )

    def _apply_store_media_command(self, command: dict[str, Any]) -> None:
        mqtt = self._mqtt
        command_id = str(command.get("commandId") or command.get("command_id") or "").strip()
        payload = command.get("payload")
        payload = payload if isinstance(payload, dict) else {}

        if not command_id or mqtt is None or not mqtt.is_connected:
            return

        if command_id in self._recent_remote_command_ids:
            mqtt.publish_ack(command_id=command_id, ok=True, payload={"duplicate": True})
            return

        media_url = str(payload.get("mediaUrl") or payload.get("media_url") or "").strip()
        track_id = str(payload.get("trackId") or payload.get("track_id") or "").strip()
        if not media_url or not track_id:
            mqtt.publish_ack(command_id=command_id, ok=False, reason="invalid_command")
            return

        self._recent_remote_command_ids.append(command_id)
        mqtt.publish_ack(command_id=command_id, ok=True, payload={"command": "store_media"})

        checksum_sha256 = (
            str(payload.get("checksumSha256") or payload.get("checksum_sha256") or "").strip()
            or None
        )
        self._start_media_worker(
            name=f"cloud-store-media-{command_id[:8]}",
            work=lambda: self._run_store_media_command(
                command_id=command_id,
                track_id=track_id,
                media_url=media_url,
                checksum_sha256=checksum_sha256,
                payload=payload,
            ),
        )

    def _run_store_media_command(
        self,
        *,
        command_id: str,
        track_id: str,
        media_url: str,
        checksum_sha256: str | None,
        payload: dict[str, Any],
    ) -> None:
        try:
            cached_asset = self._prepare_remote_playback_asset_for_media_backend(
                track_id=track_id,
                media_url=media_url,
                checksum_sha256=checksum_sha256,
            )
            target_path = self._import_remote_media_asset_for_media_backend(
                track_id=track_id,
                cached_path=str(cached_asset.path),
                payload=payload,
            )
        except Exception as exc:
            logger.warning("Device media import failed for {}: {}", track_id, exc)
            self._queue_main_thread_callback(
                lambda exc=exc: self._complete_store_media_command(
                    command_id=command_id,
                    track_id=track_id,
                    error=exc,
                )
            )
            return

        self._queue_main_thread_callback(
            lambda target_path=target_path: self._complete_store_media_command(
                command_id=command_id,
                track_id=track_id,
                target_path=target_path,
            )
        )

    def _prepare_remote_playback_asset_for_media_backend(
        self,
        *,
        track_id: str,
        media_url: str,
        checksum_sha256: str | None,
    ) -> Any:
        music_backend = getattr(self.app, "music_backend", None)
        prepare_remote_playback_asset = getattr(music_backend, "prepare_remote_playback_asset", None)
        if not callable(prepare_remote_playback_asset):
            raise RuntimeError("Rust media host remote playback is unavailable")
        return prepare_remote_playback_asset(
            track_id=track_id,
            media_url=media_url,
            checksum_sha256=checksum_sha256,
            extension=self._remote_media_extension(media_url),
        )

    def _import_remote_media_asset_for_media_backend(
        self,
        *,
        track_id: str,
        cached_path: str,
        payload: dict[str, Any],
    ) -> str:
        music_backend = getattr(self.app, "music_backend", None)
        import_remote_media_asset = getattr(music_backend, "import_remote_media_asset", None)
        if not callable(import_remote_media_asset):
            raise RuntimeError("Rust media host media import is unavailable")
        return import_remote_media_asset(
            track_id=track_id,
            cached_path=cached_path,
            title=str(payload.get("title") or "").strip() or None,
            filename=str(payload.get("filename") or payload.get("originalFilename") or "").strip()
            or None,
        )

    def _complete_store_media_command(
        self,
        *,
        command_id: str,
        track_id: str,
        target_path: Path | str | None = None,
        error: Exception | None = None,
    ) -> None:
        if error is not None or target_path is None:
            self._publish_media_library_event(
                "failed",
                command_id=command_id,
                payload={
                    "trackId": track_id,
                    "reason": "media_fetch_failed",
                },
            )
            return

        self._publish_media_library_event(
            "imported",
            command_id=command_id,
            payload={
                "trackId": track_id,
                "path": str(target_path),
            },
        )

    @staticmethod
    def _remote_media_extension(media_url: str) -> str:
        suffix = Path(urlparse(media_url).path).suffix
        return suffix or ".mp3"

    def _is_backend_configured(self) -> bool:
        return bool(self.config_manager.get_cloud_settings().backend.api_base_url.strip())

    def _current_secrets_fingerprint(self) -> tuple[bool, int, int]:
        path = self.config_manager.cloud_secrets_runtime_file
        if not path.exists():
            return (False, 0, 0)
        stat = path.stat()
        return (True, stat.st_mtime_ns, stat.st_size)

    def _cache_path(self) -> Path:
        return self.config_manager.resolve_runtime_path(self.config_manager.get_cloud_cache_file())

    def _status_path(self) -> Path:
        return self.config_manager.resolve_runtime_path(self.config_manager.get_cloud_status_file())

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()
