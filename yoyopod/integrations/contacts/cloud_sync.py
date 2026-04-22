"""Cloud-contact synchronization helpers for the mutable people directory."""

from __future__ import annotations

from typing import Any

from yoyopod.integrations.contacts.models import Contact


def build_cloud_contact(entry: dict[str, Any]) -> Contact | None:
    """Build one cloud-managed contact from backend config payload."""

    contact_id = str(entry.get("id") or "").strip()
    name = str(entry.get("name") or "").strip()
    if not contact_id or not name:
        return None

    relationship = str(entry.get("relationship") or "").strip()
    return Contact(
        name=name,
        sip_address=str(entry.get("sip_address") or "").strip(),
        phone_number=str(entry.get("phone_number") or "").strip(),
        favorite=bool(entry.get("is_primary", False)),
        notes=relationship,
        contact_id=contact_id,
        sync_origin="cloud",
        can_call=bool(entry.get("can_call", True)),
        can_receive=bool(entry.get("can_receive", True)),
    )
