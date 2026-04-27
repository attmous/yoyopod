# OTA Roadmap

The slot-deploy foundation (`docs/operations/SLOT_DEPLOY.md`) is designed so a future
OTA daemon can be added without changing any of the core deploy pieces.
This doc lists the exact extension points.

## What is already OTA-shaped

- **Manifest schema** (`yoyopod_cli/release_manifest.py`): already has
  `signature`, `channel`, `requires`, and diff-artifact fields. When OTA
  signing goes live, only the signing and verification paths change —
  the schema is stable.
- **Atomic slot flip**: `yoyopod_cli/atomic_symlink.py` + `rollback.sh`
  are the only state-mutating primitives. An OTA daemon calls the same
  primitives after downloading an artifact.
- **Rollback on failure**: `yoyopod-prod.service` has `OnFailure=`
  pointing at `yoyopod-prod-rollback.service`. An OTA-applied update that
  crash-loops triggers rollback without daemon involvement.
- **Health probes**: `yoyopod health preflight` + `yoyopod health live`
  are the same entry points the deploy CLI uses.

## What is NOT yet built

- **Update checker**: a systemd timer that polls an HTTPS manifest URL,
  diffs against the current version, and downloads when a match is found.
- **Signature verification**: manifest signing + on-device public-key
  verification before applying.
- **Diff patch application**: the manifest's `diff` artifact type is
  defined but the `zstd --patch-from` apply path isn't wired.
- **Per-device channel rollout**: server-side gating (canary 10% → 50%
  → 100%) based on device ID hashes.

## Recommended build order for OTA

1. **Manifest signing** — minisign/ed25519, CI-only signing key. Add
   `verify_manifest(path, pubkey)` to `release_manifest.py`.
2. **Static OTA bucket** — Cloudflare R2 / S3. Upload `manifest.json`
   + release tarballs + diff patches on every CI release tag.
3. **`yoyopod ota check` command** — fetches the manifest, compares
   versions, prints the update. No side effects yet.
4. **`yoyopod ota apply`** — downloads, verifies signature, runs
   preflight, flips symlinks. Reuses `atomic_symlink`.
5. **systemd timer** — runs `yoyopod ota check && yoyopod ota apply`
   every 6 h on the stable channel.
6. **Diff patches** — cut tarball size by 10–50× for small changes.
7. **Channel rollout** — server-side manifest variants + a device-ID
   hash check on the client.

See `docs/operations/SLOT_DEPLOY.md` for the current ops flow.
