# src/adaptive_bridge/adaptive_bridge/safety_supervisor.py
"""
Adaptive Bridge Safety Supervisor — Step 12.

Pure-Python state machine that evaluates runtime metrics and transitions
between NORMAL, DEGRADED, EMERGENCY, and FAILURE global modes.

Drives fail-safe behavior:
  - DEGRADED: override all noncritical topics to DISABLED
  - EMERGENCY: suspend noncritical, halve probe rate
  - FAILURE: trigger graceful proxy shutdown

Uses hysteresis-window transitions: N consecutive bad windows to degrade,
M consecutive clean windows to recover.

Thread safety: not thread-safe. Caller must serialize evaluate() calls.
"""

from .models import PolicyMode


class SafetySupervisor:
    """Global mode machine with hysteresis-gated transitions.

    Parameters
    ----------
    degrade_queue_pct:
        Queue fullness ratio (0-1) that triggers NORMAL -> DEGRADED.
    restore_low_pct:
        Queue ratio below which EMERGENCY can recover to DEGRADED.
    restore_mid_pct:
        Queue ratio below which DEGRADED can recover to NORMAL.
    degrade_windows:
        Consecutive violation windows to trigger degrade.
    restore_windows:
        Consecutive clean windows to trigger recovery.
    max_noncritical_queue:
        Maximum noncritical queue depth (from config).
    """

    def __init__(
        self,
        degrade_queue_pct: float = 0.50,
        restore_low_pct: float = 0.10,
        restore_mid_pct: float = 0.30,
        degrade_windows: int = 3,
        restore_windows: int = 5,
        max_noncritical_queue: int = 50,
    ) -> None:
        self._mode = PolicyMode.NORMAL
        self._degrade_queue_pct = degrade_queue_pct
        self._restore_low_pct = restore_low_pct
        self._restore_mid_pct = restore_mid_pct
        self._degrade_windows = degrade_windows
        self._restore_windows = restore_windows
        self._max_queue = max_noncritical_queue

        self._degrade_counter = 0
        self._overflow_counter = 0
        self._restore_counter = 0
        self._component_errors = 0
        self._shutdown_requested = False

    def evaluate(
        self, queue_sizes: list, overflow_count: int = 0, error_count: int = 0
    ) -> tuple:
        """Evaluate current metrics and advance the state machine.

        Parameters
        ----------
        queue_sizes:
            Current sizes of all noncritical queues (int list).
        overflow_count:
            Cumulative queue overflow events since last evaluation.
        error_count:
            Cumulative internal error count.

        Returns
        -------
        tuple[str, str]:
            (current_mode_string, transition_reason_string).
        """
        prev_mode = self._mode

        if self._mode == PolicyMode.FAILURE:
            return (self._mode.value, "terminal")

        # Track component errors independently
        if error_count > 0:
            self._component_errors += error_count

        max_queue_pct = max(
            (q / self._max_queue) for q in queue_sizes
        ) if queue_sizes else 0.0

        if self._mode == PolicyMode.NORMAL:
            if max_queue_pct > self._degrade_queue_pct or overflow_count > 0:
                self._degrade_counter += 1
                self._restore_counter = 0
            else:
                self._degrade_counter = 0
            if self._degrade_counter >= self._degrade_windows:
                self._mode = PolicyMode.DEGRADED
                self._degrade_counter = 0

        elif self._mode == PolicyMode.DEGRADED:
            if overflow_count > 0:
                self._overflow_counter += 1
                self._restore_counter = 0
            else:
                self._overflow_counter = 0
            # Escalate to EMERGENCY
            if self._overflow_counter >= self._degrade_windows:
                self._mode = PolicyMode.EMERGENCY
                self._overflow_counter = 0
            # Recover to NORMAL
            elif max_queue_pct < self._restore_low_pct and overflow_count == 0:
                self._restore_counter += 1
                if self._restore_counter >= self._restore_windows:
                    self._mode = PolicyMode.NORMAL
                    self._restore_counter = 0
            else:
                self._restore_counter = 0

        elif self._mode == PolicyMode.EMERGENCY:
            if max_queue_pct < self._restore_mid_pct and overflow_count == 0:
                self._restore_counter += 1
                if self._restore_counter >= self._restore_windows:
                    self._mode = PolicyMode.DEGRADED
                    self._restore_counter = 0
            else:
                self._restore_counter = 0

        # Fail on sustained component errors
        if self._component_errors >= 10:
            self._mode = PolicyMode.FAILURE
            self._shutdown_requested = True

        transition = (
            f"{prev_mode.value} -> {self._mode.value}"
            if prev_mode != self._mode else "steady"
        )
        return (self._mode.value, transition)

    def get_mode(self) -> PolicyMode:
        """Return current PolicyMode."""
        return self._mode

    def record_fault(self, count: int = 1) -> None:
        """Record component faults that contribute toward FAILURE mode."""
        self._component_errors += count

    def is_shutdown_requested(self) -> bool:
        """Return True if FAILURE mode requests proxy shutdown."""
        return self._shutdown_requested
