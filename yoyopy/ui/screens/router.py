"""
Declarative screen routing for YoyoPod.
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
        """Return the default route map for current YoyoPod screens."""
        return {
            "hub": {
                "select:Now Playing": NavigationRequest.push("now_playing"),
                "select:Playlists": NavigationRequest.push("playlists"),
                "select:Calls": NavigationRequest.push("call"),
            },
            "home": {
                "select": NavigationRequest.push("menu"),
            },
            "menu": {
                "back": NavigationRequest.pop(),
                "select:Back": NavigationRequest.pop(),
                "select:Load Playlist": NavigationRequest.push("playlists"),
                "select:Music": NavigationRequest.push("now_playing"),
                "select:Podcasts": NavigationRequest.push("now_playing"),
                "select:Audiobooks": NavigationRequest.push("now_playing"),
                "select:Now Playing": NavigationRequest.push("now_playing"),
                "select:Browse Playlists": NavigationRequest.push("playlists"),
                "select:Playlists": NavigationRequest.push("playlists"),
                "select:VoIP Status": NavigationRequest.push("call"),
                "select:Call Parent": NavigationRequest.push("contacts"),
                "select:Call": NavigationRequest.push("contacts"),
                "select:Call Contact": NavigationRequest.push("contacts"),
                "select:Contacts": NavigationRequest.push("contacts"),
            },
            "now_playing": {
                "back": NavigationRequest.pop(),
            },
            "playlists": {
                "back": NavigationRequest.pop(),
                "playlist_loaded": NavigationRequest.push("now_playing"),
            },
            "call": {
                "back": NavigationRequest.pop(),
                "browse_contacts": NavigationRequest.push("contacts"),
                "call_started": NavigationRequest.push("outgoing_call"),
            },
            "contacts": {
                "back": NavigationRequest.pop(),
                "call_started": NavigationRequest.push("outgoing_call"),
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
