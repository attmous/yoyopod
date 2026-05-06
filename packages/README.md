# Packages

Shared monorepo packages live here.

Planned packages:

- `contracts/` for API schemas, device/cloud command contracts, and generated types.
- `sdk/` for client libraries used by apps and tooling.
- `ui/` for shared app UI components if web and mobile need them.

Device runtime crates under `device/` must not import app packages.
