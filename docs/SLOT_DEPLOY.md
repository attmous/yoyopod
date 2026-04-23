# Slot Deploy (OTA-Ready)

This document describes the slot-deploy path for YoyoPod. It coexists with
the legacy `yoyopod@.service` / `yoyopod remote sync` flow. Use slot deploy
for Pis that have been bootstrapped; use the legacy flow for dev workflows
that edit files in place.

## On-device layout

```
/opt/yoyopod/
├── releases/                # immutable versioned dirs
│   ├── 2026.04.22-abc123/
│   │   ├── app/             # yoyopod + yoyopod_cli
│   │   ├── venv/            # pre-resolved site-packages
│   │   ├── bin/launch       # slot launcher (executable)
│   │   ├── assets/          # reserved for fonts/images
│   │   └── manifest.json    # schema-v1 release manifest
│   └── 2026.04.20-def456/   # previous release (kept for rollback)
├── current -> releases/2026.04.22-abc123
├── previous -> releases/2026.04.20-def456
├── bin/rollback.sh          # installed by bootstrap
└── state/                   # user data — never touched by updates
    ├── config/
    └── logs/
```

## First-time setup on a Pi

1. SSH to the Pi.
2. `git clone` the repo (anywhere — only used for bootstrap scripts).
3. Run:
   ```bash
   sudo -E ./deploy/scripts/bootstrap_pi.sh --migrate
   ```
4. Push your first release from the dev machine (next section).
5. On the Pi: `sudo systemctl enable --now yoyopod-slot.service`.

## Normal deploy from the dev machine

```bash
uv run python scripts/build_release.py --output ./build/releases --channel dev
yoyopod remote release push ./build/releases/<version>
```

This does:
1. rsync the slot dir to `/opt/yoyopod/releases/<version>/`
2. `yoyopod health preflight --slot /opt/yoyopod/releases/<version>` over SSH
3. Atomic symlink flip: `current → <version>`, `previous → <old current>`
4. `systemctl restart yoyopod-slot.service`
5. `yoyopod health live` — polls for up to 60 s for the new version to report

If any step fails, the CLI cleans up (step 2 failure) or calls rollback (step 5 failure).

## Rollback

Manually:
```bash
yoyopod remote release rollback
```

Automatically: systemd fires `yoyopod-rollback.service` after 3 crashes in 5 min.

## Status

```bash
yoyopod remote release status
```

Shows current + previous versions and a quick health signal.
