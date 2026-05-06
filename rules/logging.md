# Logging

Applies to: `device/runtime/**`, `device/*/src/**`, `yoyopod_cli/**`, and
`deploy/**`.

## Overview

Rust runtime and worker logs are the product runtime source of truth. Python
logging rules apply only to CLI/deploy tooling.

Rust code should use the workspace logging/tracing pattern already present in
the touched crate. CLI Python should use normal structured command output and
raise `typer.Exit` for command failures instead of recreating runtime logging.

## Subsystem Tags

Use stable subsystem names in log messages and worker events:

- `runtime`
- `ui`
- `media`
- `voip`
- `network`
- `power`
- `speech`
- `cloud`
- `config`

## Log Format

```
{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {subsystem:<6} | {name}:{function}:{line} | {message}
```

## File Sinks

Systemd owns process output in dev/prod lanes. Runtime logs should be readable
through `journalctl` and the `yoyopod remote logs` helpers.

If a command writes a diagnostic file, it must be explicit in the command output
and belong under the configured data/log path, not a hidden runtime side effect.

## PID File

PID/log lifecycle is owned by `yoyopod-runtime` and systemd services:

- `deploy/systemd/yoyopod-dev.service`
- `deploy/systemd/yoyopod-prod.service`

CLI commands should inspect those services or runtime status output instead of
depending on retired runtime PID files.

## Exception Handling

- Rust runtime errors should carry enough context to identify the host, worker,
  command, and device path involved.
- Worker protocol failures should emit structured error envelopes where possible.
- CLI Python should print concise operator-facing errors and return non-zero.

## Configuration

Logging settings live in current runtime config and service environment. Every
setting that affects production behavior must remain visible through config,
systemd environment, or runtime status output.
