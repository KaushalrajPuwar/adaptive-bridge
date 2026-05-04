"""
Shared runtime data structures for Adaptive Bridge.

Defines the core types shared across proxy, classifier, diagnostics, and
tests: :class:`TopicRoute` (input + critical + noncritical topic names),
:class:`TopicCounters` (per-topic message counters), :class:`PolicyMode`
(``NORMAL``, ``DEGRADED``, ``DISABLED``, ``FAILURE``), and serialisation
helpers for diagnostics export.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PolicyMode(str, Enum):
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    EMERGENCY = "EMERGENCY"
    DISABLED = "DISABLED"
    FAILURE = "FAILURE"


@dataclass(frozen=True)
class TopicRoute:
    topic_id: str
    input_topic: str
    critical_output: str
    noncritical_output: str
    message_type: str = "sensor_msgs/LaserScan"

    def to_dict(self) -> dict[str, str]:
        return {
            "topic_id": self.topic_id,
            "input_topic": self.input_topic,
            "critical_output": self.critical_output,
            "noncritical_output": self.noncritical_output,
            "message_type": self.message_type,
        }


@dataclass
class TopicCounters:
    total_received: int = 0
    total_forwarded_critical: int = 0
    total_forwarded_noncritical: int = 0
    dropped_noncritical_rate_limit: int = 0
    dropped_noncritical_stale: int = 0
    dropped_noncritical_queue: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "total_received": self.total_received,
            "total_forwarded_critical": self.total_forwarded_critical,
            "total_forwarded_noncritical": self.total_forwarded_noncritical,
            "dropped_noncritical_rate_limit": self.dropped_noncritical_rate_limit,
            "dropped_noncritical_stale": self.dropped_noncritical_stale,
            "dropped_noncritical_queue": self.dropped_noncritical_queue,
        }


@dataclass(frozen=True)
class ClassifierSnapshot:
    subscriber_id: str
    classification: str
    reason_flags: tuple[str, ...] = ()
    avg_rtt_ms: float = 0.0
    loss: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "subscriber_id": self.subscriber_id,
            "classification": self.classification,
            "reason_flags": list(self.reason_flags),
            "avg_rtt_ms": float(self.avg_rtt_ms),
            "loss": float(self.loss),
        }


@dataclass
class TopicRuntimeState:
    route: TopicRoute
    counters: TopicCounters = field(default_factory=TopicCounters)
    noncritical_mode: PolicyMode = PolicyMode.NORMAL
    last_publish_ts_critical: float | None = None
    last_publish_ts_noncritical: float | None = None
    noncritical_tokens: float | None = None
    noncritical_last_refill_ts: float | None = None
    latest_classifier_snapshot: dict[str, ClassifierSnapshot] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route.to_dict(),
            "counters": self.counters.to_dict(),
            "noncritical_mode": self.noncritical_mode.value,
            "last_publish_ts_critical": self.last_publish_ts_critical,
            "last_publish_ts_noncritical": self.last_publish_ts_noncritical,
            "noncritical_tokens": self.noncritical_tokens,
            "noncritical_last_refill_ts": self.noncritical_last_refill_ts,
            "latest_classifier_snapshot": {
                sub_id: snap.to_dict() for sub_id, snap in self.latest_classifier_snapshot.items()
            },
        }
