"""Central background-work executor for off-thread I/O and subprocess operations.

Five named `ThreadPoolExecutor` pools (`io`, `media`, `subprocess`, `watchdog`,
`power`) run blocking work off the coordinator thread, and a registry of
long-running poller threads provides centralized shutdown discipline. All
Future results return to the coordinator via :meth:`MainThreadScheduler.post`
so call sites never touch threading primitives directly.

Pool semantics:

- ``io`` — short HTTP/socket I/O including cloud control-plane work (auth,
  token refresh, config sync, MQTT) and network polling.
- ``media`` — long-running cloud media downloads (e.g. ``store_media`` and
  remote playback asset fetch); kept off ``io`` so a burst of bytes-heavy
  jobs cannot starve the latency-sensitive control-plane.
- ``subprocess`` — process lifecycle and shell-outs.
- ``watchdog`` — PiSugar watchdog feed; safety-critical, must never wait
  behind cloud work.
- ``power`` — PiSugar battery refresh feeding ``PowerSafetyPolicy.evaluate``;
  safety-relevant, kept off ``io`` for the same reason.
"""

from __future__ import annotations

import concurrent.futures.thread as _cf_thread
import threading
import time
import weakref
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Protocol, TypeVar

from loguru import logger


class _DaemonThreadPoolExecutor(ThreadPoolExecutor):
    """``ThreadPoolExecutor`` whose workers are daemon and skip the atexit join.

    Stdlib ``ThreadPoolExecutor`` creates **non-daemon** worker threads and
    registers them in ``concurrent.futures.thread._threads_queues``; the
    interpreter's ``_python_exit`` atexit hook unconditionally calls
    ``Thread.join()`` on every registered worker. A stuck submitted task
    (e.g. a hung HTTP/I2C call without a per-call timeout) therefore blocks
    process termination *even after* :meth:`BackgroundExecutor.shutdown` has
    returned within its bounded timeout.

    This subclass overrides the private ``_adjust_thread_count`` hook to:

    1. Spawn workers with ``daemon=True`` so the interpreter does not wait
       on them in its non-daemon-thread join phase.
    2. Skip registration in ``_threads_queues`` so ``_python_exit`` does
       not call ``join()`` on stuck workers at interpreter exit.

    The body mirrors CPython's stock ``_adjust_thread_count`` exactly except
    for those two changes; if the stdlib internal layout shifts in a future
    Python release, this class needs revisiting.
    """

    def _adjust_thread_count(self) -> None:  # type: ignore[override]
        if self._idle_semaphore.acquire(timeout=0):
            return

        def weakref_cb(_: Any, q: Any = self._work_queue) -> None:
            q.put(None)

        num_threads = len(self._threads)
        if num_threads < self._max_workers:
            thread_name = f"{self._thread_name_prefix or self}_{num_threads}"
            t = threading.Thread(
                name=thread_name,
                target=_cf_thread._worker,  # type: ignore[attr-defined]
                args=(
                    weakref.ref(self, weakref_cb),
                    self._work_queue,
                    self._initializer,
                    self._initargs,
                ),
                daemon=True,
            )
            t.start()
            self._threads.add(t)
            # Intentionally NOT added to ``_cf_thread._threads_queues`` — see class docstring.


class _Scheduler(Protocol):
    def post(self, fn: Callable[[], None]) -> None:
        """Queue a callback for main-thread drain."""


class _DiagnosticsLog(Protocol):
    def append(self, entry: Any) -> None:
        """Append one diagnostics entry."""


_T = TypeVar("_T")
_DEFAULT_IO_WORKERS = 4
_DEFAULT_MEDIA_WORKERS = 2
_DEFAULT_SUBPROCESS_WORKERS = 2
_DEFAULT_WATCHDOG_WORKERS = 1
_DEFAULT_POWER_WORKERS = 1
_DEFAULT_SHUTDOWN_TIMEOUT_SECONDS = 5.0


@dataclass(slots=True)
class _LongRunningEntry:
    """One registered long-running thread joined by :meth:`BackgroundExecutor.shutdown`."""

    name: str
    thread: threading.Thread


class BackgroundPool:
    """Wrap one `ThreadPoolExecutor` with a coordinator-thread result-delivery helper."""

    def __init__(
        self,
        *,
        executor: ThreadPoolExecutor,
        scheduler: _Scheduler,
        diagnostics_log: _DiagnosticsLog | None,
        pool_name: str,
    ) -> None:
        self._executor = executor
        self._scheduler = scheduler
        self._diagnostics_log = diagnostics_log
        self._pool_name = pool_name

    def submit(self, fn: Callable[..., _T], *args: Any, **kwargs: Any) -> Future[_T]:
        """Submit work to the pool; the caller owns the returned `Future`."""

        return self._executor.submit(fn, *args, **kwargs)

    def submit_and_post(
        self,
        fn: Callable[..., _T],
        *args: Any,
        on_done: Callable[[Future[_T]], None],
        **kwargs: Any,
    ) -> Future[_T]:
        """Submit work and deliver the completed `Future` back via the main-thread scheduler."""

        future = self._executor.submit(fn, *args, **kwargs)
        future.add_done_callback(self._build_post_callback(fn, on_done))
        return future

    def _set_diagnostics_log(self, diagnostics_log: _DiagnosticsLog | None) -> None:
        """Replace the diagnostics sink for this pool."""

        self._diagnostics_log = diagnostics_log

    def _build_post_callback(
        self,
        fn: Callable[..., Any],
        on_done: Callable[[Future[Any]], None],
    ) -> Callable[[Future[Any]], None]:
        """Return a Future done-callback that posts the handler onto the main thread."""

        def _post(future: Future[Any]) -> None:
            self._scheduler.post(lambda: self._invoke_handler(fn, future, on_done))

        return _post

    def _invoke_handler(
        self,
        fn: Callable[..., Any],
        future: Future[Any],
        on_done: Callable[[Future[Any]], None],
    ) -> None:
        """Run the completion handler on the main thread, recording any failures.

        Completion handlers may be invoked with a *cancelled* future when
        :meth:`BackgroundExecutor.shutdown` aborts queued work via
        ``cancel_futures=True``; handlers should check ``future.cancelled()``
        before calling ``future.result()`` to avoid ``CancelledError``. The
        handler is still invoked on cancellation so callers can release
        in-flight flags (e.g. ``_power_refresh_in_flight``).
        """

        if future.cancelled():
            # Calling future.exception() on a cancelled future raises
            # CancelledError; short-circuit and record a low-severity
            # diagnostic instead, then still run on_done for cleanup.
            self._record_cancellation(fn=fn)
        else:
            background_exc = future.exception()
            if background_exc is not None:
                self._record_error(
                    kind="background_error",
                    fn=fn,
                    exc=background_exc,
                )
                logger.opt(exception=background_exc).error(
                    "Background work failed in pool {!r}: {}",
                    self._pool_name,
                    _callable_name(fn),
                )
        try:
            on_done(future)
        except Exception as exc:
            self._record_error(
                kind="background_completion_error",
                fn=fn,
                exc=exc,
            )
            logger.exception(
                "Background completion handler for {} failed",
                _callable_name(fn),
            )

    def _record_cancellation(self, *, fn: Callable[..., Any]) -> None:
        """Record one low-severity ``background_cancelled`` diagnostic entry."""

        if self._diagnostics_log is None:
            return
        self._diagnostics_log.append(
            {
                "kind": "background_cancelled",
                "pool": self._pool_name,
                "handler": _callable_name(fn),
            }
        )

    def _record_error(
        self,
        *,
        kind: str,
        fn: Callable[..., Any],
        exc: BaseException,
    ) -> None:
        """Append one background-error entry to the diagnostics sink when present."""

        if self._diagnostics_log is None:
            return
        self._diagnostics_log.append(
            {
                "kind": kind,
                "pool": self._pool_name,
                "handler": _callable_name(fn),
                "exc": f"{exc.__class__.__name__}: {exc}",
            }
        )


class BackgroundExecutor:
    """Owns named background pools and registered long-running poller threads."""

    def __init__(
        self,
        scheduler: _Scheduler,
        *,
        diagnostics_log: _DiagnosticsLog | None = None,
        io_workers: int = _DEFAULT_IO_WORKERS,
        media_workers: int = _DEFAULT_MEDIA_WORKERS,
        subprocess_workers: int = _DEFAULT_SUBPROCESS_WORKERS,
        watchdog_workers: int = _DEFAULT_WATCHDOG_WORKERS,
        power_workers: int = _DEFAULT_POWER_WORKERS,
    ) -> None:
        self._scheduler = scheduler
        self._diagnostics_log = diagnostics_log
        self._io_executor = _DaemonThreadPoolExecutor(
            max_workers=io_workers, thread_name_prefix="yp-io"
        )
        self._media_executor = _DaemonThreadPoolExecutor(
            max_workers=media_workers, thread_name_prefix="yp-media"
        )
        self._subprocess_executor = _DaemonThreadPoolExecutor(
            max_workers=subprocess_workers, thread_name_prefix="yp-sub"
        )
        self._watchdog_executor = _DaemonThreadPoolExecutor(
            max_workers=watchdog_workers, thread_name_prefix="yp-wd"
        )
        self._power_executor = _DaemonThreadPoolExecutor(
            max_workers=power_workers, thread_name_prefix="yp-pwr"
        )
        self.io = BackgroundPool(
            executor=self._io_executor,
            scheduler=scheduler,
            diagnostics_log=diagnostics_log,
            pool_name="io",
        )
        self.media = BackgroundPool(
            executor=self._media_executor,
            scheduler=scheduler,
            diagnostics_log=diagnostics_log,
            pool_name="media",
        )
        self.subprocess = BackgroundPool(
            executor=self._subprocess_executor,
            scheduler=scheduler,
            diagnostics_log=diagnostics_log,
            pool_name="subprocess",
        )
        self.watchdog = BackgroundPool(
            executor=self._watchdog_executor,
            scheduler=scheduler,
            diagnostics_log=diagnostics_log,
            pool_name="watchdog",
        )
        self.power = BackgroundPool(
            executor=self._power_executor,
            scheduler=scheduler,
            diagnostics_log=diagnostics_log,
            pool_name="power",
        )
        self._long_running: list[_LongRunningEntry] = []
        self._shutdown = False
        self._shutdown_lock = threading.Lock()

    def register_long_running(
        self,
        thread: threading.Thread,
        *,
        name: str,
    ) -> None:
        """Register a poller thread for centralized shutdown discipline."""

        with self._shutdown_lock:
            if self._shutdown:
                raise RuntimeError(
                    f"Cannot register long-running thread {name!r}: "
                    "BackgroundExecutor already shut down"
                )
            self._long_running.append(_LongRunningEntry(name=name, thread=thread))

    def set_diagnostics_log(self, diagnostics_log: _DiagnosticsLog | None) -> None:
        """Attach or clear the diagnostics sink and propagate to managed pools."""

        self._diagnostics_log = diagnostics_log
        self.io._set_diagnostics_log(diagnostics_log)
        self.media._set_diagnostics_log(diagnostics_log)
        self.subprocess._set_diagnostics_log(diagnostics_log)
        self.watchdog._set_diagnostics_log(diagnostics_log)
        self.power._set_diagnostics_log(diagnostics_log)

    def long_running_thread_names(self) -> list[str]:
        """Return the names of currently registered long-running threads."""

        with self._shutdown_lock:
            return [entry.name for entry in self._long_running]

    def is_shutdown(self) -> bool:
        """Return whether :meth:`shutdown` has already been called."""

        with self._shutdown_lock:
            return self._shutdown

    def shutdown(self, *, timeout: float = _DEFAULT_SHUTDOWN_TIMEOUT_SECONDS) -> None:
        """Cancel pending Futures, bound-wait pool drain, and join long-running threads.

        Total time is bounded by ``timeout``: each pool is shut down via a daemon
        helper thread so a stuck in-flight task cannot block shutdown indefinitely.
        Pending futures are cancelled; running tasks continue in their daemon worker
        threads (which die with the process if the wait times out).
        """

        with self._shutdown_lock:
            if self._shutdown:
                return
            self._shutdown = True
            entries = list(self._long_running)

        deadline = time.monotonic() + max(0.0, timeout)
        self._shutdown_pool_bounded(self._io_executor, "io", deadline)
        self._shutdown_pool_bounded(self._media_executor, "media", deadline)
        self._shutdown_pool_bounded(self._subprocess_executor, "subprocess", deadline)
        self._shutdown_pool_bounded(self._watchdog_executor, "watchdog", deadline)
        self._shutdown_pool_bounded(self._power_executor, "power", deadline)
        for entry in entries:
            remaining = max(0.0, deadline - time.monotonic())
            entry.thread.join(timeout=remaining)
            if entry.thread.is_alive():
                logger.warning(
                    "Long-running background thread {!r} did not exit within shutdown budget",
                    entry.name,
                )

    def _shutdown_pool_bounded(
        self,
        executor: ThreadPoolExecutor,
        name: str,
        deadline: float,
    ) -> None:
        """Shut one pool down with a bounded wait against the shared deadline."""

        waiter = threading.Thread(
            target=lambda: executor.shutdown(wait=True, cancel_futures=True),
            daemon=True,
            name=f"yp-{name}-shutdown",
        )
        waiter.start()
        remaining = max(0.0, deadline - time.monotonic())
        waiter.join(timeout=remaining)
        if waiter.is_alive():
            logger.warning(
                "Background pool {!r} did not finish shutdown within budget; "
                "in-flight tasks may still be running",
                name,
            )


def _callable_name(fn: Callable[..., Any]) -> str:
    """Return a stable identifier for a callable used in diagnostics entries."""

    module = getattr(fn, "__module__", "") or ""
    qualname = getattr(fn, "__qualname__", getattr(fn, "__name__", repr(fn)))
    return f"{module}.{qualname}".strip(".")
