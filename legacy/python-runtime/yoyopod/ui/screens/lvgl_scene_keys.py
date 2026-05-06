"""Canonical retained-scene keys for pooled LVGL view families.

These keys describe native scene pools, not independent per-controller caches.
When multiple controllers intentionally share one scene family, only the latest
retained Python view that built that scene remains reusable.
"""

LIST_SCENE_KEY = "playlist"
"""Shared list-scene pool for playlists, recents, contacts, and call history."""

TALK_ACTIONS_SCENE_KEY = "talk_actions"
"""Shared action-scene pool for Talk contact actions and voice-note states."""
