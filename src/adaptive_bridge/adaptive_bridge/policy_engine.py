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

    .. note::

       Per-topic subscriber isolation is not yet implemented.  The current
       :meth:`get_mode` checks ALL known subscribers and returns DEGRADED
       if *any* is NONCRITICAL.  Future work should introduce a
       subscriber-to-topic mapping so that one degraded subscriber does not
       affect unrelated topics.
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
        self._last_decision_data: dict[str, dict] = {}

    def on_classifier_update(self, subscriber_id: str, state: str,
                              decision_data: dict | None = None) -> None:
        """Process a single classifier decision for one subscriber.

        Applies forced-critical override first, then transition damping.
        Optionally stores the full decision dict for diagnostics injection.
        """
        if subscriber_id in self._forced_critical:
            self._subscriber_states[subscriber_id] = "CRITICAL"
            self._damping_counters[subscriber_id] = self._hysteresis_count
            if decision_data:
                self._last_decision_data[subscriber_id] = decision_data
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
        """Return the global PolicyMode across all tracked subscribers.

        The ``topic_id`` parameter is reserved for future per-topic isolation
        but is currently unused — the engine checks ALL known subscriber states.
        If ANY subscriber is NONCRITICAL, the entire system is DEGRADED.
        This is the safest default until per-topic subscriber mapping is added.
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

    def get_subscriber_decisions(self) -> dict[str, dict]:
        """Return the last full decision data dict for each subscriber.

        Used by diagnostics to inject classifier details into payload."""
        return dict(self._last_decision_data)
