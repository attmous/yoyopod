"""Tests for the central :class:`BackgroundExecutor` and its named pools."""

from __future__ import annotations

import concurrent.futures.thread as _cf_thread
import threading
import time
from concurrent.futures import Future
from typing import Any

import pytest

from yoyopod.core.background import BackgroundExecutor
from yoyopod.core.scheduler import MainThreadScheduler


def _wait_for_pending(scheduler: MainThreadScheduler, *, timeout_seconds: float = 2.0) -> None:
    """Wait until the scheduler has at least one pending main-thread callback."""

    deadline = time.monotonic() + timeout_seconds
    while scheduler.pending_count() == 0 and time.monotonic() < deadline:
        time.sleep(0.005)


def test_submit_and_post_delivers_result_via_scheduler() -> None:
    scheduler = MainThreadScheduler()
    executor = BackgroundExecutor(scheduler)
    seen: list[str] = []

    future = executor.io.submit_and_post(
        lambda: "ok",
        on_done=lambda fut: seen.append(fut.result()),
    )
    future.result(timeout=2.0)

    _wait_for_pending(scheduler)
    assert scheduler.drain() >= 1
    assert seen == ["ok"]

    executor.shutdown()


def test_submit_and_post_records_background_exception() -> None:
    scheduler = MainThreadScheduler()
    diagnostics: list[dict[str, Any]] = []
    executor = BackgroundExecutor(scheduler, diagnostics_log=diagnostics)

    def boom() -> None:
        raise RuntimeError("kaboom")

    future = executor.io.submit_and_post(boom, on_done=lambda fut: None)

    with pytest.raises(RuntimeError, match="kaboom"):
        future.result(timeout=2.0)

    _wait_for_pending(scheduler)
    scheduler.drain()

    matching = [entry for entry in diagnostics if entry["kind"] == "background_error"]
    assert matching, f"no background_error entry recorded; saw {diagnostics}"
    assert matching[0]["pool"] == "io"
    assert "kaboom" in matching[0]["exc"]

    executor.shutdown()


def test_submit_and_post_records_completion_handler_exception() -> None:
    scheduler = MainThreadScheduler()
    diagnostics: list[dict[str, Any]] = []
    executor = BackgroundExecutor(scheduler, diagnostics_log=diagnostics)

    def handler(_fut: Future[int]) -> None:
        raise ValueError("handler boom")

    future = executor.io.submit_and_post(lambda: 42, on_done=handler)
    future.result(timeout=2.0)

    _wait_for_pending(scheduler)
    scheduler.drain()

    matching = [entry for entry in diagnostics if entry["kind"] == "background_completion_error"]
    assert matching, f"no completion_error entry recorded; saw {diagnostics}"
    assert "handler boom" in matching[0]["exc"]

    executor.shutdown()


def test_submit_returns_future_without_post_callback() -> None:
    scheduler = MainThreadScheduler()
    executor = BackgroundExecutor(scheduler)

    future = executor.io.submit(lambda: 99)
    assert future.result(timeout=2.0) == 99
    assert scheduler.pending_count() == 0

    executor.shutdown()


def test_register_long_running_records_and_joins_on_shutdown() -> None:
    scheduler = MainThreadScheduler()
    executor = BackgroundExecutor(scheduler)
    stop_event = threading.Event()

    def loop() -> None:
        while not stop_event.is_set():
            time.sleep(0.01)

    thread = threading.Thread(target=loop, daemon=True, name="poller-test")
    thread.start()
    executor.register_long_running(thread, name="poller-test")

    assert "poller-test" in executor.long_running_thread_names()

    stop_event.set()
    executor.shutdown(timeout=1.0)

    assert not thread.is_alive()


def test_shutdown_returns_when_long_running_thread_misses_timeout() -> None:
    scheduler = MainThreadScheduler()
    executor = BackgroundExecutor(scheduler)
    release_event = threading.Event()

    def loop() -> None:
        # Wait longer than the shutdown timeout to force the join to time out.
        release_event.wait(timeout=2.0)

    thread = threading.Thread(target=loop, daemon=True, name="stuck-poller")
    thread.start()
    executor.register_long_running(thread, name="stuck-poller")

    started_at = time.monotonic()
    executor.shutdown(timeout=0.1)
    elapsed = time.monotonic() - started_at
    assert elapsed < 1.0  # shutdown should not block for the full thread duration

    release_event.set()
    thread.join(timeout=2.0)


def test_shutdown_completes_within_timeout_when_pool_task_blocks() -> None:
    """Shutdown must honor its timeout even when an in-flight pool task blocks indefinitely."""

    scheduler = MainThreadScheduler()
    executor = BackgroundExecutor(scheduler, io_workers=1)
    io_started = threading.Event()
    io_release = threading.Event()

    def slow_io() -> None:
        io_started.set()
        # Hold for far longer than the shutdown budget; released in cleanup below.
        io_release.wait(timeout=5.0)

    executor.io.submit(slow_io)
    assert io_started.wait(timeout=1.0), "io task did not start before shutdown"

    started_at = time.monotonic()
    executor.shutdown(timeout=0.1)
    elapsed = time.monotonic() - started_at
    # Without the bounded-shutdown helper, this would block on the running task
    # (cancel_futures only cancels queued work) and elapsed would be ~5s.
    assert elapsed < 1.0, f"shutdown took {elapsed:.2f}s, expected within budget"

    # Cleanup: let the daemon worker exit so it does not linger across tests.
    io_release.set()


def test_shutdown_is_idempotent() -> None:
    scheduler = MainThreadScheduler()
    executor = BackgroundExecutor(scheduler)
    executor.shutdown()
    executor.shutdown()
    assert executor.is_shutdown() is True


def test_register_after_shutdown_raises() -> None:
    scheduler = MainThreadScheduler()
    executor = BackgroundExecutor(scheduler)
    executor.shutdown()

    thread = threading.Thread(target=lambda: None, daemon=True)
    with pytest.raises(RuntimeError, match="already shut down"):
        executor.register_long_running(thread, name="late")


def test_set_diagnostics_log_propagates_to_pools() -> None:
    scheduler = MainThreadScheduler()
    executor = BackgroundExecutor(scheduler)
    diagnostics: list[dict[str, Any]] = []
    executor.set_diagnostics_log(diagnostics)

    def boom() -> None:
        raise RuntimeError("late-attached")

    future = executor.io.submit_and_post(boom, on_done=lambda fut: None)
    with pytest.raises(RuntimeError):
        future.result(timeout=2.0)

    _wait_for_pending(scheduler)
    scheduler.drain()

    assert any("late-attached" in entry["exc"] for entry in diagnostics)

    executor.shutdown()


def test_set_diagnostics_log_propagates_to_watchdog_pool() -> None:
    """Diagnostics sink must reach the dedicated watchdog pool too."""

    scheduler = MainThreadScheduler()
    executor = BackgroundExecutor(scheduler)
    diagnostics: list[dict[str, Any]] = []
    executor.set_diagnostics_log(diagnostics)

    def boom() -> None:
        raise RuntimeError("watchdog-attached")

    future = executor.watchdog.submit_and_post(boom, on_done=lambda fut: None)
    with pytest.raises(RuntimeError):
        future.result(timeout=2.0)

    _wait_for_pending(scheduler)
    scheduler.drain()

    matching = [
        entry
        for entry in diagnostics
        if entry["pool"] == "watchdog" and "watchdog-attached" in entry["exc"]
    ]
    assert matching, f"no watchdog-pool error recorded; saw {diagnostics}"

    executor.shutdown()


def test_subprocess_pool_isolated_from_io_pool() -> None:
    scheduler = MainThreadScheduler()
    executor = BackgroundExecutor(scheduler, io_workers=1, subprocess_workers=1)
    io_started = threading.Event()
    io_release = threading.Event()

    def slow_io() -> None:
        io_started.set()
        io_release.wait(timeout=2.0)

    # Saturate the io pool with a long-blocked task.
    blocker = executor.io.submit(slow_io)
    assert io_started.wait(timeout=1.0)

    # Subprocess pool should still process work in parallel.
    sub_done = executor.subprocess.submit(lambda: "sub-ok")
    assert sub_done.result(timeout=1.0) == "sub-ok"

    io_release.set()
    blocker.result(timeout=2.0)
    executor.shutdown()


def test_watchdog_pool_isolated_from_io_pool() -> None:
    """Watchdog feeds must run on workers that cloud/io work cannot saturate."""

    scheduler = MainThreadScheduler()
    executor = BackgroundExecutor(scheduler, io_workers=1)
    io_started = threading.Event()
    io_release = threading.Event()

    def slow_io() -> None:
        io_started.set()
        io_release.wait(timeout=2.0)

    # Saturate the io pool with a long-blocked task that mirrors a stuck
    # CloudManager HTTP call.
    blocker = executor.io.submit(slow_io)
    assert io_started.wait(timeout=1.0)

    # The watchdog pool must run independently and complete promptly.
    wd_done = executor.watchdog.submit(lambda: "wd-ok")
    assert wd_done.result(timeout=1.0) == "wd-ok"

    io_release.set()
    blocker.result(timeout=2.0)
    executor.shutdown()


def test_pool_workers_are_daemon_and_skip_atexit_registry() -> None:
    """Workers must be daemon and not registered in ``_threads_queues``.

    Stdlib ``ThreadPoolExecutor`` workers are non-daemon and joined by Python's
    ``concurrent.futures.thread._python_exit`` atexit hook. Either condition
    can extend process termination beyond the bounded ``shutdown(timeout=...)``
    when an in-flight task is stuck.
    """

    scheduler = MainThreadScheduler()
    executor = BackgroundExecutor(scheduler, io_workers=1, subprocess_workers=1)

    # Materialize at least one worker per pool by running one task each.
    executor.io.submit(lambda: None).result(timeout=2.0)
    executor.media.submit(lambda: None).result(timeout=2.0)
    executor.subprocess.submit(lambda: None).result(timeout=2.0)
    executor.watchdog.submit(lambda: None).result(timeout=2.0)
    executor.power.submit(lambda: None).result(timeout=2.0)

    pools_to_check = [
        ("io", executor._io_executor),
        ("media", executor._media_executor),
        ("subprocess", executor._subprocess_executor),
        ("watchdog", executor._watchdog_executor),
        ("power", executor._power_executor),
    ]
    for name, pool_executor in pools_to_check:
        threads = list(pool_executor._threads)
        assert threads, f"{name} pool spawned no workers"
        for t in threads:
            assert t.daemon, f"{name} worker {t.name!r} is not daemon"
            assert t not in _cf_thread._threads_queues, (  # type: ignore[attr-defined]
                f"{name} worker {t.name!r} is registered in "
                "concurrent.futures.thread._threads_queues; atexit would join "
                "it and may hang on stuck tasks"
            )

    executor.shutdown()


def test_power_pool_isolated_from_io_pool() -> None:
    """Power refresh must run on workers that cloud/io work cannot saturate.

    PowerRuntimeService gates new refreshes on `_power_refresh_in_flight`. If
    the io pool is saturated by CloudManager work, a queued refresh stalls and
    no new refreshes are scheduled, delaying ``PowerSafetyPolicy.evaluate``
    (low-battery warnings, shutdown decisions).
    """

    scheduler = MainThreadScheduler()
    executor = BackgroundExecutor(scheduler, io_workers=1)
    io_started = threading.Event()
    io_release = threading.Event()

    def slow_io() -> None:
        io_started.set()
        io_release.wait(timeout=2.0)

    blocker = executor.io.submit(slow_io)
    assert io_started.wait(timeout=1.0)

    pwr_done = executor.power.submit(lambda: "pwr-ok")
    assert pwr_done.result(timeout=1.0) == "pwr-ok"

    io_release.set()
    blocker.result(timeout=2.0)
    executor.shutdown()


def test_submit_after_shutdown_returns_cancelled_future_without_raising() -> None:
    """Late submissions during shutdown must not raise ``RuntimeError``.

    Cloud completion handlers (e.g. ``_complete_fetch_remote_config`` ->
    ``_maybe_bootstrap_local_contacts`` -> ``_start_worker``) can fire on the
    scheduler during shutdown drain. A closed ``ThreadPoolExecutor`` would
    raise ``RuntimeError`` on submit; the pool must instead drop the work,
    log it, and return a cancelled Future.
    """

    scheduler = MainThreadScheduler()
    executor = BackgroundExecutor(scheduler)
    executor.shutdown()

    future = executor.io.submit(lambda: "should-not-run")
    assert future.cancelled(), "post-shutdown submit must return a cancelled Future"

    # And the same for every other named pool (they all share the wrapper).
    for pool in (executor.media, executor.subprocess, executor.watchdog, executor.power):
        f = pool.submit(lambda: "x")
        assert f.cancelled()


def test_submit_and_post_after_shutdown_still_invokes_on_done() -> None:
    """submit_and_post during shutdown must run on_done so callers can clean up.

    Caller cleanup (e.g. clearing ``_request_in_flight``, ``_power_refresh_in_flight``)
    lives in on_done. If late submissions silently dropped without firing
    on_done, in-flight bookkeeping would be stuck on True forever.
    """

    scheduler = MainThreadScheduler()
    diagnostics: list[dict[str, Any]] = []
    executor = BackgroundExecutor(scheduler, diagnostics_log=diagnostics)
    executor.shutdown()

    cleanup_called: list[bool] = []

    def on_done(_fut: Future[Any]) -> None:
        cleanup_called.append(True)

    future = executor.io.submit_and_post(lambda: "x", on_done=on_done)
    assert future.cancelled()

    _wait_for_pending(scheduler, timeout_seconds=2.0)
    scheduler.drain()

    assert cleanup_called == [True], "on_done was not invoked for post-shutdown submit"

    cancelled_entries = [e for e in diagnostics if e.get("kind") == "background_cancelled"]
    assert cancelled_entries, f"no background_cancelled entry; saw {diagnostics}"


def test_invoke_handler_runs_on_done_on_cancelled_future_without_crashing() -> None:
    """Cancelled queued futures must not crash ``_invoke_handler``.

    Without the cancellation guard, ``_invoke_handler`` calls
    ``future.exception()`` which raises ``CancelledError`` on cancelled
    futures. The scheduler logs a generic task error and ``on_done``
    (which holds caller cleanup logic such as clearing
    ``_power_refresh_in_flight``) never runs.
    """

    scheduler = MainThreadScheduler()
    diagnostics: list[dict[str, Any]] = []
    # io_workers=1 lets us saturate with one blocker and queue a cancellable task.
    executor = BackgroundExecutor(scheduler, io_workers=1, diagnostics_log=diagnostics)

    block_started = threading.Event()
    block_release = threading.Event()

    def slow_blocker() -> None:
        block_started.set()
        block_release.wait(timeout=5.0)

    blocker = executor.io.submit(slow_blocker)
    assert block_started.wait(timeout=1.0)

    cleanup_called: list[bool] = []

    def on_done(_fut: Future[Any]) -> None:
        cleanup_called.append(True)

    queued = executor.io.submit_and_post(lambda: "never-runs", on_done=on_done)
    assert queued.cancel(), "queued future should still be cancellable"
    assert queued.cancelled()

    _wait_for_pending(scheduler, timeout_seconds=2.0)
    scheduler.drain()

    # on_done must run for cancelled futures — that's where caller cleanup lives.
    assert cleanup_called == [True], "on_done was not invoked for cancelled future"

    # Diagnostics record cancellation as a distinct kind, not a generic crash.
    cancelled_entries = [e for e in diagnostics if e.get("kind") == "background_cancelled"]
    assert cancelled_entries, f"no background_cancelled entry recorded; saw {diagnostics}"
    assert cancelled_entries[0]["pool"] == "io"

    # No spurious background_error or background_completion_error.
    assert not any(
        e.get("kind") in {"background_error", "background_completion_error"}
        for e in diagnostics
    ), f"unexpected error entry recorded: {diagnostics}"

    block_release.set()
    blocker.result(timeout=2.0)
    executor.shutdown()


def test_set_diagnostics_log_propagates_to_power_pool() -> None:
    """Diagnostics sink must reach the dedicated power pool too."""

    scheduler = MainThreadScheduler()
    executor = BackgroundExecutor(scheduler)
    diagnostics: list[dict[str, Any]] = []
    executor.set_diagnostics_log(diagnostics)

    def boom() -> None:
        raise RuntimeError("power-attached")

    future = executor.power.submit_and_post(boom, on_done=lambda fut: None)
    with pytest.raises(RuntimeError):
        future.result(timeout=2.0)

    _wait_for_pending(scheduler)
    scheduler.drain()

    matching = [
        entry
        for entry in diagnostics
        if entry["pool"] == "power" and "power-attached" in entry["exc"]
    ]
    assert matching, f"no power-pool error recorded; saw {diagnostics}"

    executor.shutdown()


def test_set_diagnostics_log_propagates_to_media_pool() -> None:
    """Diagnostics sink must reach the dedicated media pool too."""

    scheduler = MainThreadScheduler()
    executor = BackgroundExecutor(scheduler)
    diagnostics: list[dict[str, Any]] = []
    executor.set_diagnostics_log(diagnostics)

    def boom() -> None:
        raise RuntimeError("media-attached")

    future = executor.media.submit_and_post(boom, on_done=lambda fut: None)
    with pytest.raises(RuntimeError):
        future.result(timeout=2.0)

    _wait_for_pending(scheduler)
    scheduler.drain()

    matching = [
        entry
        for entry in diagnostics
        if entry["pool"] == "media" and "media-attached" in entry["exc"]
    ]
    assert matching, f"no media-pool error recorded; saw {diagnostics}"

    executor.shutdown()


def test_media_pool_isolated_from_io_pool() -> None:
    """A long-running media download must not delay control-plane io work.

    Cloud control-plane calls (auth, token refresh, config sync) gate on
    ``_request_in_flight``. If media downloads share the io pool, a queued
    auth task can sit behind store_media bytes and stall token refresh in
    production.
    """

    scheduler = MainThreadScheduler()
    executor = BackgroundExecutor(scheduler, media_workers=1)
    media_started = threading.Event()
    media_release = threading.Event()

    def slow_media() -> None:
        media_started.set()
        media_release.wait(timeout=2.0)

    blocker = executor.media.submit(slow_media)
    assert media_started.wait(timeout=1.0)

    # io control-plane must remain responsive while media is busy.
    io_done = executor.io.submit(lambda: "io-ok")
    assert io_done.result(timeout=1.0) == "io-ok"

    media_release.set()
    blocker.result(timeout=2.0)
    executor.shutdown()
