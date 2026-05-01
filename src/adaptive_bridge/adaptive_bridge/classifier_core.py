# classifier_core.py
"""
Adaptive Bridge — Classifier Core Library (Step 9).

This module implements the deterministic subscriber classification state machine.
It is pure Python with zero ROS dependency, making it independently unit-testable.

Architecture
------------
SubscriberClassifier
  - Maintains per-subscriber internal state (_SubscriberState).
  - Accepts ProbeMetrics inputs via update().
  - Applies threshold gates + hysteresis counters to decide state transitions.
  - Respects forced-critical overrides (always wins, highest precedence).
  - Returns ClassificationDecision on every update() call.
  - Exposes snapshot() for diagnostics and node integration.

State Machine (per subscriber)
-------------------------------
States:   UNKNOWN → (initial, insufficient data or not yet converged)
          CRITICAL → (safe default once data is available)
          NONCRITICAL → (demoted due to sustained metric violations)

Transitions (all gated by hysteresis_count consecutive windows):
  UNKNOWN    → NONCRITICAL   N consecutive bad windows
  UNKNOWN    → CRITICAL      N consecutive good windows
  CRITICAL   → NONCRITICAL   N consecutive bad windows
  NONCRITICAL → CRITICAL     N consecutive good windows  (reason: recovered)
  ANY        → CRITICAL      forced override active      (bypasses machine)

Safety bias:
  When uncertain (UNKNOWN + allow_unknown_state=False), default to CRITICAL.
  Forced-critical override is checked first, before any threshold logic.

Thread safety:
  Not thread-safe. The ROS classifier node (Step 10) must call update() and
  snapshot() only from a single ROS executor thread (e.g., a periodic timer
  callback). Do not call from multiple threads concurrently.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from .config_types import ClassifierConfig
from .classifier_types import (
    ClassificationDecision,
    ProbeMetrics,
    REASON_HIGH_LOSS,
    REASON_HIGH_RTT,
    REASON_HIGH_RTT_AND_LOSS,
    REASON_INSUFFICIENT_DATA,
    REASON_MANUAL_OVERRIDE,
    REASON_PROMOTING,
    REASON_RECOVERED,
    REASON_STABLE_CRITICAL,
)


# ──────────────────────────────────────────────────────────────────────
# Internal per-subscriber mutable state
# ──────────────────────────────────────────────────────────────────────

@dataclass
class _SubscriberState:
    """Internal mutable state for one subscriber's classification machine.

    This is intentionally not frozen — the state machine mutates it on every
    update() call.
    """

    state: str = "UNKNOWN"
    hysteresis_counter: int = 0    # consecutive violation windows (gates demotion)
    consecutive_good: int = 0      # consecutive clean windows (gates promotion)
    last_decision: Optional[ClassificationDecision] = None


# ──────────────────────────────────────────────────────────────────────
# SubscriberClassifier — the state machine engine
# ──────────────────────────────────────────────────────────────────────

class SubscriberClassifier:
    """Deterministic per-subscriber classification state machine.

    Parameters
    ----------
    config:
        ``ClassifierConfig`` providing all threshold and hysteresis values.
    forced_critical_ids:
        Optional set of subscriber IDs that are always classified as CRITICAL
        regardless of probe metrics (manual override, highest precedence).
    """

    def __init__(
        self,
        config: ClassifierConfig,
        forced_critical_ids: Optional[set] = None,
    ) -> None:
        self._config = config
        self._forced_critical: set[str] = set(forced_critical_ids or set())
        # Per-subscriber state, lazily initialized on first update()
        self._states: dict[str, _SubscriberState] = {}

    # ── Public interface ───────────────────────────────────────────────

    def update(
        self,
        subscriber_id: str,
        metrics: ProbeMetrics,
        now_ns: Optional[int] = None,
    ) -> ClassificationDecision:
        """Evaluate one subscriber against current probe metrics.

        Parameters
        ----------
        subscriber_id:
            Identifier for the subscriber (e.g., node name, IP, or UUID).
        metrics:
            Latest ``ProbeMetrics`` from the probe subsystem.
        now_ns:
            Monotonic timestamp in nanoseconds.  Defaults to ``time.monotonic_ns()``.

        Returns
        -------
        ClassificationDecision
            The current classification decision.  Always returned even if the
            state did not change (allows callers to always have fresh data).
        """
        if now_ns is None:
            now_ns = time.monotonic_ns()

        # Lazily initialize subscriber state
        if subscriber_id not in self._states:
            self._states[subscriber_id] = _SubscriberState()

        sub_state = self._states[subscriber_id]

        # ── Step 1: Forced-critical override (highest precedence) ──────
        if subscriber_id in self._forced_critical:
            decision = ClassificationDecision(
                subscriber_id=subscriber_id,
                state="CRITICAL",
                reason=REASON_MANUAL_OVERRIDE,
                ts_ns=now_ns,
                avg_rtt_ms=float(metrics.avg_rtt_ms),
                loss=float(metrics.loss),
                hysteresis_counter=sub_state.hysteresis_counter,
                consecutive_good=sub_state.consecutive_good,
            )
            # Do NOT modify machine state so that removing the override
            # leaves the subscriber in its pre-override state.
            sub_state.last_decision = decision
            return decision

        # ── Step 2: Insufficient data ──────────────────────────────────
        if metrics.sample_count < 1:
            effective_state = (
                "UNKNOWN" if self._config.allow_unknown_state else "CRITICAL"
            )
            decision = ClassificationDecision(
                subscriber_id=subscriber_id,
                state=effective_state,
                reason=REASON_INSUFFICIENT_DATA,
                ts_ns=now_ns,
                avg_rtt_ms=float(metrics.avg_rtt_ms),
                loss=float(metrics.loss),
                hysteresis_counter=sub_state.hysteresis_counter,
                consecutive_good=sub_state.consecutive_good,
            )
            sub_state.last_decision = decision
            return decision

        # ── Step 3: Threshold evaluation ───────────────────────────────
        rtt_violated = metrics.avg_rtt_ms > self._config.demote_rtt_ms
        loss_violated = metrics.loss > self._config.demote_loss_threshold
        rtt_good = metrics.avg_rtt_ms <= self._config.promote_rtt_ms
        loss_good = metrics.loss <= self._config.promote_loss_threshold

        is_bad = rtt_violated or loss_violated
        is_good = rtt_good and loss_good

        # Reason code for a bad sample
        if rtt_violated and loss_violated:
            bad_reason = REASON_HIGH_RTT_AND_LOSS
        elif rtt_violated:
            bad_reason = REASON_HIGH_RTT
        else:
            bad_reason = REASON_HIGH_LOSS

        # ── Step 4: State machine transitions ─────────────────────────
        current = sub_state.state
        reason: str
        next_state: str = current

        if current == "UNKNOWN":
            if is_bad:
                sub_state.hysteresis_counter += 1
                sub_state.consecutive_good = 0
                if sub_state.hysteresis_counter >= self._config.hysteresis_count:
                    next_state = "NONCRITICAL"
                    sub_state.hysteresis_counter = 0
                    sub_state.consecutive_good = 0
                    reason = bad_reason
                else:
                    reason = bad_reason
            elif is_good:
                sub_state.consecutive_good += 1
                sub_state.hysteresis_counter = 0
                if sub_state.consecutive_good >= self._config.hysteresis_count:
                    next_state = "CRITICAL"
                    sub_state.hysteresis_counter = 0
                    sub_state.consecutive_good = 0
                    reason = REASON_STABLE_CRITICAL
                else:
                    reason = REASON_PROMOTING
            else:
                # Fuzzy zone — neither clearly bad nor clearly good
                sub_state.hysteresis_counter = 0
                sub_state.consecutive_good = 0
                reason = REASON_INSUFFICIENT_DATA

        elif current == "CRITICAL":
            if is_bad:
                sub_state.hysteresis_counter += 1
                sub_state.consecutive_good = 0
                if sub_state.hysteresis_counter >= self._config.hysteresis_count:
                    next_state = "NONCRITICAL"
                    sub_state.hysteresis_counter = 0
                    sub_state.consecutive_good = 0
                    reason = bad_reason
                else:
                    reason = bad_reason
            else:
                # Good sample while CRITICAL — reset demotion counter
                sub_state.hysteresis_counter = 0
                sub_state.consecutive_good += 1
                reason = REASON_STABLE_CRITICAL

        else:  # NONCRITICAL
            if is_good:
                sub_state.consecutive_good += 1
                sub_state.hysteresis_counter = 0
                if sub_state.consecutive_good >= self._config.hysteresis_count:
                    next_state = "CRITICAL"
                    sub_state.hysteresis_counter = 0
                    sub_state.consecutive_good = 0
                    reason = REASON_RECOVERED
                else:
                    reason = REASON_RECOVERED  # "recovering" in progress
            else:
                # Still bad — stay NONCRITICAL, reset recovery counter
                sub_state.consecutive_good = 0
                sub_state.hysteresis_counter += 1
                reason = bad_reason

        sub_state.state = next_state

        decision = ClassificationDecision(
            subscriber_id=subscriber_id,
            state=next_state,
            reason=reason,
            ts_ns=now_ns,
            avg_rtt_ms=float(metrics.avg_rtt_ms),
            loss=float(metrics.loss),
            hysteresis_counter=sub_state.hysteresis_counter,
            consecutive_good=sub_state.consecutive_good,
        )
        sub_state.last_decision = decision
        return decision

    def snapshot(self) -> dict[str, ClassificationDecision]:
        """Return the most recent decision for every known subscriber.

        Returns an empty dict if no subscribers have been updated yet.
        The returned dict is a shallow copy — safe to iterate while the
        classifier continues to run.
        """
        return {
            sub_id: state.last_decision
            for sub_id, state in self._states.items()
            if state.last_decision is not None
        }

    def reset(self, subscriber_id: str) -> None:
        """Reset a single subscriber to initial UNKNOWN state.

        The next ``update()`` call for this subscriber will start fresh.
        """
        self._states.pop(subscriber_id, None)

    def reset_all(self) -> None:
        """Reset all subscribers to initial state."""
        self._states.clear()

    def set_forced_critical(self, subscriber_id: str, forced: bool) -> None:
        """Add or remove a subscriber from the forced-critical override set.

        Parameters
        ----------
        subscriber_id:
            The subscriber to override.
        forced:
            ``True`` to force CRITICAL, ``False`` to remove the override.
        """
        if forced:
            self._forced_critical.add(subscriber_id)
        else:
            self._forced_critical.discard(subscriber_id)

    # ── Internal helpers ───────────────────────────────────────────────

    @property
    def known_subscribers(self) -> list[str]:
        """Return a list of all subscriber IDs known to the classifier."""
        return list(self._states.keys())
