#!/usr/bin/env python3
"""Repo-owned profiling helpers for bounded YoYoPod investigations."""

from __future__ import annotations

import argparse
import cProfile
import importlib.util
import io
import pstats
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_OUTPUT_DIR = REPO_ROOT / "logs" / "profiles"
PROFILE_SCRIPT = REPO_ROOT / "scripts" / "profile.py"


@dataclass(frozen=True)
class TargetSpec:
    """One bounded runtime or benchmark target."""

    help: str
    default_iterations: int
    runner: Callable[[int], int]


def _resolve_output_path(raw_path: str | None, *, target: str, suffix: str) -> Path:
    """Resolve one optional output path relative to the repo root."""

    if raw_path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = REPO_ROOT / path
    else:
        path = PROFILE_OUTPUT_DIR / f"{target}{suffix}"

    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _import_yoyopod_app() -> type[object]:
    """Import the canonical app lazily so help/tooling commands stay lightweight."""

    from yoyopod.app import YoyoPodApp

    return YoyoPodApp


def _run_scaffold_loop(iterations: int) -> int:
    """Benchmark the lightweight scaffold loop without full runtime boot."""

    YoyoPodApp = _import_yoyopod_app()
    app = YoyoPodApp(strict_bus=True)
    try:
        app.run(sleep_seconds=0.0, max_iterations=max(1, iterations))
        return 0
    finally:
        app.stop()


def _with_simulated_app(callback: Callable[[object], None]) -> int:
    """Boot one simulated app, run a callback, and always tear it down cleanly."""

    YoyoPodApp = _import_yoyopod_app()
    app = YoyoPodApp(simulate=True)
    try:
        if not app.setup():
            return 1
        callback(app)
        return 0
    finally:
        app.stop()


def _run_simulate_bootstrap(_iterations: int) -> int:
    """Measure simulated boot and teardown without entering the infinite app loop."""

    return _with_simulated_app(lambda _app: None)


def _run_simulate_loop(iterations: int) -> int:
    """Measure boot plus bounded coordinator-loop iterations in simulation mode."""

    def _profiled_run(app: object) -> None:
        runtime_loop = getattr(app, "runtime_loop")
        monotonic_now = time.monotonic()
        current_time = time.time()
        last_screen_update = current_time
        screen_update_interval = 0.1

        for _ in range(max(1, iterations)):
            monotonic_now += 0.02
            current_time += 0.02
            last_screen_update = runtime_loop.run_iteration(
                monotonic_now=monotonic_now,
                current_time=current_time,
                last_screen_update=last_screen_update,
                screen_update_interval=screen_update_interval,
            )

    return _with_simulated_app(_profiled_run)


TARGETS: dict[str, TargetSpec] = {
    "scaffold-loop": TargetSpec(
        help="Run the lightweight scaffold loop without full runtime boot.",
        default_iterations=5000,
        runner=_run_scaffold_loop,
    ),
    "simulate-bootstrap": TargetSpec(
        help="Construct, set up, and stop the full simulated app once.",
        default_iterations=1,
        runner=_run_simulate_bootstrap,
    ),
    "simulate-loop": TargetSpec(
        help="Boot the simulated app and run bounded coordinator-loop iterations.",
        default_iterations=200,
        runner=_run_simulate_loop,
    ),
}


def run_target(target: str, *, iterations: int | None = None) -> int:
    """Run one named profiling target."""

    spec = TARGETS.get(target)
    if spec is None:
        raise SystemExit(f"Unsupported profiling target: {target}")

    effective_iterations = spec.default_iterations if iterations is None else iterations
    return spec.runner(effective_iterations)


def build_pyperf_command(
    *,
    target: str,
    iterations: int,
    name: str,
    output: Path,
    fast: bool,
    rigorous: bool,
    track_memory: bool,
    quiet: bool,
) -> tuple[str, ...]:
    """Build the repo-owned pyperf command for one bounded target."""

    command: list[str] = [sys.executable, "-m", "pyperf", "command"]
    if fast:
        command.append("--fast")
    if rigorous:
        command.append("--rigorous")
    if quiet:
        command.append("--quiet")
    if track_memory:
        command.append("--track-memory")

    command.extend(
        [
            "--name",
            name,
            "--output",
            str(output),
            "--",
            sys.executable,
            str(PROFILE_SCRIPT),
            "run",
            target,
            "--iterations",
            str(iterations),
        ]
    )
    return tuple(command)


def _module_available(module_name: str) -> bool:
    """Return whether one Python module is importable in the current environment."""

    return importlib.util.find_spec(module_name) is not None


def _command_available(command_name: str) -> bool:
    """Return whether one executable is available on PATH."""

    return shutil.which(command_name) is not None


def _require_module(module_name: str) -> None:
    """Exit with one consistent message when a profiling dependency is missing."""

    if _module_available(module_name):
        return
    raise SystemExit(
        f"Missing optional dependency '{module_name}'. Run `uv sync --extra dev` and retry."
    )


def _handle_list_targets(_args: argparse.Namespace) -> int:
    """Print the supported profiling targets."""

    for name, spec in TARGETS.items():
        print(f"{name}: iterations={spec.default_iterations} - {spec.help}")
    return 0


def _handle_tools(_args: argparse.Namespace) -> int:
    """Print which profiling tools are available in the current environment."""

    tools = (
        ("pyinstrument", _module_available("pyinstrument")),
        ("pyperf", _module_available("pyperf")),
        ("py-spy", _command_available("py-spy")),
        ("perf", _command_available("perf")),
    )
    for tool_name, available in tools:
        status = "available" if available else "missing"
        print(f"{tool_name}: {status}")
    print(f"output-dir: {PROFILE_OUTPUT_DIR}")
    return 0


def _handle_run(args: argparse.Namespace) -> int:
    """Run one bounded target without extra profiling."""

    return run_target(args.target, iterations=args.iterations)


def _handle_cprofile(args: argparse.Namespace) -> int:
    """Run one bounded target under cProfile and dump a stats file."""

    output = _resolve_output_path(args.output, target=args.target, suffix=".prof")
    profiler = cProfile.Profile()
    exit_code = profiler.runcall(run_target, args.target, iterations=args.iterations)
    profiler.dump_stats(str(output))

    stats_stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stats_stream).strip_dirs().sort_stats(args.sort)
    stats.print_stats(args.top)
    print(stats_stream.getvalue(), end="")
    print(f"wrote cProfile stats to {output}")
    return int(exit_code)


def _handle_pyinstrument(args: argparse.Namespace) -> int:
    """Run one bounded target under pyinstrument."""

    _require_module("pyinstrument")
    from pyinstrument import Profiler

    suffix = ".html" if args.html else ".txt"
    output = _resolve_output_path(args.output, target=args.target, suffix=suffix)

    profiler = Profiler(interval=args.interval)
    profiler.start()
    exit_code = run_target(args.target, iterations=args.iterations)
    profiler.stop()

    if args.html:
        report = profiler.output_html()
    else:
        report = profiler.output_text()

    output.write_text(report, encoding="utf-8")
    if not args.html:
        print(report, end="" if report.endswith("\n") else "\n")
    print(f"wrote pyinstrument report to {output}")
    return exit_code


def _handle_pyperf(args: argparse.Namespace) -> int:
    """Run one bounded target through pyperf command benchmarking."""

    _require_module("pyperf")
    output = _resolve_output_path(args.output, target=args.target, suffix=".json")
    spec = TARGETS[args.target]
    command = build_pyperf_command(
        target=args.target,
        iterations=spec.default_iterations if args.iterations is None else args.iterations,
        name=args.name or args.target,
        output=output,
        fast=args.fast,
        rigorous=args.rigorous,
        track_memory=args.track_memory,
        quiet=args.quiet,
    )
    print("running:", " ".join(command))
    completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if completed.returncode == 0:
        print(f"wrote pyperf benchmark to {output}")
    return completed.returncode


def build_parser() -> argparse.ArgumentParser:
    """Create the profiling command parser."""

    parser = argparse.ArgumentParser(description="Run repo-owned YoYoPod profiling helpers.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_targets_parser = subparsers.add_parser(
        "list-targets",
        help="List the bounded profiling targets.",
    )
    list_targets_parser.set_defaults(handler=_handle_list_targets)

    tools_parser = subparsers.add_parser(
        "tools",
        help="Show which profiling tools are available in this environment.",
    )
    tools_parser.set_defaults(handler=_handle_tools)

    run_parser = subparsers.add_parser(
        "run",
        help="Run one bounded target without extra profiling.",
    )
    run_parser.add_argument("target", choices=tuple(TARGETS))
    run_parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Override the target's default loop count when applicable.",
    )
    run_parser.set_defaults(handler=_handle_run)

    cprofile_parser = subparsers.add_parser(
        "cprofile",
        help="Profile one bounded target with cProfile.",
    )
    cprofile_parser.add_argument("target", choices=tuple(TARGETS))
    cprofile_parser.add_argument("--iterations", type=int, default=None)
    cprofile_parser.add_argument(
        "--output",
        default="",
        help="Write the .prof file here. Default: logs/profiles/<target>.prof",
    )
    cprofile_parser.add_argument(
        "--sort",
        default="cumulative",
        help="Stats sort key passed to pstats. Default: cumulative",
    )
    cprofile_parser.add_argument(
        "--top",
        type=int,
        default=30,
        help="Print this many top cProfile rows. Default: 30",
    )
    cprofile_parser.set_defaults(handler=_handle_cprofile)

    pyinstrument_parser = subparsers.add_parser(
        "pyinstrument",
        help="Profile one bounded target with pyinstrument.",
    )
    pyinstrument_parser.add_argument("target", choices=tuple(TARGETS))
    pyinstrument_parser.add_argument("--iterations", type=int, default=None)
    pyinstrument_parser.add_argument(
        "--output",
        default="",
        help="Write the report here. Default: logs/profiles/<target>.txt|.html",
    )
    pyinstrument_parser.add_argument(
        "--interval",
        type=float,
        default=0.001,
        help="Sampling interval in seconds. Default: 0.001",
    )
    pyinstrument_parser.add_argument(
        "--html",
        action="store_true",
        help="Write an HTML report instead of plain text.",
    )
    pyinstrument_parser.set_defaults(handler=_handle_pyinstrument)

    pyperf_parser = subparsers.add_parser(
        "pyperf",
        help="Benchmark one bounded target with pyperf command.",
    )
    pyperf_parser.add_argument("target", choices=tuple(TARGETS))
    pyperf_parser.add_argument("--iterations", type=int, default=None)
    pyperf_parser.add_argument(
        "--output",
        default="",
        help="Write the JSON benchmark file here. Default: logs/profiles/<target>.json",
    )
    pyperf_parser.add_argument(
        "--name",
        default="",
        help="Optional benchmark name. Default: target name",
    )
    pyperf_mode = pyperf_parser.add_mutually_exclusive_group()
    pyperf_mode.add_argument("--fast", action="store_true", help="Use pyperf fast mode.")
    pyperf_mode.add_argument(
        "--rigorous",
        action="store_true",
        help="Use pyperf rigorous mode.",
    )
    pyperf_parser.add_argument(
        "--track-memory",
        action="store_true",
        help="Benchmark peak RSS instead of elapsed time.",
    )
    pyperf_parser.add_argument(
        "--quiet",
        action="store_true",
        help="Hide pyperf stability warnings in the command output.",
    )
    pyperf_parser.set_defaults(handler=_handle_pyperf)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Script entry point."""

    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
