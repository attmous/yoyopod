# Rust VoIP Domain Facade Slice

## Goal

Move the next set of VoIP runtime facts under the Rust host while Python remains the command bridge, persistence mirror, and app callback surface.

## Acceptance Criteria

- Rust `voip.snapshot` includes mute state and keeps it consistent across `voip.set_mute`, configure, unregister, and backend failure reset paths.
- Python parses and mirrors the Rust-owned mute state from `VoIPRuntimeSnapshot`.
- In Rust-host mode, outgoing Python commands do not invent call identity or mute state before Rust snapshots report them.
- Legacy Python/mock backends keep their current optimistic behavior where no Rust snapshot owner exists.
- Code follows clean-code and Rust coding guidelines: small focused helpers, readable names, no broad refactors, and tests that describe behavior.

## Work Plan

- [x] Add failing Rust host tests for snapshot-owned mute state.
- [x] Add failing Python tests for snapshot-owned mute and outgoing-call identity.
- [x] Add `muted` to the Rust `VoipHost` state and snapshot payload.
- [x] Add `muted` to Python `VoIPRuntimeSnapshot` parsing and manager mirroring.
- [x] Gate optimistic Python command updates behind a legacy-backend check.
- [x] Run focused tests, then full quality gates.
- [ ] Commit, push, and open a PR.
