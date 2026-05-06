"""Tests for the scaffold main-thread scheduler."""

from __future__ import annotations

import threading

from yoyopod.core import MainThreadScheduler


def test_scheduler_runs_immediately_on_main_thread() -> None:
    scheduler = MainThreadScheduler()
    seen: list[str] = []

    scheduler.run_on_main(lambda: seen.append("inline"))

    assert seen == ["inline"]
    assert scheduler.pending_count() == 0


def test_scheduler_queues_background_work_until_drain() -> None:
    scheduler = MainThreadScheduler()
    seen: list[str] = []

    worker = threading.Thread(target=lambda: scheduler.run_on_main(lambda: seen.append("queued")))
    worker.start()
    worker.join()

    assert seen == []
    assert scheduler.pending_count() == 1
    assert scheduler.drain() == 1
    assert seen == ["queued"]


def test_scheduler_post_queues_main_thread_work_until_drain() -> None:
    scheduler = MainThreadScheduler()
    seen: list[str] = []

    scheduler.post(lambda: seen.append("queued"))

    assert seen == []
    assert scheduler.pending_count() == 1
    assert scheduler.drain() == 1
    assert seen == ["queued"]


def test_scheduler_logs_and_continues_after_task_failure() -> None:
    scheduler = MainThreadScheduler()
    seen: list[str] = []

    scheduler.post(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    scheduler.post(lambda: seen.append("after"))

    assert scheduler.drain() == 2
    assert seen == ["after"]
