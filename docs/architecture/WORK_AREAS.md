# Repo Work Areas

YoYoPod is now Rust-first for the device runtime. Use this map when deciding
where a change belongs.

## Primary Runtime

- `yoyopod_rs/runtime/` owns process supervision, config loading, event routing,
  state composition, and UI snapshot delivery.
- `yoyopod_rs/ui/` owns Whisplay/LVGL rendering and button-facing UI
  behavior.
- `yoyopod_rs/media/` owns local music playback and mpv process control.
- `yoyopod_rs/voip/` owns SIP, calls, and voice-message behavior through
  Liblinphone.
- `yoyopod_rs/network/` owns cellular modem, PPP, and GPS behavior.
- `yoyopod_rs/cloud/` owns MQTT/cloud telemetry and command transport.
- `yoyopod_rs/power/` owns power/battery integration.
- `yoyopod_rs/speech/` owns cloud speech, TTS, and Ask worker protocol.

## Python Still-Owned Areas

- `yoyopod_cli/` owns local and Pi operations tooling.
- `deploy/` owns systemd, installer, slot, and release packaging scripts.
- `yoyopod/` remains for compatibility paths, Python app surfaces that have not
  been retired, and shared models still consumed by tooling.
- `tests/` contains both Rust-runtime migration coverage and Python
  CLI/compatibility coverage.

## Local Build Output

Do not work from generated output directories. These are disposable:

- `yoyopod_rs/target/`
- `yoyopod_rs/*/build/`
- `.venv/`
- `.pytest_cache/`
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
