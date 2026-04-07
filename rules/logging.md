# Logging

Applies to: `yoyopy/utils/logger.py`, `yoyopy/main.py`

## Overview

All logging via `loguru` (never stdlib `logging`). Centralized configuration in `yoyopy/utils/logger.py`. Stdlib logging is intercepted and routed through loguru.

## Subsystem Tags

Use `get_subsystem_logger(subsystem)` for bound loggers. Available tags (6-char max):
- `voip`, `music`, `coord`, `ui`, `power`, `config`, `app`, `core`

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

Written to `/tmp/yoyopod.pid` on startup, cleaned up via `atexit`. Used by `/yoyopod-restart`, `/yoyopod-deploy`, and `/yoyopod-status` for process management.

## Startup/Shutdown Markers

```
===== YoyoPod starting (version=X, pid=Y) =====
===== YoyoPod shutting down (pid=Y) =====
```

Used by deploy commands to verify the app started successfully.

## Exception Handling

- `sys.excepthook` overridden to log unhandled main-thread exceptions
- `threading.excepthook` overridden to log unhandled worker-thread exceptions
- Both include full tracebacks with variable inspection (`diagnose=True`)

## Configuration

All settings in `config/yoyopod_config.yaml` under `logging:` key. Every setting overridable via `YOYOPOD_*` environment variables.
