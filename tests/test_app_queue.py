"""Tests for coordinator-thread event dispatch in YoyoPodApp."""

import threading

from yoyopy.app import YoyoPodApp


def test_main_thread_action_runs_immediately() -> None:
    """Callbacks scheduled on the coordinator thread should run inline."""
    app = YoyoPodApp(simulate=True)
    seen_thread_ids: list[int] = []

    app._run_on_main_thread(
        "immediate action",
        lambda: seen_thread_ids.append(threading.get_ident()),
    )

    assert seen_thread_ids == [app._main_thread_id]
    assert app._process_pending_main_thread_actions() == 0


def test_background_thread_action_is_queued_until_drained() -> None:
    """Callbacks from worker threads should wait for the main loop to drain them."""
    app = YoyoPodApp(simulate=True)
    seen_thread_ids: list[int] = []

    def worker() -> None:
        app._run_on_main_thread(
            "queued action",
            lambda: seen_thread_ids.append(threading.get_ident()),
        )

    worker_thread = threading.Thread(target=worker)
    worker_thread.start()
    worker_thread.join()

    assert seen_thread_ids == []
    assert app._process_pending_main_thread_actions() == 1
    assert seen_thread_ids == [app._main_thread_id]
