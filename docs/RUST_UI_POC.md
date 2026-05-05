# Rust UI PoC Compatibility

The former Rust UI PoC is now the Rust UI Host. The old `rust-ui-poc` commands
remain as compatibility aliases, but new production source, CI artifacts, and
hardware validation should use the host names.

Current contract:

- Docs: `docs/RUST_UI_HOST.md`
- CI artifact: `yoyopod-rust-device-arm64-<sha>`
- Pi checkout binary: `yoyopod_rs/ui/build/yoyopod-ui-host`
- Build command: `yoyopod build rust-ui-host`
- Pi smoke command: `yoyopod pi rust-ui-host`

Do not build Rust on the Pi Zero 2W. Commit and push first, wait for the CI
`rust-device-arm64` artifact for the exact commit, then extract that device
bundle on the target.
