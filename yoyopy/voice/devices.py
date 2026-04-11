"""Helpers for listing ALSA capture/playback devices for UI selection.

These functions intentionally have safe fallbacks when running in environments
without ALSA utilities (for example the Windows simulator).
"""

from __future__ import annotations

import re
import shutil
import subprocess
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
        # Device identifiers are on non-indented lines; descriptions are indented.
        if not line or line.startswith(" "):
            continue
        device = line.strip()
        if not device:
            continue
        if device in {"null"}:
            continue
        devices.append(device)
    return devices


@lru_cache(maxsize=1)
def _asound_card_aliases() -> dict[str, str]:
    """Return ALSA card-id -> friendly name mapping when available."""

    cards_path = Path("/proc/asound/cards")
    if not cards_path.exists():
        return {}

    try:
        text = cards_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}

    aliases: dict[str, str] = {}
    for line in text.splitlines():
        # Example:
        #  1 [SE             ]: USB-Audio - Jabra Evolve 75 SE
        match = re.match(r"^\s*\d+\s+\[([^\]]+)\]:\s*(.+?)\s*$", line)
        if not match:
            continue
        card_id = match.group(1).strip()
        rest = match.group(2).strip()
        if not card_id or not rest:
            continue
        friendly = rest
        if " - " in rest:
            friendly = rest.split(" - ", 1)[1].strip() or rest
        aliases[card_id] = friendly
    return aliases


def _friendly_card_name(card_id: str) -> str:
    return _asound_card_aliases().get(card_id, card_id)


def _parse_card_dev(device: str) -> tuple[str | None, int | None]:
    """Extract CARD and DEV fields from an ALSA selector string."""

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
    """Return ALSA playback devices in a stable, UI-friendly order."""

    parsed = _run_list(aplay_binary)
    candidates: list[str] = []
    for device in parsed:
        if device in {"default", "sysdefault", "null"}:
            continue
        route = _route_name(device)
        # Keep only "physical" options: one per card, prefer plughw; keep HDMI explicitly.
        if route not in {"plughw", "hw", "hdmi"}:
            continue
        card, _ = _parse_card_dev(device)
        if not card:
            continue
        candidates.append(device)

    # Choose one best route per card.
    by_card: dict[str, list[str]] = {}
    for device in candidates:
        card, _ = _parse_card_dev(device)
        if not card:
            continue
        by_card.setdefault(card, []).append(device)

    chosen: list[str] = []
    for card, devices in by_card.items():
        # Prefer hdmi for HDMI cards, otherwise plughw then hw.
        priority = ["plughw", "hw"]
        if card.lower() in {"vc4hdmi"}:
            priority = ["hdmi", "plughw", "hw"]
        best: str | None = None
        for route in priority:
            matches = [d for d in devices if _route_name(d) == route]
            if matches:
                # Prefer lowest DEV if multiple.
                matches.sort(key=lambda d: (_parse_card_dev(d)[1] or 0, d))
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
        # Rough heuristics: keep USB-ish headsets first.
        if "usb" in friendly or "jabra" in friendly:
            return (0, friendly)
        if "blue" in friendly:
            return (1, friendly)
        return (3, friendly)

    chosen = sorted(dict.fromkeys(chosen), key=sort_key)
    return chosen


def list_capture_devices(*, arecord_binary: str = "arecord") -> list[str]:
    """Return ALSA capture devices in a stable, UI-friendly order."""

    parsed = _run_list(arecord_binary)
    candidates: list[str] = []
    for device in parsed:
        if device in {"default", "sysdefault", "null"}:
            continue
        route = _route_name(device)
        if route not in {"plughw", "hw"}:
            continue
        card, _ = _parse_card_dev(device)
        if not card:
            continue
        candidates.append(device)

    by_card: dict[str, list[str]] = {}
    for device in candidates:
        card, _ = _parse_card_dev(device)
        if not card:
            continue
        by_card.setdefault(card, []).append(device)

    chosen: list[str] = []
    for card, devices in by_card.items():
        for route in ("plughw", "hw"):
            matches = [d for d in devices if _route_name(d) == route]
            if matches:
                matches.sort(key=lambda d: (_parse_card_dev(d)[1] or 0, d))
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

    chosen = sorted(dict.fromkeys(chosen), key=sort_key)
    return chosen


def format_device_label(device_id: str | None) -> str:
    """Turn an ALSA selector into a compact label suitable for the 240px UI."""

    if not device_id:
        return "Auto"

    normalized = _normalize_alsa_selector(device_id)

    route = _route_name(normalized)
    card, dev = _parse_card_dev(normalized)
    if card:
        friendly = _friendly_card_name(card)
        # Special-case HDMI for readability.
        if route == "hdmi" or card.lower() == "vc4hdmi":
            label = "HDMI"
        else:
            label = friendly
        if dev not in (None, 0) and len(label) <= 14:
            label = f"{label} {dev}"
        label = label.strip()
        if len(label) > 18:
            return label[:17] + "..."
        return label

    # Keep the full selector for power users, but avoid noisy prefixes.
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

    if len(normalized) > 18:
        return normalized[:17] + "..."
    return normalized
