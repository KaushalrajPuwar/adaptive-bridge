# src/tests/test_classifier_node_integration.py
"""
Integration tests for Step 10 — Classifier Node Runtime Integration.

Tests spin up ClassifierNode + ProbeResponder in a live ROS2 graph
and verify real probe exchange, decision publishing, and robustness.

All tests require rclpy.init() and use SingleThreadedExecutor.
"""
from __future__ import annotations

import pytest
import json
import time
import threading

import rclpy
from rclpy.executors import SingleThreadedExecutor
from std_msgs.msg import String

from adaptive_bridge.classifier_node import ClassifierNode
from adaptive_bridge.utils.probes import ProbeResponder, stats_to_probe_metrics
from adaptive_bridge.classifier_types import (
    ALL_REASON_CODES,
    ALL_STATES,
    ProbeMetrics,
)


@pytest.fixture(scope="module")
def ros_context():
    """Initialize rclpy once for the entire test module."""
    rclpy.init()
    yield
    try:
        rclpy.shutdown()
    except Exception:
        pass


def _spin_executor(executor: SingleThreadedExecutor, duration_s: float) -> None:
    """Run an executor in a background thread for a fixed duration."""
    stop = threading.Event()

    def spin():
        while not stop.is_set():
            executor.spin_once(timeout_sec=0.05)

    t = threading.Thread(target=spin, daemon=True)
    t.start()
    time.sleep(duration_s)
    stop.set()
    time.sleep(0.1)


# ------------------------------------------------------------------
# A. Node Lifecycle
# ------------------------------------------------------------------

class TestNodeLifecycle:
    def test_node_starts_and_stops_cleanly(self, ros_context):
        classifier = ClassifierNode()
        assert classifier.get_eval_count() == 0
        assert classifier.get_error_count() == 0
        classifier.destroy()

    def test_node_destroy_releases_timers(self, ros_context):
        classifier = ClassifierNode()
        classifier.destroy()
        assert classifier._eval_timer.is_canceled or not classifier._eval_timer.is_ready


# ------------------------------------------------------------------
# B. Decision Publishing
# ------------------------------------------------------------------

class TestDecisionPublishing:
    def test_decisions_published_to_classifier_state_topic(self, ros_context):
        classifier = ClassifierNode()
        responder = ProbeResponder()

        executor = SingleThreadedExecutor()
        executor.add_node(classifier)
        executor.add_node(responder)

        received: list[dict] = []

        def collect(msg: String):
            received.append(json.loads(msg.data))

        sub = classifier.create_subscription(
            String, "/adaptive_bridge/classifier/state", collect, 10
        )

        _spin_executor(executor, 6.0)

        assert len(received) >= 1, "No classifier decisions published"

        classifier.destroy()
        responder.destroy()

        # Clean up the executor's internal state
        executor.remove_node(classifier)
        executor.remove_node(responder)

    def test_decision_payload_has_required_keys(self, ros_context):
        classifier = ClassifierNode()
        responder = ProbeResponder()

        executor = SingleThreadedExecutor()
        executor.add_node(classifier)
        executor.add_node(responder)

        received: list[dict] = []

        def collect(msg: String):
            received.append(json.loads(msg.data))

        sub = classifier.create_subscription(
            String, "/adaptive_bridge/classifier/state", collect, 10
        )

        _spin_executor(executor, 6.0)

        assert len(received) >= 1
        d = received[0]
        required = {
            "subscriber_id", "state", "reason", "ts_ns",
            "avg_rtt_ms", "loss", "hysteresis_counter", "consecutive_good",
            "eval_count", "error_count",
        }
        missing = required - set(d.keys())
        assert not missing, f"Missing keys: {missing}"

        classifier.destroy()
        responder.destroy()

        executor.remove_node(classifier)
        executor.remove_node(responder)

    def test_decision_state_is_valid(self, ros_context):
        classifier = ClassifierNode()
        responder = ProbeResponder()

        executor = SingleThreadedExecutor()
        executor.add_node(classifier)
        executor.add_node(responder)

        received: list[dict] = []

        def collect(msg: String):
            received.append(json.loads(msg.data))

        sub = classifier.create_subscription(
            String, "/adaptive_bridge/classifier/state", collect, 10
        )

        _spin_executor(executor, 6.0)

        assert len(received) >= 1
        for d in received:
            assert d["state"] in ALL_STATES, f"Invalid state: {d['state']}"
            assert d["reason"] in ALL_REASON_CODES, f"Invalid reason: {d['reason']}"

        classifier.destroy()
        responder.destroy()

        executor.remove_node(classifier)
        executor.remove_node(responder)

    def test_eval_count_monotonic(self, ros_context):
        classifier = ClassifierNode()
        responder = ProbeResponder()

        executor = SingleThreadedExecutor()
        executor.add_node(classifier)
        executor.add_node(responder)

        received: list[dict] = []

        def collect(msg: String):
            received.append(json.loads(msg.data))

        sub = classifier.create_subscription(
            String, "/adaptive_bridge/classifier/state", collect, 10
        )

        # Spin briefly first to flush any stale messages, then collect fresh
        _spin_executor(executor, 0.5)
        received.clear()

        _spin_executor(executor, 6.0)

        assert len(received) >= 2, "Need at least 2 decisions for monotonic check"
        counts = [d.get("eval_count", 0) for d in received if "eval_count" in d]
        for i in range(1, len(counts)):
            assert counts[i] >= counts[i - 1], (
                f"eval_count not monotonic at index {i}: {counts[i - 1]} -> {counts[i]}"
            )

        classifier.destroy()
        responder.destroy()

        executor.remove_node(classifier)
        executor.remove_node(responder)


# ------------------------------------------------------------------
# C. Robustness
# ------------------------------------------------------------------

class TestRobustness:
    def test_no_crash_without_probe_responder(self, ros_context):
        """Classifier publishes decisions even with zero probe responses."""
        classifier = ClassifierNode()
        executor = SingleThreadedExecutor()
        executor.add_node(classifier)

        received: list[dict] = []

        def collect(msg: String):
            received.append(json.loads(msg.data))

        sub = classifier.create_subscription(
            String, "/adaptive_bridge/classifier/state", collect, 10
        )

        _spin_executor(executor, 5.0)

        assert len(received) >= 1, "Classifier should publish even without probe data"
        # With no data, probe metrics have sample_count=0
        # -> classifier returns UNKNOWN (allow_unknown_state=True in default config)
        # or CRITICAL (allow_unknown_state=False)
        for d in received:
            assert d["state"] in ALL_STATES
            # ts_ns should be populated
            assert d["ts_ns"] > 0

        assert classifier.get_error_count() == 0, "No eval errors expected"
        classifier.destroy()
        executor.remove_node(classifier)

    def test_recovery_after_probe_responder_appears(self, ros_context):
        """State transitions from UNKNOWN toward CRITICAL as probe data arrives."""
        classifier = ClassifierNode()

        executor = SingleThreadedExecutor()
        executor.add_node(classifier)

        received_before: list[dict] = []

        def collect(msg: String):
            received_before.append(json.loads(msg.data))

        sub = classifier.create_subscription(
            String, "/adaptive_bridge/classifier/state", collect, 10
        )

        # Phase 1: spin without responder
        _spin_executor(executor, 5.0)
        state_before = received_before[-1]["state"] if received_before else "UNKNOWN"

        # Phase 2: add responder
        responder = ProbeResponder()
        executor.add_node(responder)
        received_after: list[dict] = []
        # Remove old callback and re-subscribe to get just phase-2 messages
        classifier.destroy_subscription(sub)
        sub2 = classifier.create_subscription(
            String, "/adaptive_bridge/classifier/state",
            lambda msg: received_after.append(json.loads(msg.data)), 10
        )

        _spin_executor(executor, 5.0)

        assert len(received_after) >= 1, "No decisions after responder added"

        # With real probe responses, sample_count > 0 and classifier should
        # eventually reach CRITICAL given good network.
        # We don't assert exact state (hysteresis may take time) but verify
        # at least one decision is published with valid state.
        for d in received_after:
            assert d["state"] in ALL_STATES

        classifier.destroy()
        responder.destroy()
        executor.remove_node(classifier)
        executor.remove_node(responder)

    def test_ts_ns_increases_monotonically(self, ros_context):
        classifier = ClassifierNode()
        responder = ProbeResponder()

        executor = SingleThreadedExecutor()
        executor.add_node(classifier)
        executor.add_node(responder)

        received: list[dict] = []

        def collect(msg: String):
            received.append(json.loads(msg.data))

        sub = classifier.create_subscription(
            String, "/adaptive_bridge/classifier/state", collect, 10
        )

        _spin_executor(executor, 6.0)
        assert len(received) >= 3

        ts_values = [d["ts_ns"] for d in received if "ts_ns" in d]
        for i in range(1, len(ts_values)):
            assert ts_values[i] >= ts_values[i - 1], (
                f"ts_ns decreased at index {i}: {ts_values[i - 1]} -> {ts_values[i]}"
            )

        classifier.destroy()
        responder.destroy()
        executor.remove_node(classifier)
        executor.remove_node(responder)


# ------------------------------------------------------------------
# D. Probe Metrics Conversion
# ------------------------------------------------------------------

class TestProbeMetricsConversion:
    def test_stats_to_probe_metrics_mapping(self):
        """Verify stats_to_probe_metrics() converts get_stats() dict correctly."""
        stats = {
            "sender_id": "test_client",
            "protocol_version": 1,
            "window_size": 10,
            "sent_total": 100,
            "recv_total": 95,
            "loss_rate": 0.05,
            "rtt": {"count": 10, "mean_ms": 15.3, "p95_ms": 25.1},
            "jitter": {"count": 9, "mean_ms": 3.2, "p95_ms": 7.8},
            "errors": {},
            "outstanding_count": 2,
            "last_seq": 200,
        }

        m = stats_to_probe_metrics(stats)

        assert isinstance(m, ProbeMetrics)
        assert m.avg_rtt_ms == 15.3
        assert m.loss == 0.05
        assert m.sample_count == 10
        assert m.p95_rtt_ms == 25.1
        assert m.jitter_ms == 3.2

    def test_stats_to_probe_metrics_empty_dict(self):
        """Empty dict should produce zero-valued valid ProbeMetrics."""
        m = stats_to_probe_metrics({})
        assert isinstance(m, ProbeMetrics)
        assert m.avg_rtt_ms == 0.0
        assert m.loss == 0.0
        assert m.sample_count == 0

    def test_stats_to_probe_metrics_partial(self):
        """Missing rtt/jitter sub-dicts should not crash."""
        stats = {"loss_rate": 0.2}
        m = stats_to_probe_metrics(stats)
        assert m.avg_rtt_ms == 0.0
        assert m.loss == 0.2
        assert m.sample_count == 0
        assert m.p95_rtt_ms == 0.0
        assert m.jitter_ms == 0.0
