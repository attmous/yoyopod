"""
Declarative screen routing for YoYoPod.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from loguru import logger


@dataclass(frozen=True, slots=True)
class NavigationRequest:
    """Represents a pending navigation request emitted by a screen."""

    operation: str
    target: Optional[str] = None
    route_name: Optional[str] = None
    payload: Optional[Any] = None

    @classmethod
    def push(cls, target: str) -> "NavigationRequest":
        return cls(operation="push", target=target)

    @classmethod
    def pop(cls) -> "NavigationRequest":
        return cls(operation="pop")

    @classmethod
    def replace(cls, target: str) -> "NavigationRequest":
        return cls(operation="replace", target=target)

    @classmethod
    def route(cls, route_name: str, payload: Optional[Any] = None) -> "NavigationRequest":
        return cls(operation="route", route_name=route_name, payload=payload)


class ScreenRouter:
    """Resolve route names into concrete screen-stack navigation operations."""

    def __init__(self, routes: Optional[Dict[str, Dict[str, NavigationRequest]]] = None) -> None:
        self.routes = routes or self._default_routes()

    def resolve(
        self,
        screen_name: str,
        route_name: str,
        payload: Optional[Any] = None,
    ) -> Optional[NavigationRequest]:
        """Resolve a named route from a screen into a concrete navigation request."""
        screen_routes = self.routes.get(screen_name, {})
        route_key = self._route_key(route_name, payload)

        if route_key in screen_routes:
            return screen_routes[route_key]

        if route_name in screen_routes:
            return screen_routes[route_name]

        logger.warning(f"No route found for {screen_name}.{route_key}")
        return None

    def _default_routes(self) -> Dict[str, Dict[str, NavigationRequest]]:
        """Return the default route map for current YoYoPod screens."""
        return {
            "hub": {
                "select:Listen": NavigationRequest.push("listen"),
                "select:Talk": NavigationRequest.push("call"),
                "select:Ask": NavigationRequest.push("ask"),
                "select:Setup": NavigationRequest.push("power"),
                # Legacy aliases from the pre-overhaul Whisplay hub.
                "select:Now Playing": NavigationRequest.push("now_playing"),
                "select:Playlists": NavigationRequest.push("playlists"),
                "select:Calls": NavigationRequest.push("call"),
                "select:Power": NavigationRequest.push("power"),
                "hold_ask": NavigationRequest.push("ask"),
            },
            "home": {
                "select": NavigationRequest.push("menu"),
            },
            "menu": {
                "back": NavigationRequest.pop(),
                "select:Back": NavigationRequest.pop(),
                "select:Listen": NavigationRequest.push("listen"),
                "select:Talk": NavigationRequest.push("call"),
                "select:Ask": NavigationRequest.push("ask"),
                "select:Setup": NavigationRequest.push("power"),
                "select:Settings": NavigationRequest.push("power"),
                "select:Load Playlist": NavigationRequest.push("playlists"),
                "select:Music": NavigationRequest.push("listen"),
                "select:Podcasts": NavigationRequest.push("listen"),
                "select:Audiobooks": NavigationRequest.push("listen"),
                "select:Now Playing": NavigationRequest.push("now_playing"),
                "select:Browse Playlists": NavigationRequest.push("playlists"),
                "select:Playlists": NavigationRequest.push("playlists"),
                "select:VoIP Status": NavigationRequest.push("call"),
                "select:Talk Hub": NavigationRequest.push("call"),
                "select:Call Parent": NavigationRequest.push("contacts"),
                "select:Call": NavigationRequest.push("contacts"),
                "select:Call Contact": NavigationRequest.push("contacts"),
                "select:Contacts": NavigationRequest.push("contacts"),
                "select:Power Status": NavigationRequest.push("power"),
            },
            "listen": {
                "back": NavigationRequest.pop(),
                "open_playlists": NavigationRequest.push("playlists"),
                "open_recent": NavigationRequest.push("recent_tracks"),
                "shuffle_started": NavigationRequest.push("now_playing"),
            },
            "ask": {
                "back": NavigationRequest.pop(),
                "call_started": NavigationRequest.push("outgoing_call"),
                "shuffle_started": NavigationRequest.push("now_playing"),
                "open_talk": NavigationRequest.push("call"),
                "open_listen": NavigationRequest.push("listen"),
                "open_setup": NavigationRequest.push("power"),
                "go_home": NavigationRequest.replace("hub"),
            },
            "power": {
                "back": NavigationRequest.pop(),
            },
            "now_playing": {
                "back": NavigationRequest.pop(),
            },
            "playlists": {
                "back": NavigationRequest.pop(),
                "playlist_loaded": NavigationRequest.push("now_playing"),
            },
            "recent_tracks": {
                "back": NavigationRequest.pop(),
                "track_loaded": NavigationRequest.push("now_playing"),
            },
            "call": {
                "back": NavigationRequest.pop(),
                "open_contact": NavigationRequest.push("talk_contact"),
                "call_started": NavigationRequest.push("outgoing_call"),
            },
            "talk_contact": {
                "back": NavigationRequest.pop(),
                "call_started": NavigationRequest.push("outgoing_call"),
                "voice_note": NavigationRequest.push("voice_note"),
            },
            "contacts": {
                "back": NavigationRequest.pop(),
                "open_contact": NavigationRequest.push("talk_contact"),
                "call_started": NavigationRequest.push("outgoing_call"),
                "voice_note_selected": NavigationRequest.push("voice_note"),
            },
            "call_history": {
                "back": NavigationRequest.pop(),
                "call_started": NavigationRequest.push("outgoing_call"),
            },
            "voice_note": {
                "back": NavigationRequest.pop(),
            },
            "incoming_call": {
                "call_answered": NavigationRequest.push("in_call"),
                "call_rejected": NavigationRequest.pop(),
            },
            "in_call": {
                "call_hangup": NavigationRequest.pop(),
            },
            "outgoing_call": {
                "call_hangup": NavigationRequest.pop(),
            },
        }

    @staticmethod
    def _route_key(route_name: str, payload: Optional[Any]) -> str:
        """Create a lookup key for payload-sensitive routes."""
        if payload is None:
            return route_name
        return f"{route_name}:{payload}"
