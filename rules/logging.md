# Logging

Applies to: `yoyopod/core/logging.py`, `yoyopod/main.py`

## Overview

All logging via `loguru` (never stdlib `logging`). Centralized configuration in `yoyopod/core/logging.py`. Stdlib logging is intercepted and routed through loguru.

## Subsystem Tags

Use `get_subsystem_logger(subsystem)` for bound loggers. Available tags (6-char max):
- `comm`, `music`, `coord`, `ui`, `power`, `config`, `app`, `core`

Tags are auto-inferred from module names via `_SUBSYSTEM_OVERRIDES` mapping. Explicit binding overrides auto-inference.

## Log Format

```
{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {subsystem:<6} | {name}:{function}:{line} | {message}
```

## File Sinks

| Sink | Path | Level | Rotation | Retention |
|---|---|---|---|---|
| Main log | `logs/yoyopod.log` | configurable (default INFO) | 5 MB | 3 days |
| Error log | `logs/yoyopod_errors.log` | ERROR+ | 2 MB | 7 days |

Both use gzip compression, UTF-8 encoding, synchronous writes (`enqueue=False`).

## PID File

Written under the active lane state directory on startup:

- dev: `/opt/yoyopod-dev/state/yoyopod.pid`
- prod: `/opt/yoyopod-prod/state/yoyopod.pid`

`YOYOPOD_PID_FILE` is the systemd/launcher override that keeps the Rust runtime
and `yoyopod target ...` CLI on the same path. Do not use `/tmp/yoyopod.pid`;
`/tmp` sticky-bit ownership breaks cleanup when the service and SSH user differ.

## Startup/Shutdown Markers

```
===== yoyopod starting (version=X, pid=Y) =====
===== yoyopod shutting down (pid=Y) =====
```

Used by deploy commands to verify the app started successfully.

## Exception Handling

- `sys.excepthook` overridden to log unhandled main-thread exceptions
- `threading.excepthook` overridden to log unhandled worker-thread exceptions
- Both include full tracebacks with variable inspection (`diagnose=True`)

## Configuration

Logging settings live in `config/app/core.yaml` under `logging:`. Every setting
remains overridable via `YOYOPOD_*` environment variables.
