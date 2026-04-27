# Raspberry Pi Profiling Workflow

This guide is the repo-owned profiling path for YoYoPod performance and
runtime investigations.

Use it when you want to answer questions like:

- did the branch make startup slower?
- is the coordinator loop spending more time in one phase?
- is the Pi staying responsive during music, VoIP, and navigation soaks?
- is memory growth coming from Python code or a native dependency?

For the Raspberry Pi Zero 2 W, treat target-hardware results as the source of
truth. Desktop simulation is still useful, but it is a fast triage step, not
proof that the Pi will behave the same way.

## Runtime Hybrid Phase 0 Baseline

Use this workflow before moving voice and network work into sidecar workers.
The goal is to capture responsiveness and PSS/RSS with the current
single-supervisor runtime so Phase 2/3 changes can be compared against a real
target-hardware baseline.

Enable responsiveness captures for the dev-lane run in the Pi service/runtime
environment. These exports are examples of the values the service must see;
running them only in the local shell before `yoyopod remote sync` does not
guarantee they will be present in the systemd service environment. Apply the
same values through the Pi runtime environment or config used by the dev-lane
service:

```bash
export YOYOPOD_RESPONSIVENESS_WATCHDOG_ENABLED=true
export YOYOPOD_RESPONSIVENESS_STALL_THRESHOLD_SECONDS=5
export YOYOPOD_RESPONSIVENESS_RECENT_INPUT_WINDOW_SECONDS=3
```

Deploy and confirm the dev lane:

```bash
yoyopod remote mode activate dev
yoyopod remote sync --branch <branch>
yoyopod remote status
```

Capture recent logs and a status snapshot after the exercise:

```bash
yoyopod remote logs --lines 200
yoyopod remote status
```

Record these fields from logs, status output, and any generated responsiveness
captures. Keep null or missing values in the baseline notes too, because some
fields may be absent until enough samples or captures exist:

- `responsiveness_input_to_action_p95_ms`
- `responsiveness_action_to_visible_p95_ms`
- `runtime_loop_gap_seconds`
- `runtime_main_thread_drain_seconds`
- `runtime_blocking_span_name`
- `runtime_blocking_span_seconds`
- `process_memory_rss_kb`
- `process_memory_pss_kb`
- `workers`

Run a one-hour mixed soak that covers:

- idle screen wake/sleep
- music navigation and playback
- incoming or simulated VoIP state changes
- voice command path with current local settings
- cellular/network reconnect or status polling
- low-risk power/status screen navigation

The pre-worker baseline is not pass/fail. Use it to identify the top stalls
and memory pressure before Phase 2/3, then keep the raw notes with the branch
or release artifacts they describe.

## Runtime Hybrid Phase 2 Cloud Voice Measurement

Use this after the Go cloud voice worker is wired behind the feature flag.

### Build and deploy

```bash
uv run yoyopod build voice-worker
yoyopod remote mode activate dev
yoyopod remote sync --branch <branch>
```

### Required scenarios

Capture status and process memory for each scenario:

- voice disabled
- local Vosk configured and one transcription attempted
- Go voice worker idle with mock provider
- Go voice worker cloud STT request
- Go voice worker cloud TTS request
- provider unavailable or missing credentials
- worker crash and supervisor restart

### Fields to record

- supervisor PSS/RSS
- voice worker PSS/RSS
- total process tree PSS/RSS
- `responsiveness_input_to_action_p95_ms`
- `responsiveness_action_to_visible_p95_ms`
- `runtime_main_thread_drain_seconds`
- voice worker pending requests
- voice worker restart count
- protocol errors and dropped messages

### Acceptance target

Cloud voice mode is acceptable only if STT/TTS requests avoid UI-loop stalls
and total PSS is lower than the current local Vosk command path when Vosk is
resident.

## 1. Install the profiling tools

The repo now tracks the common Python-side tools in the `dev` extra:

```bash
uv sync --extra dev
uv run yoyopod dev profile tools
```

That gives you:

- `pyinstrument` for quick sampled call-stack reports
- `pyperf` for repeatable benchmark runs and branch-to-branch comparisons
- `py-spy` for low-overhead sampling, especially on the Pi
- `pytest-timeout` for hang detection during tests

The Linux `perf` tool is still a system package, not a Python dependency.

## 2. Start with the repo's own target diagnostics

Before reaching for external profilers, run the normal target validation flow.
YoYoPod already emits the most important coordinator-loop timing signals:

- `Runtime loop blocked`
- `Coordinator blocking span`
- `Runtime iteration slow`
- `VoIP iterate timing drift`
- `VoIP timing window`

Recommended flow:

```bash
git branch --show-current
git rev-parse HEAD
yoyopod remote validate --branch <branch> --sha <commit> --with-music --with-voip --with-navigation
yoyopod remote logs --follow --filter coord
yoyopod remote logs --follow --filter comm
```

For longer Pi soaks, consider enabling the responsiveness watchdog in
`config/app/core.yaml`:

```yaml
diagnostics:
  responsiveness_watchdog_enabled: true
  responsiveness_stall_threshold_seconds: 5.0
```

That captures evidence bundles under `logs/responsiveness/` when the loop
stops advancing.

## 3. Use bounded local targets for branch-to-branch comparisons

The repo ships a bounded helper script plus `yoyopod dev profile` wrappers so
you can benchmark startup and loop behavior without manually stopping the app.

List the targets:

```bash
uv run yoyopod dev profile targets
```

Current targets:

- `scaffold-loop`: lightweight event-bus and scheduler loop without full boot
- `simulate-bootstrap`: full simulated app setup + teardown once
- `simulate-loop`: simulated boot plus bounded coordinator-loop iterations

### Quick startup triage with `cProfile`

```bash
uv run yoyopod dev profile cprofile --target simulate-bootstrap
uv run yoyopod dev profile cprofile --target simulate-loop --iterations 300
```

Artifacts land under `logs/profiles/` by default, and the command also prints a
top-functions summary.

### Fast call-stack report with `pyinstrument`

```bash
uv run yoyopod dev profile pyinstrument --target simulate-bootstrap
uv run yoyopod dev profile pyinstrument --target simulate-loop --iterations 300 --html
```

Use `--html` when you want the navigable report.

### Repeatable benchmark runs with `pyperf`

```bash
uv run yoyopod dev profile pyperf --target scaffold-loop --fast
uv run yoyopod dev profile pyperf --target simulate-bootstrap --output logs/profiles/bootstrap.json
uv run yoyopod dev profile pyperf --target simulate-loop --iterations 300 --track-memory
```

Compare saved runs with:

```bash
uv run python -m pyperf compare_to logs/profiles/baseline.json logs/profiles/changed.json --table
```

If results look noisy on Linux, use:

```bash
uv run python -m pyperf system tune
```

Only do that on machines where changing benchmark-related system settings is
acceptable.

## 4. Profile the running Pi with `py-spy` when logs point at CPU hotspots

After `yoyopod remote validate` leaves the app running on the board:

```bash
ssh <pi-host>
cd ~/yoyopod-core
source .venv/bin/activate
mkdir -p logs/profiles
py-spy record -o logs/profiles/pyspy.svg --pid "$(cat /tmp/yoyopod.pid)"
```

Useful variants:

```bash
py-spy top --pid "$(cat /tmp/yoyopod.pid)"
py-spy dump --pid "$(cat /tmp/yoyopod.pid)"
py-spy record -o logs/profiles/pyspy-speedscope.json --format speedscope --pid "$(cat /tmp/yoyopod.pid)"
```

Notes:

- attaching to a live process may require `sudo` or relaxed ptrace settings
- use this after the repo's own coordinator and VoIP timing logs already point
  at "something CPU-bound is wrong"
- `py-spy` is especially useful when you want a flame graph without modifying
  the running code

## 5. Use Linux `perf` when native code or scheduler behavior looks suspicious

`perf` matters here because YoYoPod crosses Python, mpv, Liblinphone, display
drivers, and kernel scheduling.

For a live process:

```bash
perf stat -p "$(cat /tmp/yoyopod.pid)" -I 1000
```

For a bounded fresh run where you want Python function names in the output on
Python 3.12+:

```bash
mkdir -p logs/profiles
PYTHONPERFSUPPORT=1 perf record -F 99 -g -o logs/profiles/perf-simulate-bootstrap.data \
  python scripts/profile.py run simulate-bootstrap
perf report -g -i logs/profiles/perf-simulate-bootstrap.data
```

If the interpreter was not started with `PYTHONPERFSUPPORT=1` or `python -X perf`,
`perf` can still show native hot spots, but Python function names may be missing.

## 6. Use test timeouts for hangs, not performance regressions

`pytest-timeout` is for "this test wedged" situations:

```bash
uv run pytest -q --timeout=60
uv run pytest -q tests/e2e/test_app_orchestration.py --timeout=60
```

Use it to get thread dumps when the suite stalls. Do not use it as a benchmark
tool.

## 7. Practical sequence for this repo

When you are checking whether an architecture change regressed the Pi, use this
order:

1. Run `uv run python scripts/quality.py gate && uv run pytest -q`.
2. Run `yoyopod remote validate --branch <branch> --sha <commit> --with-music --with-voip --with-navigation`.
3. Inspect `coord` and `comm` log warnings first.
4. Compare `simulate-bootstrap` or `simulate-loop` with `yoyopod dev profile`.
5. If the Pi still looks CPU-bound, attach `py-spy`.
6. If the time is disappearing into native code or scheduling, use `perf`.

That order keeps the cheapest and most repo-specific signals first, and only
drops to heavier system profilers when the app's own diagnostics are not enough.
