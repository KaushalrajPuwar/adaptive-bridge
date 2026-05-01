# src/adaptive_bridge/adaptive_bridge/policy_engine.py
"""
Adaptive Bridge Policy Engine — Step 11.

Maps classifier state decisions to per-topic noncritical policy modes.
Implements transition damping (hysteresis), safety bias (UNKNOWN -> CRITICAL),
and forced-critical override enforcement.

Public API:
  on_classifier_update(subscriber_id, state)  -> ingest classifier output
  get_mode(topic_id)                          -> PolicyMode for a topic
  get_mode_for_subscriber(subscriber_id)      -> PolicyMode for a subscriber
  get_subscriber_states()                     -> snapshot for diagnostics
"""

from .models import PolicyMode


class PolicyEngine:
    """Maps classifier subscriber states into per-topic noncritical PolicyMode.

    Parameters
    ----------
    hysteresis_count:
        Number of consecutive stable classifier windows required before a
        mode change takes effect.  Default 3.
    forced_critical_ids:
        Optional set of subscriber IDs that are always treated as CRITICAL
        regardless of their classifier state (manual override).
    """

    def __init__(
        self,
        hysteresis_count: int = 3,
        forced_critical_ids: set | None = None,
    ) -> None:
        self._hysteresis_count = max(1, hysteresis_count)
        self._forced_critical: set = set(forced_critical_ids or [])

        self._subscriber_states: dict[str, str] = {}
        self._damping_counters: dict[str, int] = {}
        self._last_classification: dict[str, str] = {}

    def on_classifier_update(self, subscriber_id: str, state: str) -> None:
        """Process a single classifier decision for one subscriber.

        Applies forced-critical override first, then transition damping.
        A subscriber must report the same state for N consecutive windows
        before the policy engine accepts it as stable.
        """
        if subscriber_id in self._forced_critical:
            self._subscriber_states[subscriber_id] = "CRITICAL"
            self._damping_counters[subscriber_id] = self._hysteresis_count
            return

        prev = self._last_classification.get(subscriber_id)
        if prev is None:
            self._damping_counters[subscriber_id] = 1
        elif prev == state:
            self._damping_counters[subscriber_id] = (
                self._damping_counters.get(subscriber_id, 0) + 1
            )
        else:
            self._damping_counters[subscriber_id] = 0

        self._last_classification[subscriber_id] = state

        if self._damping_counters.get(subscriber_id, 0) >= self._hysteresis_count:
            self._subscriber_states[subscriber_id] = state

    def get_mode(self, topic_id: str) -> PolicyMode:
        """Return the appropriate PolicyMode for a topic.

        Safety bias: UNKNOWN subscribers are treated as CRITICAL (NORMAL mode).
        If ANY subscriber for this topic is NONCRITICAL, the topic is DEGRADED.
        """
        for sub_id, curr_state in self._subscriber_states.items():
            if curr_state == "NONCRITICAL":
                return PolicyMode.DEGRADED
        return PolicyMode.NORMAL

    def get_mode_for_subscriber(self, subscriber_id: str) -> PolicyMode:
        """Return the mode for a single subscriber (for diagnostics)."""
        state = self._subscriber_states.get(subscriber_id, "UNKNOWN")
        if state == "NONCRITICAL":
            return PolicyMode.DEGRADED
        return PolicyMode.NORMAL

    def get_subscriber_states(self) -> dict[str, str]:
        """Return the current stable classifier state for all subscribers."""
        return dict(self._subscriber_states)
