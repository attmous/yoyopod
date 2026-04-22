"""Shared hardware metadata helpers that do not belong to one domain."""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
from functools import lru_cache
from pathlib import Path

from loguru import logger


def _normalize_alsa_selector(value: str) -> str:
    raw = value.strip()
    if raw.upper().startswith("ALSA:"):
        raw = raw.split(":", 1)[1].strip()
    return raw


def _run_list(binary: str) -> list[str]:
    if not shutil.which(binary):
        return []
    try:
        result = subprocess.run(
            [binary, "-L"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception as exc:
        logger.debug("ALSA list via {} failed: {}", binary, exc)
        return []
    if result.returncode != 0:
        return []
    devices: list[str] = []
    for line in result.stdout.splitlines():
        if not line or line.startswith(" "):
            continue
        device = line.strip()
        if not device or device == "null":
            continue
        devices.append(device)
    return devices


@lru_cache(maxsize=1)
def _asound_card_aliases() -> dict[str, str]:
    cards_path = Path("/proc/asound/cards")
    if not cards_path.exists():
        return {}

    try:
        text = cards_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}

    aliases: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*\d+\s+\[([^\]]+)\]:\s*(.+?)\s*$", line)
        if not match:
            continue
        card_id = match.group(1).strip()
        rest = match.group(2).strip()
        if not card_id or not rest:
            continue
        friendly = rest.split(" - ", 1)[1].strip() if " - " in rest else rest
        aliases[card_id] = friendly or rest
    return aliases


def _friendly_card_name(card_id: str) -> str:
    return _asound_card_aliases().get(card_id, card_id)


def _parse_card_dev(device: str) -> tuple[str | None, int | None]:
    upper = device.upper()
    card = None
    dev = None
    if "CARD=" in upper:
        start = upper.index("CARD=") + len("CARD=")
        end = device.find(",", start)
        card = (device[start:] if end == -1 else device[start:end]).strip() or None
    if "DEV=" in upper:
        start = upper.index("DEV=") + len("DEV=")
        end = device.find(",", start)
        raw = (device[start:] if end == -1 else device[start:end]).strip()
        try:
            dev = int(raw)
        except Exception:
            dev = None
    return card, dev


def _route_name(device: str) -> str:
    return device.split(":", 1)[0].strip().lower() if ":" in device else device.strip().lower()


def list_playback_devices(*, aplay_binary: str = "aplay") -> list[str]:
    parsed = _run_list(aplay_binary)
    candidates: list[str] = []
    for device in parsed:
        if device in {"default", "sysdefault", "null"}:
            continue
        route = _route_name(device)
        if route not in {"plughw", "hw", "hdmi"}:
            continue
        card, _ = _parse_card_dev(device)
        if card:
            candidates.append(device)

    by_card: dict[str, list[str]] = {}
    for device in candidates:
        card, _ = _parse_card_dev(device)
        if card:
            by_card.setdefault(card, []).append(device)

    chosen: list[str] = []
    for card, devices in by_card.items():
        priority = ["hdmi", "plughw", "hw"] if card.lower() == "vc4hdmi" else ["plughw", "hw"]
        best: str | None = None
        for route in priority:
            matches = [device for device in devices if _route_name(device) == route]
            if matches:
                matches.sort(key=lambda device: (_parse_card_dev(device)[1] or 0, device))
                best = matches[0]
                break
        if best is not None:
            chosen.append(best)

    def sort_key(value: str) -> tuple[int, str]:
        card, _ = _parse_card_dev(value)
        route = _route_name(value)
        friendly = _friendly_card_name(card or "").lower()
        if route == "hdmi" or (card or "").lower() == "vc4hdmi":
            return (2, friendly)
        if "usb" in friendly or "jabra" in friendly:
            return (0, friendly)
        if "blue" in friendly:
            return (1, friendly)
        return (3, friendly)

    return sorted(dict.fromkeys(chosen), key=sort_key)


def list_capture_devices(*, arecord_binary: str = "arecord") -> list[str]:
    parsed = _run_list(arecord_binary)
    candidates: list[str] = []
    for device in parsed:
        if device in {"default", "sysdefault", "null"}:
            continue
        route = _route_name(device)
        if route not in {"plughw", "hw"}:
            continue
        card, _ = _parse_card_dev(device)
        if card:
            candidates.append(device)

    by_card: dict[str, list[str]] = {}
    for device in candidates:
        card, _ = _parse_card_dev(device)
        if card:
            by_card.setdefault(card, []).append(device)

    chosen: list[str] = []
    for _card, devices in by_card.items():
        for route in ("plughw", "hw"):
            matches = [device for device in devices if _route_name(device) == route]
            if matches:
                matches.sort(key=lambda device: (_parse_card_dev(device)[1] or 0, device))
                chosen.append(matches[0])
                break

    def sort_key(value: str) -> tuple[int, str]:
        card, _ = _parse_card_dev(value)
        friendly = _friendly_card_name(card or "").lower()
        if "usb" in friendly or "jabra" in friendly:
            return (0, friendly)
        if "blue" in friendly:
            return (1, friendly)
        return (2, friendly)

    return sorted(dict.fromkeys(chosen), key=sort_key)


def format_device_label(device_id: str | None) -> str:
    """Turn an ALSA selector into a compact label suitable for the 240px UI."""

    if not device_id:
        return "Auto"

    normalized = _normalize_alsa_selector(device_id)
    route = _route_name(normalized)
    card, dev = _parse_card_dev(normalized)
    if card:
        friendly = _friendly_card_name(card)
        label = "HDMI" if route == "hdmi" or card.lower() == "vc4hdmi" else friendly
        if dev not in (None, 0) and len(label) <= 14:
            label = f"{label} {dev}"
        label = label.strip()
        return label[:17] + "..." if len(label) > 18 else label

    for prefix in (
        "default:",
        "sysdefault:",
        "plughw:",
        "front:",
        "dsnoop:",
        "dmix:",
        "hw:",
        "iec958:",
        "hdmi:",
    ):
        if normalized.lower().startswith(prefix):
            normalized = normalized[len(prefix) :]
            break

    normalized = normalized.strip()
    if not normalized:
        return "Auto"
    return normalized[:17] + "..." if len(normalized) > 18 else normalized


class AudioDeviceCatalog:
    """Cache audio-device options and refresh them off the UI input path."""

    def __init__(
        self,
        *,
        aplay_binary: str = "aplay",
        arecord_binary: str = "arecord",
    ) -> None:
        self.aplay_binary = aplay_binary
        self.arecord_binary = arecord_binary
        self._lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._refresh_thread: threading.Thread | None = None
        self._playback_devices: list[str] = []
        self._capture_devices: list[str] = []

    def playback_devices(self) -> list[str]:
        with self._lock:
            return list(self._playback_devices)

    def capture_devices(self) -> list[str]:
        with self._lock:
            return list(self._capture_devices)

    def refresh(self) -> None:
        playback_devices = list_playback_devices(aplay_binary=self.aplay_binary)
        capture_devices = list_capture_devices(arecord_binary=self.arecord_binary)
        with self._lock:
            self._playback_devices = playback_devices
            self._capture_devices = capture_devices

    def refresh_async(self) -> None:
        with self._refresh_lock:
            worker = self._refresh_thread
            if worker is not None and worker.is_alive():
                return

            worker = threading.Thread(
                target=self._refresh_worker,
                name="audio-device-catalog-refresh",
                daemon=True,
            )
            self._refresh_thread = worker
            worker.start()

    def _refresh_worker(self) -> None:
        try:
            self.refresh()
        except Exception as exc:
            logger.debug("Audio-device refresh failed: {}", exc)
