# Legacy Python Runtime

This directory contains the retired Python app runtime and its old demo scripts.
It is not a supported runtime owner for the device and is excluded from
packaging and default tests.

Supported runtime code lives under `device/`. Supported operations tooling
lives under `yoyopod_cli/`.

Do not import this directory from active code. Delete this directory after the
Rust runtime has completed one hardware validation cycle without needing Python
runtime parity inspection.
