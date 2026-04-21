"""Compatibility export for callers still importing calling.messaging."""

from yoyopod.integrations.call.messaging import MessagingService

__all__ = ["MessagingService"]
