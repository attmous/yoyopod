# Repo Work Areas

YoYoPod is now Rust-first for the device runtime. Use this map when deciding
where a change belongs.

## Primary Runtime

- `device/runtime/` owns process supervision, config loading, event routing,
  state composition, and UI snapshot delivery.
- `device/ui/` owns Whisplay/LVGL rendering and button-facing UI
  behavior.
- `device/media/` owns local music playback and mpv process control.
- `device/voip/` owns SIP, calls, and voice-message behavior through
  Liblinphone.
- `device/network/` owns cellular modem, PPP, and GPS behavior.
- `device/cloud/` owns MQTT/cloud telemetry and command transport.
- `device/power/` owns power/battery integration.
- `device/speech/` owns cloud speech, TTS, and Ask worker protocol.

## Monorepo App And Package Areas

- `apps/` is for web/mobile applications.
- `packages/` is for shared app/cloud contracts, SDKs, and reusable app code.
- Device runtime code must not depend on `apps/`.
- Shared contracts should flow through `packages/contracts/` when that package exists.

## Python Still-Owned Areas

- `yoyopod_cli/` owns local and Pi operations tooling.
- `deploy/` owns systemd, installer, slot, and release packaging scripts.
- Python code is CLI, deploy, and Pi validation tooling only; it is not the
  device runtime owner.

## Local Build Output

Do not work from generated output directories. These are disposable:

- `device/target/`
- `device/*/build/`
- `.venv/`
- `__pycache__/`
- `logs/`
- local `data/`

Do not commit runtime models, wasm preview bundles, local metadata exports, audio
files, fonts, or build artifacts directly to Git. Put required large assets in a
release artifact, package download step, or Git LFS only after deciding that the
asset is part of the source contract.

When disk usage gets large, clean ignored output with:

```bash
git clean -fdX
```

Run that only from a clean worktree because it deletes all ignored local files,
including local virtual environments and generated artifacts.
