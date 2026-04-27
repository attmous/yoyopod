# Architecture Docs

Current runtime and package-ownership contracts live here.

- [`SYSTEM_ARCHITECTURE.md`](SYSTEM_ARCHITECTURE.md) - runtime topology, bootstrap flow, and subsystem boundaries
- [`CANONICAL_STRUCTURE.md`](CANONICAL_STRUCTURE.md) - config topology, package ownership, and test layout
- [`RUNTIME_EVENT_FLOW.md`](RUNTIME_EVENT_FLOW.md) - typed event pipeline and main-thread ownership
- [`CROSS_SCREEN_OVERLAYS.md`](CROSS_SCREEN_OVERLAYS.md) - overlay ownership and ordering rules
- [`DISPLAY_HAL_ARCHITECTURE.md`](DISPLAY_HAL_ARCHITECTURE.md) - display abstraction and adapters
- [`INPUT_HAL_ARCHITECTURE.md`](INPUT_HAL_ARCHITECTURE.md) - semantic input model and adapters
- [`GLOBAL_AUDIO_DEVICE_FACADE_CONTRACT.md`](GLOBAL_AUDIO_DEVICE_FACADE_CONTRACT.md) - shared audio-device contract

For day-to-day setup and deploy work, use [`../operations/README.md`](../operations/README.md).
