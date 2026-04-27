# YoYoPod Remote Playback On Device

This document describes the current device-side playback and media-import behavior for `yoyo-py`.

## MQTT Contract

Topics:

- `yoyopod/{deviceId}/cmd`
- `yoyopod/{deviceId}/ack`
- `yoyopod/{deviceId}/evt`

Rules:

- `ack` emits command acceptance only
- `evt` emits lifecycle only
- `ack` and `nack` must never be replayed as lifecycle events on `evt`

Accepted commands:

- `play_track`
- `pause`
- `resume`
- `stop`
- `store_media`

## ACK Payloads

```json
{
  "command_id": "cmd_123",
  "status": "ack",
  "payload": {
    "command": "play_track"
  }
}
```

```json
{
  "command_id": "cmd_123",
  "status": "nack",
  "reason": "invalid_command",
  "payload": {}
}
```

## Event Payloads

Playback lifecycle is published on `evt` with `type: "playback"`.

Supported `eventType` values:

- `buffering`
- `playing`
- `paused`
- `stopped`
- `completed`
- `failed`

Device-local media import lifecycle is also published on `evt`, but with `type: "media_library"`.

Supported media-library `eventType` values:

- `imported`
- `failed`

## Remote Playback Cache

Remote playback uses a bounded local cache before mpv starts playback.

- cache key includes a sanitized `track_id`
- checksum is verified when provided
- cache downloads run off the coordinator thread before mpv load starts
- least-recently-used pruning uses file mtime and evicts oldest files first
- the just-fetched asset is protected from immediate self-eviction even when it exceeds the nominal cache cap
- playback runs from the cached local file, not the signed backend URL

Relevant config fields:

- `media.music.remote_cache_dir`
- `media.music.remote_cache_max_bytes`

Operational behavior:

- first remote play downloads and verifies the asset
- repeated plays reuse the cached local asset when possible
- short backend token lifetime does not interrupt playback after fetch completes

## Device-Local Media Import

Dashboard upload now supports device-local persistence through the backend-mediated `store_media` command.

Current import behavior:

1. backend finalizes the uploaded household track
2. backend sends `store_media` to the selected device over the same MQTT command dispatcher used for playback commands
3. device downloads the authorized asset through the same cache path used by remote playback
4. device persists the file under `YOYOPOD_MUSIC_DIR/dashboard_uploads/`
5. device updates `YOYOPOD_MUSIC_DIR/Dashboard Uploads.m3u`
6. device emits `media_library.imported` or `media_library.failed`

This keeps backend as the policy authority while making the resulting media available through the device-local `Listen` surface.

## Playback Behavior

- only one active remote playback session is tracked
- a new valid `play_track` interrupts the current remote playback
- pending downloads are correlated by `commandId` and activation generation so stale stop callbacks do not clear the next session
- if `stop` arrives while a remote asset is still buffering, the pending asset is discarded and playback does not start after the stop ACK
- `pause` and `resume` run through the current mpv backend path
- duplicate `commandId` values are ACKed as duplicates and are not replayed
- `store_media` also participates in duplicate command suppression

## Real Validation Notes

Observed on the real `piz` device:

- `ack`
- `buffering`
- `playing`
- `paused`
- `resume -> playing`
- `stop -> stopped`
- `store_media -> media_library.imported`
- repeated import/play paths using cached assets

Operational note:

- the current Pi runtime still logs VoIP recovery warnings because the Liblinphone native backend is unavailable on that device image
- this does not block local music playback or media import
