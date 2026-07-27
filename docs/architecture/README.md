# Architecture Docs

Runtime topology, package/config ownership, event flow, and the
cross-cutting structural contracts that define how yoyopod is composed.

- [`SYSTEM_ARCHITECTURE.md`](SYSTEM_ARCHITECTURE.md) - current runtime
  shape: the Rust runtime, the worker hosts, and the operator CLI
- [`WORK_AREAS.md`](WORK_AREAS.md) - where active Rust-first work
  belongs by area
- [`CANONICAL_STRUCTURE.md`](CANONICAL_STRUCTURE.md) - config topology,
  package ownership, validation layout, and board overlay rules
- [`RUNTIME_EVENT_FLOW.md`](RUNTIME_EVENT_FLOW.md) - how runtime events
  flow from worker hosts through `yoyopod-runtime` into app state

For the operator-side view (deploy / lanes / hardware validation), see
[`../operations/README.md`](../operations/README.md). For UI design
constraints, see [`../design/README.md`](../design/README.md). For the
current rebuild status, see [`../ROADMAP.md`](../ROADMAP.md).
