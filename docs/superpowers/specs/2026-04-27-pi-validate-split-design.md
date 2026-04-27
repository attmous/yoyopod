# pi_validate Split Design

**Date:** 2026-04-27
**Owner:** Moustafa
**Status:** Draft for review
**Target hardware:** Raspberry Pi Zero 2W (no runtime impact)

---

## 1. Problem

`yoyopod_cli/pi_validate.py` is 2940 lines, and its companion `_pi_validate_helpers.py` is another 1350 lines. Together they form the largest concentrated block of CLI code in the repo (~4300 LOC across two files).

The existing companion file is itself evidence that someone already tried to split once and stopped halfway: `_pi_validate_helpers.py` extracts only the navigation soak helpers, leaving the other ~600 LOC of validation helpers (deploy checks, cloud voice helpers, voip drill infrastructure, environment checks, etc.) inline in `pi_validate.py`.

Day-to-day cost:
- Adding a new validation requires scrolling through a 2940-line file with 8 unrelated subcommands sharing a flat namespace.
- Code review on validation changes shows a wall of context that is mostly unrelated to the change.
- Tracing a bug in (e.g.) `voip_check` requires loading mental context for cloud_voice, music, and navigation soak even when those are irrelevant.
- The single-file shape makes it tempting to keep adding helpers inline rather than extract.

This is unblocked, mechanical debt. The natural sectioning is already obvious from the existing organization: 8 typer subcommands, each with its own helper cluster.

---

## 2. Goals

- Split `pi_validate.py` into a `pi_validate/` subpackage with one module per validation domain.
- Reorganize `_pi_validate_helpers.py` (1350 LOC of navigation soak infrastructure) into a focused `_navigation_soak/` subpackage with 4–5 logical modules.
- Preserve every observable behavior: same CLI surface (`yoyopod pi validate <subcommand>`), same flags, same exit codes, same output.
- Preserve every public symbol used by tests, by updating test imports to the new canonical location.
- Land the change as one atomic PR. The work is mechanical; a half-migrated state across PRs would be more confusing than a single big diff.

---

## 3. Non-goals

- No logic changes inside the moved code. No behavioral fixes, no improvements, no refactors of function bodies. Pure relocation.
- No reorganization of tests beyond updating import paths. `tests/cli/test_pi_validate_*.py` stays where it is.
- No renaming of helper functions or classes (e.g., `_CheckResult` stays `_CheckResult`).
- No per-domain subpackages (the alternative "Option B" granularity). If a single domain becomes painful later, that domain gets split into a subpackage as a follow-up — not preemptively.
- No changes to `pyproject.toml [tool.yoyopod_quality]` paths beyond what the rename mechanically requires.
- No back-compat shim for the old import paths. The package is internal; old paths break cleanly.

---

## 4. Proposed structure

```text
yoyopod_cli/pi_validate/
├── __init__.py          # typer.Typer assembly; registers the 8 subcommands
├── _common.py           # CheckResult, _print_summary, _resolve_runtime_path,
│                        # _nearest_existing_parent, _load_app_config,
│                        # _load_media_config — shared helpers
├── deploy.py            # ~170 LOC: deploy() command + deploy contract checks
├── cloud_voice.py       # ~900 LOC: cloud_voice() + voice worker protocol
│                        # client + cloud env + acoustic checks
├── system.py            # ~290 LOC: smoke() + environment / display / input /
│                        # power / rtc checks
├── music.py             # ~140 LOC: music() command
├── voip.py              # ~1100 LOC: voip() + drill recorder + soak primitives
├── stability.py         # ~70 LOC: stability() command
├── navigation.py        # ~80 LOC: navigation() command
├── lvgl.py              # ~65 LOC: lvgl() command
└── _navigation_soak/
    ├── __init__.py      # public re-export surface
    ├── plan.py          # ~200 LOC: NavigationSoakStep / Report / Error,
    │                    # build_navigation_soak_plan
    ├── handle.py        # ~210 LOC: NavigationSoakAppHandle protocol,
    │                    # YoyoPodAppNavigationSoakHandle, factory
    ├── pump.py          # ~170 LOC: env helpers, _pump_app, route helpers,
    │                    # sleep/wake exercise
    ├── idle.py          # ~120 LOC: run_navigation_idle_soak + idle helpers
    └── runner.py        # ~600 LOC: NavigationSoakFailure, NavigationSoakStats,
                         # _RuntimePump, NavigationSoakRunner, run_navigation_soak
```

`yoyopod_cli/pi_validate.py` (file) is deleted. `yoyopod_cli/_pi_validate_helpers.py` is deleted. `yoyopod_cli/pi_validate_helpers.py` (the public re-export shim) is deleted.

Total file count goes from 3 → 16 files. Average file size drops from ~1400 LOC to ~265 LOC. The two largest files (`cloud_voice.py` ~900 LOC and `voip.py` ~1100 LOC) remain large but each is internally coherent — see §11 for the rule under which they would be split further.

---

## 5. Module mapping

Source line ranges from current `pi_validate.py`:

| Lines | Symbol(s) | New home |
|---|---|---|
| 66–103 | `_CheckResult`, `_print_summary`, `_resolve_runtime_path`, `_nearest_existing_parent` | `pi_validate/_common.py` |
| 104–246 | deploy contract / runtime paths / entrypoint checks | `pi_validate/deploy.py` |
| 247–994 | cloud voice (env file, settings, worker protocol client, binary check, capture route, acoustic loopback, cycle check, command match) | `pi_validate/cloud_voice.py` |
| 995–1018 | `_load_app_config`, `_load_media_config` | `pi_validate/_common.py` |
| 1019–1248 | environment / display / input / power / rtc checks | `pi_validate/system.py` |
| 1249–1361 | `_music_check` | `pi_validate/music.py` |
| 1362–2313 | voip check + DrillResult / DrillRecorder + all soak primitives + run_quick_voip_check / run_voip_*_drill / run_voip_call_soak | `pi_validate/voip.py` |
| 2314–2339 | `deploy()` typer command | `pi_validate/deploy.py` |
| 2340–2494 | `cloud_voice()` typer command | `pi_validate/cloud_voice.py` |
| 2495–2550 | `smoke()` typer command | `pi_validate/system.py` |
| 2551–2576 | `music()` typer command | `pi_validate/music.py` |
| 2577–2727 | `voip()` typer command | `pi_validate/voip.py` |
| 2728–2795 | `stability()` typer command | `pi_validate/stability.py` |
| 2796–2875 | `navigation()` typer command | `pi_validate/navigation.py` |
| 2876–end | `lvgl()` typer command | `pi_validate/lvgl.py` |

From `_pi_validate_helpers.py`:

| Lines | Symbol(s) | New home |
|---|---|---|
| 27–234 | `NavigationSoakAppHandle`, `YoyoPodAppNavigationSoakHandle`, `_NavigationSoakAppFactory`, `_default_app_factory` | `_navigation_soak/handle.py` |
| 236–432 | `NavigationSoakError`, `NavigationSoakStep`, `NavigationSoakReport`, `build_navigation_soak_plan` | `_navigation_soak/plan.py` |
| 434–595 | `_temporary_env`, `_pump_app`, `_current_route`, `_dispatch_action`, `_reset_selection`, `_wait_for_route`, `_wait_for_track`, `_exercise_sleep_wake`, `_prepare_validation_music_dir` | `_navigation_soak/pump.py` |
| 596–716 | `run_navigation_idle_soak` and idle-only helpers | `_navigation_soak/idle.py` |
| 717–end | `NavigationSoakFailure`, `NavigationSoakStats`, `_temporary_env_var`, `_RuntimePump`, `NavigationSoakRunner`, `run_navigation_soak` | `_navigation_soak/runner.py` |

---

## 6. Typer registration pattern

The current entry point is `yoyopod_cli/main.py:135`:

```python
pi_app.add_typer(_pi_validate.app, name="validate")
```

After the split, `_pi_validate` becomes the `pi_validate` package, and `pi_validate.app` is constructed in `pi_validate/__init__.py`:

```python
# pi_validate/__init__.py
import typer

from . import (
    deploy as _deploy,
    cloud_voice as _cloud_voice,
    system as _system,
    music as _music,
    voip as _voip,
    stability as _stability,
    navigation as _navigation,
    lvgl as _lvgl,
)

app = typer.Typer()

app.command(name="deploy")(_deploy.deploy)
app.command(name="cloud_voice")(_cloud_voice.cloud_voice)
app.command(name="smoke")(_system.smoke)
app.command(name="music")(_music.music)
app.command(name="voip")(_voip.voip)
app.command(name="stability")(_stability.stability)
app.command(name="navigation")(_navigation.navigation)
app.command(name="lvgl")(_lvgl.lvgl)

__all__ = ["app"]
```

Each command module defines its function as a plain function (no `@app.command()` decorator) — registration happens in `__init__.py`. This keeps the modules import-cycle-free and individually testable.

`yoyopod_cli/main.py` keeps its existing import (`from yoyopod_cli import pi_validate as _pi_validate`) and the existing `pi_app.add_typer(_pi_validate.app, name="validate")` line continues to work unchanged because `pi_validate.app` is still exposed.

---

## 7. Tests and the public re-export shim

Four test files reference `pi_validate`:

- `tests/cli/test_pi_validate_helpers.py` — imports `from yoyopod_cli import _pi_validate_helpers as helpers` AND `from yoyopod_cli import pi_validate_helpers as public_helpers` (the public shim).
- `tests/cli/test_pi_validate_cloud_voice.py` — imports `from yoyopod_cli import pi_validate` and accesses many private symbols by attribute (`pi_validate._load_cloud_voice_env_file`, `pi_validate._cloud_voice_settings_check`, `pi_validate._VoiceWorkerProtocolClient`, etc.). It also monkeypatches imported modules (`pi_validate.shutil`, `pi_validate.subprocess`, `pi_validate.os`).
- `tests/cli/test_voip_cli.py` — `import yoyopod_cli.pi_validate as voip_cli`, accesses voip helpers.
- `tests/cli/test_yoyopod_cli_pi_validate.py` — `import yoyopod_cli.pi_validate as pi_validate; app = pi_validate.app` and accesses other top-level helpers.

After the split, three things change:

1. **The `yoyopod_cli/pi_validate_helpers.py` shim is deleted.** `tests/cli/test_pi_validate_helpers.py` updates both its imports to point at the new locations: `yoyopod_cli.pi_validate._navigation_soak` (and its submodules) for the helpers.

2. **Tests that access private helpers via attribute path migrate to submodule attribute paths.** Example:
   ```python
   # Before
   from yoyopod_cli import pi_validate
   result = pi_validate._cloud_voice_settings_check(settings, provider="mock")
   monkeypatch.setattr(pi_validate.shutil, "which", lambda b: f"/usr/bin/{b}")

   # After
   from yoyopod_cli.pi_validate import cloud_voice
   result = cloud_voice._cloud_voice_settings_check(settings, provider="mock")
   monkeypatch.setattr(cloud_voice.shutil, "which", lambda b: f"/usr/bin/{b}")
   ```
   This is the largest mechanical edit in the test suite — every `pi_validate.<helper>` and every monkeypatch target must be re-routed to the helper's new home submodule. There are likely 30–60 such call sites across the four test files; an exact count comes during implementation.

3. **`app = pi_validate.app` keeps working unchanged** — the top-level `pi_validate/__init__.py` still exposes `app`. Tests that only touch `app` (CLI invocation tests) need no changes.

No back-compat shim. The package is internal. The import-path and attribute-path breaks are acceptable; they happen once, in this PR, and are mechanical.

---

## 8. Internal cross-module references

Some helpers are likely shared across domains (e.g., `_load_app_config` is used by multiple subcommands). The migration must:

1. Identify cross-references during the move (a quick `grep` per moved symbol against the rest of `pi_validate.py` will surface them).
2. For symbols used by multiple domains, place them in `_common.py` rather than picking one domain to "own" them.
3. Acceptable rule of thumb: if a symbol is used by exactly one domain, it lives in that domain's module; if used by 2+ domains, it lives in `_common.py`.

This rule will be applied conservatively: when in doubt, move to `_common.py`. Over-aggressive co-location risks circular imports between domain modules.

---

## 9. Risks

1. **Missed import sweeps and missed attribute access.** Hardcoded imports of `from yoyopod_cli.pi_validate import X` may exist outside `tests/cli/`. Equally important: tests access private symbols via module-attribute path (`pi_validate._helper`, `pi_validate.shutil` for monkeypatching). Both must be swept. A repo-wide grep for `pi_validate\.` (with the dot) catches the latter pattern alongside the former.
2. **Circular imports.** If a domain module needs a helper that lives in another domain, the temptation is to import sideways. Mitigation: route shared helpers through `_common.py`. If two domains genuinely share infrastructure (e.g., voip and cloud_voice both need worker protocol bits), promote that infrastructure to `_common.py` or a third focused module rather than a sideways import.
3. **Typer registration regression.** The new `__init__.py` pattern is functionally equivalent to the existing `@app.command()` decorators, but a typo in command names or option signatures would silently produce a different CLI surface. Mitigation: verification step #2 below diffs `--help` output before/after.
4. **CI gate paths.** `pyproject.toml [tool.yoyopod_quality]` gates `yoyopod_cli` as a directory, so the rename is gate-transparent. Spot-check during implementation.
5. **`git log --follow` archaeology.** A pure rename split fragments file history. Using `git mv` (or `git log --follow`) for the largest sub-extracts mitigates this. For the small ones, history pointers in commit messages are sufficient.
6. **Branch conflicts.** Any in-flight feature branch touching `pi_validate.py` will conflict massively. Mitigation: time the merge for a moment when no such branches are mid-flight, or coordinate.

---

## 10. Verification

Before claiming done:

1. **Quality gate:** `uv run python scripts/quality.py gate` passes.
2. **CLI surface unchanged:** for each of the 8 subcommands, `yoyopod pi validate <subcommand> --help` produces identical output before and after the split (capture pre-split into a fixture, diff post-split).
3. **Test suite:** `uv run pytest -q tests/cli/` passes. Especially the four pi_validate-related test files listed in §7.
4. **Smoke run on Pi:** `yoyopod pi validate smoke` runs to completion on dev hardware. (Per `CLAUDE.md` the canonical smoke check.)
5. **Import and attribute-access sweep:** `grep -rn "yoyopod_cli\.pi_validate" yoyopod/ yoyopod_cli/ tests/ scripts/ deploy/` shows only legitimate uses — i.e., `from yoyopod_cli.pi_validate.<submodule> import X` or `yoyopod_cli.pi_validate.<submodule>.foo` for monkeypatching. No hit should reach into `pi_validate` as if it were a flat module.
6. **No leftover dead files:** `yoyopod_cli/pi_validate.py`, `yoyopod_cli/_pi_validate_helpers.py`, `yoyopod_cli/pi_validate_helpers.py` are deleted.
7. **Full test suite:** `uv run pytest -q` passes (mod known Windows-specific failures, per `CLAUDE.md` pre-commit rule guidance).

---

## 11. Out-of-scope follow-ups

These came up during brainstorming but are explicitly deferred to separate work:

- Splitting `cloud_voice.py` (~900 LOC) or `voip.py` (~1100 LOC) into per-domain subpackages. The trigger to split: a single domain accumulates a second large helper cluster (e.g., voip needing both "drill recorder" and "call soak" infrastructure to grow further) such that the file's table of contents stops fitting on one screen. Until then, internal section-comment headers within each file are sufficient.
- Reorganizing `tests/cli/test_pi_validate_*.py` into per-domain test files mirroring the new module split.
- Reviewing `yoyopod_cli/remote_*.py` (9 files, ~2200 LOC) for consolidation into a `remote/` subpackage. This is a peer-priority refactor, not a dependency.
- AppContext discipline pass (`yoyopod/core/app_context.py` 841 LOC). Higher payoff, separate scope.
- voip/call terminology unification (`AppContext.voip` field, `sync_context_voip_status`, etc.).
- Co-locating `yoyopod/backends/` into `yoyopod/integrations/`. Intentionally not pursued — see brainstorming session notes.
