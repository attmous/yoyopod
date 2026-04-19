"""Loop cadence decision helpers for RuntimeLoopService."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from yoyopod.utils.logger import get_subsystem_logger

if TYPE_CHECKING:
    from yoyopod.runtime.loop import RuntimeLoopService


coord_logger = get_subsystem_logger("coord")


@dataclass(frozen=True, slots=True)
class _LoopCadenceDecision:
    """Normalized runtime cadence decision for the next coordinator wake."""

    mode: str
    reason: str
    loop_sleep_seconds: float
    voip_iterate_interval_seconds: float


def _select_loop_cadence(
    runtime_loop: "RuntimeLoopService",
    *,
    monotonic_now: float,
) -> _LoopCadenceDecision:
    """Choose the next runtime cadence from current state and queued work."""

    configured_voip_interval_seconds = max(
        0.01,
        float(runtime_loop.app._voip_iterate_interval_seconds),
    )
    fast_loop_sleep_seconds = min(
        runtime_loop._RELAXED_IDLE_INTERVAL_SECONDS,
        configured_voip_interval_seconds,
    )
    pending_callbacks = max(0, runtime_loop.app._pending_main_thread_callback_count() or 0)
    pending_events = max(0, runtime_loop.app.event_bus.pending_count())
    if pending_callbacks > 0 or pending_events > 0:
        return _LoopCadenceDecision(
            mode="latency_sensitive",
            reason="pending_work",
            loop_sleep_seconds=runtime_loop._pending_work_loop_sleep_seconds(),
            voip_iterate_interval_seconds=configured_voip_interval_seconds,
        )

    if runtime_loop.app._pending_shutdown is not None or runtime_loop.app._power_alert is not None:
        return _LoopCadenceDecision(
            mode="latency_sensitive",
            reason="safety_transition",
            loop_sleep_seconds=fast_loop_sleep_seconds,
            voip_iterate_interval_seconds=configured_voip_interval_seconds,
        )

    if runtime_loop._runtime_state_name() in runtime_loop._LATENCY_SENSITIVE_STATES:
        return _LoopCadenceDecision(
            mode="latency_sensitive",
            reason="call_or_connecting_state",
            loop_sleep_seconds=fast_loop_sleep_seconds,
            voip_iterate_interval_seconds=configured_voip_interval_seconds,
        )

    recent_input_age_seconds = (
        max(0.0, monotonic_now - runtime_loop.app._last_input_activity_at)
        if runtime_loop.app._last_input_activity_at > 0.0
        else None
    )
    if (
        recent_input_age_seconds is not None
        and recent_input_age_seconds <= runtime_loop._RECENT_INPUT_WINDOW_SECONDS
    ):
        return _LoopCadenceDecision(
            mode="latency_sensitive",
            reason="recent_input",
            loop_sleep_seconds=fast_loop_sleep_seconds,
            voip_iterate_interval_seconds=configured_voip_interval_seconds,
        )

    if not runtime_loop.app._screen_awake:
        return _LoopCadenceDecision(
            mode="idle_sleeping",
            reason="screen_sleeping",
            loop_sleep_seconds=runtime_loop._SCREEN_SLEEP_IDLE_INTERVAL_SECONDS,
            voip_iterate_interval_seconds=max(
                configured_voip_interval_seconds,
                runtime_loop._SCREEN_SLEEP_IDLE_INTERVAL_SECONDS,
            ),
        )

    return _LoopCadenceDecision(
        mode="idle_awake",
        reason="screen_awake_idle",
        loop_sleep_seconds=runtime_loop._RELAXED_IDLE_INTERVAL_SECONDS,
        voip_iterate_interval_seconds=max(
            configured_voip_interval_seconds,
            runtime_loop._RELAXED_IDLE_INTERVAL_SECONDS,
        ),
    )


def _apply_loop_cadence(
    runtime_loop: "RuntimeLoopService",
    decision: _LoopCadenceDecision,
    *,
    monotonic_now: float,
) -> None:
    """Store one cadence decision and accelerate due work when responsiveness tightens."""

    previous_voip_interval_seconds = runtime_loop._current_voip_iterate_interval_seconds
    changed = (
        runtime_loop._current_cadence_mode != decision.mode
        or runtime_loop._current_cadence_reason != decision.reason
        or abs(runtime_loop._current_loop_sleep_seconds - decision.loop_sleep_seconds) > 1e-9
        or abs(previous_voip_interval_seconds - decision.voip_iterate_interval_seconds) > 1e-9
    )
    runtime_loop._current_cadence_mode = decision.mode
    runtime_loop._current_cadence_reason = decision.reason
    runtime_loop._current_loop_sleep_seconds = decision.loop_sleep_seconds
    runtime_loop._current_voip_iterate_interval_seconds = decision.voip_iterate_interval_seconds
    runtime_loop._last_cadence_selected_at = monotonic_now

    if (
        runtime_loop.app.voip_manager is not None
        and runtime_loop.app.voip_manager.running
    ):
        if runtime_loop._voip_background_iterate_enabled():
            ensure_running = getattr(
                runtime_loop.app.voip_manager,
                "ensure_background_iterate_running",
                None,
            )
            if callable(ensure_running):
                ensure_running()
            set_interval = getattr(
                runtime_loop.app.voip_manager,
                "set_iterate_interval_seconds",
                None,
            )
            if callable(set_interval):
                set_interval(decision.voip_iterate_interval_seconds)
            # The background worker now owns iterate timing, so the coordinator-side
            # deadline stays cleared even when the cadence decision itself is unchanged.
            runtime_loop.app._next_voip_iterate_at = 0.0
        else:
            # Recompute the coordinator-side deadline on every pass so manual iterate
            # scheduling stays aligned to the latest cadence and last-start timestamp.
            runtime_loop.app._next_voip_iterate_at = _next_voip_due_at_for_cadence(
                runtime_loop=runtime_loop,
                monotonic_now=monotonic_now,
                iterate_interval_seconds=decision.voip_iterate_interval_seconds,
            )

    if not changed:
        return

    coord_logger.info(
        "Runtime cadence: "
        "mode={} reason={} sleep_ms={:.1f} voip_interval_ms={:.1f} "
        "configured_voip_interval_ms={:.1f} screen={} state={}",
        decision.mode,
        decision.reason,
        decision.loop_sleep_seconds * 1000.0,
        decision.voip_iterate_interval_seconds * 1000.0,
        runtime_loop.app._voip_iterate_interval_seconds * 1000.0,
        runtime_loop._current_screen_name(),
        runtime_loop._runtime_state_name(),
    )


def _effective_voip_iterate_interval_seconds(runtime_loop: "RuntimeLoopService") -> float:
    """Return the currently selected VoIP iterate cadence."""

    return max(0.01, runtime_loop._current_voip_iterate_interval_seconds)


def _next_voip_due_at_for_cadence(
    runtime_loop: "RuntimeLoopService",
    *,
    monotonic_now: float,
    iterate_interval_seconds: float,
) -> float:
    """Return the next VoIP iterate deadline aligned to the current cadence."""

    effective_interval_seconds = max(0.01, iterate_interval_seconds)
    if runtime_loop._last_voip_iterate_started_at <= 0.0:
        return monotonic_now + effective_interval_seconds
    return max(
        monotonic_now,
        runtime_loop._last_voip_iterate_started_at + effective_interval_seconds,
    )
