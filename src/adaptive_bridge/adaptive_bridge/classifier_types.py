# classifier_types.py
"""
Typed input/output contract for the Adaptive Bridge classifier core.

This module is pure Python — zero ROS dependency — so it can be imported by:
  - unit tests without rclpy.init()
  - classifier_core.py (state machine)
  - classifier_node.py (ROS wrapper, Step 10)
  - diagnostics.py (for snapshot conversion)

Design:
  ProbeMetrics     — structured input from the probe subsystem.
  ClassificationDecision — structured output from one evaluation cycle.
  Reason code constants  — typed strings used across the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import ClassifierSnapshot

# ──────────────────────────────────────────────────────────────────────
# Schema version (bump on breaking key change)
# ──────────────────────────────────────────────────────────────────────

CLASSIFIER_SCHEMA_VERSION: str = "1.0"

# ──────────────────────────────────────────────────────────────────────
# Reason codes (authoritative constants — never use raw strings)
# ──────────────────────────────────────────────────────────────────────

REASON_MANUAL_OVERRIDE: str = "manual_override"
REASON_HIGH_RTT: str = "high_rtt"
REASON_HIGH_LOSS: str = "high_loss"
REASON_HIGH_RTT_AND_LOSS: str = "high_rtt_and_loss"
REASON_RECOVERED: str = "recovered"
REASON_INSUFFICIENT_DATA: str = "insufficient_data"
REASON_STABLE_CRITICAL: str = "stable_critical"
REASON_PROMOTING: str = "promoting"

# All valid reason codes (for validation in tests)
ALL_REASON_CODES: frozenset[str] = frozenset({
    REASON_MANUAL_OVERRIDE,
    REASON_HIGH_RTT,
    REASON_HIGH_LOSS,
    REASON_HIGH_RTT_AND_LOSS,
    REASON_RECOVERED,
    REASON_INSUFFICIENT_DATA,
    REASON_STABLE_CRITICAL,
    REASON_PROMOTING,
})

# All valid states (for validation in tests)
ALL_STATES: frozenset[str] = frozenset({"CRITICAL", "NONCRITICAL", "UNKNOWN"})


# ──────────────────────────────────────────────────────────────────────
# ProbeMetrics — input from probe subsystem
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ProbeMetrics:
    """Structured probe metrics fed to the classifier.

    All metrics are computed by the probe subsystem over a rolling window
    before being handed to the classifier.

    Parameters
    ----------
    avg_rtt_ms:
        Rolling mean round-trip time in milliseconds.
    loss:
        Fraction of probes lost in the window; range [0.0, 1.0].
    sample_count:
        Number of probe samples that contributed to these metrics.
        A value of 0 means no data is available (classifier must handle
        this gracefully — see ``allow_unknown_state``).
    p95_rtt_ms:
        95th-percentile RTT in milliseconds.  0.0 if not available.
    jitter_ms:
        Estimated jitter (RTT variance proxy) in milliseconds. 0.0 if
        not available.
    """

    avg_rtt_ms: float
    loss: float
    sample_count: int
    p95_rtt_ms: float = 0.0
    jitter_ms: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.loss <= 1.0:
            raise ValueError(f"ProbeMetrics.loss must be in [0, 1], got {self.loss}")
        if self.sample_count < 0:
            raise ValueError(f"ProbeMetrics.sample_count must be >= 0, got {self.sample_count}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "avg_rtt_ms": float(self.avg_rtt_ms),
            "loss": float(self.loss),
            "sample_count": int(self.sample_count),
            "p95_rtt_ms": float(self.p95_rtt_ms),
            "jitter_ms": float(self.jitter_ms),
        }


# ──────────────────────────────────────────────────────────────────────
# ClassificationDecision — output of one evaluation cycle
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ClassificationDecision:
    """The result of one classifier evaluation for one subscriber.

    Parameters
    ----------
    subscriber_id:
        Identifier of the subscriber being classified.
    state:
        Current classification: ``"CRITICAL"``, ``"NONCRITICAL"``, or
        ``"UNKNOWN"``.
    reason:
        One of the ``REASON_*`` constants explaining the decision.
    ts_ns:
        Monotonic timestamp (nanoseconds) when this decision was made.
    avg_rtt_ms:
        Snapshot of the input RTT at decision time.
    loss:
        Snapshot of the input loss fraction at decision time.
    hysteresis_counter:
        Current consecutive-violation window count (gates demotion).
    consecutive_good:
        Current consecutive-good-window count (gates promotion/recovery).
    """

    subscriber_id: str
    state: str
    reason: str
    ts_ns: int
    avg_rtt_ms: float
    loss: float
    hysteresis_counter: int
    consecutive_good: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "subscriber_id": self.subscriber_id,
            "state": self.state,
            "reason": self.reason,
            "ts_ns": int(self.ts_ns),
            "avg_rtt_ms": float(self.avg_rtt_ms),
            "loss": float(self.loss),
            "hysteresis_counter": int(self.hysteresis_counter),
            "consecutive_good": int(self.consecutive_good),
        }

    def to_snapshot(self) -> ClassifierSnapshot:
        """Convert to a ``ClassifierSnapshot`` for diagnostics payload injection.

        This bridges the classifier_core output type and the existing
        diagnostics/models.py type without introducing a circular import.
        """
        reason_flags: tuple[str, ...] = (self.reason,)
        return ClassifierSnapshot(
            subscriber_id=self.subscriber_id,
            classification=self.state,
            reason_flags=reason_flags,
            avg_rtt_ms=self.avg_rtt_ms,
            loss=self.loss,
        )
