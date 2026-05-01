# src/tests/test_probes.py
"""
Unit tests for Step 8 — Probe Protocol Hardening.

Tests for ProbeClient (hardened protocol v1, bounded storage, windowed metrics,
sanity checks, jitter, timeout) and ProbeResponder (versioned responses with
receiver-side timestamps).

All tests use mocking — no rclpy.init() required.

Test categories:
  A. Payload Format and Versioning (5 tests)
  B. Receive-Side Sanity Checks (6 tests)
  C. Bounded Storage and Timeout (4 tests)
  D. Rolling Metrics Computation (5 tests)
  E. get_stats() Contract (3 tests)
  F. ProbeResponder Tests (4 tests)
Total: 27 tests
"""

from __future__ import annotations

import sys
import os

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "adaptive_bridge"),
)

import json
import time
import pytest
from unittest.mock import MagicMock, patch
from collections import deque

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

TIME_BASE = 1_700_000_000_000_000_000  # ~1.7e18 ns


@pytest.fixture
def mock_ros_node(monkeypatch):
    """Mock ROS Node methods so ProbeClient/ProbeResponder can be instantiated
    without a live rclpy runtime."""
    monkeypatch.setattr(
        "rclpy.node.Node.__init__", lambda self, *a, **kw: None
    )
    monkeypatch.setattr(
        "rclpy.node.Node.create_publisher", lambda *a, **kw: MagicMock()
    )
    monkeypatch.setattr(
        "rclpy.node.Node.create_subscription", lambda *a, **kw: MagicMock()
    )
    monkeypatch.setattr(
        "rclpy.node.Node.create_timer", lambda *a, **kw: MagicMock()
    )
    monkeypatch.setattr(
        "rclpy.node.Node.get_logger", lambda self: MagicMock()
    )
    monkeypatch.setattr(
        "rclpy.node.Node.destroy_node", lambda self: None
    )


@pytest.fixture
def client(mock_ros_node):
    """Create a ProbeClient with a small window for deterministic testing."""
    from adaptive_bridge.utils.probes import ProbeClient

    c = ProbeClient(
        node_name="test_probe_client",
        rate_hz=5.0,
        window_size=10,
        timeout_ms=500,
    )
    c._pub = MagicMock()
    return c


@pytest.fixture
def responder(mock_ros_node):
    """Create a ProbeResponder for testing."""
    from adaptive_bridge.utils.probes import ProbeResponder

    r = ProbeResponder(node_name="test_responder")
    r._pub = MagicMock()
    return r


# ---------------------------------------------------------------------------
# A. Payload Format and Versioning
# ---------------------------------------------------------------------------

class TestPayloadFormat:
    def test_probe_request_payload_structure(self, client, monkeypatch):
        """Emitted request JSON contains all required fields."""
        published = []

        def capture(msg):
            published.append(json.loads(msg.data))

        client._pub.publish.side_effect = capture
        monkeypatch.setattr(time, "monotonic_ns", lambda: TIME_BASE)
        client._on_send_timer()

        p = published[0]
        assert p["v"] == 1
        assert isinstance(p["seq"], int) and p["seq"] == 1
        assert p["send_time_ns"] == TIME_BASE
        assert p["sender_id"] == "test_probe_client"
        assert p["probe_id"] == "test_probe_client"

    def test_sequence_monotonically_increases(self, client, monkeypatch):
        """seq increments by 1 each call."""
        published = []

        def capture(msg):
            published.append(json.loads(msg.data))

        client._pub.publish.side_effect = capture
        monkeypatch.setattr(time, "monotonic_ns", lambda: TIME_BASE)

        for i in range(5):
            client._on_send_timer()

        seqs = [p["seq"] for p in published]
        assert seqs == [1, 2, 3, 4, 5]

    def test_protocol_version_in_payload(self, client, monkeypatch):
        """v field is 1 (PROBE_PROTOCOL_VERSION)."""
        published = []

        def capture(msg):
            published.append(json.loads(msg.data))

        client._pub.publish.side_effect = capture
        monkeypatch.setattr(time, "monotonic_ns", lambda: TIME_BASE)
        client._on_send_timer()
        assert published[0]["v"] == 1

    def test_request_uses_monotonic_ns_range(self, client, monkeypatch):
        """send_time_ns is in the realistic nanosecond range (> 1e15)."""
        published = []

        def capture(msg):
            published.append(json.loads(msg.data))

        client._pub.publish.side_effect = capture
        monkeypatch.setattr(time, "monotonic_ns", lambda: TIME_BASE)
        client._on_send_timer()
        assert published[0]["send_time_ns"] > 1_000_000_000_000_000  # > 1e15


# ---------------------------------------------------------------------------
# B. Receive-Side Sanity Checks
# ---------------------------------------------------------------------------

class TestReceiveSanityChecks:
    def test_malformed_json_discarded(self, client):
        """Non-JSON payload increments malformed_count, no crash."""
        msg = MagicMock()
        msg.data = "not valid json{{{"
        initial = client._malformed_count
        client._on_response(msg)
        assert client._malformed_count == initial + 1

    def test_missing_seq_field_discarded(self, client):
        """JSON without seq field increments malformed_count."""
        msg = MagicMock()
        msg.data = json.dumps({"v": 1, "probe_id": "x"})
        initial = client._malformed_count
        client._on_response(msg)
        assert client._malformed_count == initial + 1

    def test_wrong_protocol_version_discarded(self, client):
        """Response with wrong v field increments malformed_count."""
        msg = MagicMock()
        msg.data = json.dumps({"v": 999, "seq": 1})
        initial = client._malformed_count
        client._on_response(msg)
        assert client._malformed_count == initial + 1

    def test_response_for_unknown_seq_discarded(self, client):
        """Response with a seq we never sent increments unknown_seq_count."""
        msg = MagicMock()
        msg.data = json.dumps({"v": 1, "seq": 9999})
        initial = client._unknown_seq_count
        client._on_response(msg)
        assert client._unknown_seq_count == initial + 1
        assert len(client._rtt_window) == 0

    def test_stale_response_rejected(self, client, monkeypatch):
        """Response with RTT exceeding timeout_ms is rejected as stale."""
        send_ns = TIME_BASE
        client._outstanding[1] = send_ns

        stale_rtt_ns = 600 * 1_000_000  # 600ms > 500ms timeout
        monkeypatch.setattr(time, "monotonic_ns", lambda: send_ns + stale_rtt_ns)

        msg = MagicMock()
        msg.data = json.dumps({"v": 1, "seq": 1})
        initial = client._stale_count
        client._on_response(msg)
        assert client._stale_count == initial + 1
        assert 1 not in client._outstanding

    def test_seq_zero_or_negative_discarded(self, client):
        """seq=0 or seq=-1 is treated as malformed."""
        msg = MagicMock()
        msg.data = json.dumps({"v": 1, "seq": 0})
        initial = client._malformed_count
        client._on_response(msg)
        assert client._malformed_count == initial + 1

        msg.data = json.dumps({"v": 1, "seq": -1})
        client._on_response(msg)
        assert client._malformed_count == initial + 2

    def test_non_dict_payload_discarded(self, client):
        """A JSON array (not object) is treated as malformed."""
        msg = MagicMock()
        msg.data = json.dumps([1, 2, 3])
        initial = client._malformed_count
        client._on_response(msg)
        assert client._malformed_count == initial + 1


# ---------------------------------------------------------------------------
# C. Bounded Storage and Timeout
# ---------------------------------------------------------------------------

class TestBoundedStorageAndTimeout:
    def test_outstanding_map_evicts_oldest(self, client, monkeypatch):
        """When max_outstanding is reached, oldest entry is evicted
        and marked as lost in results window."""
        client._max_outstanding = 5
        monkeypatch.setattr(time, "monotonic_ns", lambda: TIME_BASE)

        for i in range(6):
            client._on_send_timer()

        assert len(client._outstanding) <= 5

    def test_cleanup_timer_removes_expired(self, client, monkeypatch):
        """Cleanup sweep removes entries older than timeout_ms."""
        old_time = TIME_BASE
        client._outstanding[1] = old_time
        client._outstanding[2] = old_time

        future_time = old_time + (600 * 1_000_000)
        monkeypatch.setattr(time, "monotonic_ns", lambda: future_time)

        client._on_cleanup_timer()
        assert 1 not in client._outstanding
        assert 2 not in client._outstanding

    def test_timeout_ms_from_constructor_respected(self, mock_ros_node, monkeypatch):
        """ProbeClient with timeout_ms=200 rejects responses >200ms."""
        from adaptive_bridge.utils.probes import ProbeClient

        c = ProbeClient(
            node_name="test_timeout",
            rate_hz=5.0,
            window_size=10,
            timeout_ms=200,
        )
        c._pub = MagicMock()

        send_ns = TIME_BASE
        c._outstanding[1] = send_ns

        within_timeout = send_ns + (150 * 1_000_000)
        monkeypatch.setattr(time, "monotonic_ns", lambda: within_timeout)

        msg = MagicMock()
        msg.data = json.dumps({"v": 1, "seq": 1})
        c._on_response(msg)
        assert c._stale_count == 0
        assert c._recv_total == 1

    def test_timeout_ms_rejects_slow_responses(self, mock_ros_node, monkeypatch):
        """ProbeClient with timeout_ms=100 rejects responses >100ms."""
        from adaptive_bridge.utils.probes import ProbeClient

        c = ProbeClient(
            node_name="test_timeout_slow",
            rate_hz=5.0,
            window_size=10,
            timeout_ms=100,
        )
        c._pub = MagicMock()

        send_ns = TIME_BASE
        c._outstanding[1] = send_ns

        beyond_timeout = send_ns + (150 * 1_000_000)
        monkeypatch.setattr(time, "monotonic_ns", lambda: beyond_timeout)

        msg = MagicMock()
        msg.data = json.dumps({"v": 1, "seq": 1})
        c._on_response(msg)
        assert c._stale_count == 1

    def test_default_timeout_applied(self, mock_ros_node):
        """ProbeClient without explicit timeout uses default 500ms."""
        from adaptive_bridge.utils.probes import ProbeClient

        c = ProbeClient(
            node_name="test_default_timeout",
            rate_hz=5.0,
            window_size=10,
        )
        c._pub = MagicMock()
        assert c._timeout_ms == 500


# ---------------------------------------------------------------------------
# D. Rolling Metrics Computation
# ---------------------------------------------------------------------------

class TestRollingMetrics:
    def test_rtt_mean_computed_correctly(self, client, monkeypatch):
        """Inject known RTTs and verify mean."""
        rtts = [10, 20, 30, 40, 50]
        for i, rtt_ms in enumerate(rtts, 1):
            send_ns = TIME_BASE
            recv_ns = send_ns + int(rtt_ms * 1_000_000)
            client._outstanding[i] = send_ns
            monkeypatch.setattr(time, "monotonic_ns", lambda ns=recv_ns: ns)
            msg = MagicMock()
            msg.data = json.dumps({"v": 1, "seq": i})
            client._on_response(msg)

        stats = client.get_stats()
        assert stats["rtt"]["count"] == 5
        assert stats["rtt"]["mean_ms"] == 30.0

    def test_rtt_p95_computed_correctly(self, mock_ros_node, monkeypatch):
        """Inject known RTTs and verify p95 is correct."""
        from adaptive_bridge.utils.probes import ProbeClient

        c = ProbeClient(
            node_name="test_p95",
            rate_hz=5.0,
            window_size=20,
            timeout_ms=500,
        )
        c._pub = MagicMock()

        rtts = [float(i) for i in range(1, 21)]  # 1..20 ms
        for i, rtt_ms in enumerate(rtts, 1):
            send_ns = TIME_BASE
            recv_ns = send_ns + int(rtt_ms * 1_000_000)
            c._outstanding[i] = send_ns
            monkeypatch.setattr(time, "monotonic_ns", lambda ns=recv_ns: ns)
            msg = MagicMock()
            msg.data = json.dumps({"v": 1, "seq": i})
            c._on_response(msg)

        stats = c.get_stats()
        assert stats["rtt"]["count"] == 20
        assert stats["rtt"]["p95_ms"] == 19.0

    def test_jitter_mean_computed_correctly(self, client, monkeypatch):
        """Inject alternating RTTs and verify jitter is non-zero."""
        rtts = [10.0, 20.0, 10.0, 20.0, 10.0]
        for i, rtt_ms in enumerate(rtts, 1):
            send_ns = TIME_BASE
            recv_ns = send_ns + int(rtt_ms * 1_000_000)
            client._outstanding[i] = send_ns
            monkeypatch.setattr(time, "monotonic_ns", lambda ns=recv_ns: ns)
            msg = MagicMock()
            msg.data = json.dumps({"v": 1, "seq": i})
            client._on_response(msg)

        stats = client.get_stats()
        assert stats["jitter"]["count"] > 0
        jitter_mean = stats["jitter"]["mean_ms"]
        assert jitter_mean > 0.0

    def test_loss_rate_from_sliding_window_not_cumulative(self, client):
        """Loss rate reflects only recent results_window, not lifetime totals."""
        client._window_size = 5
        client._results_window = deque([True, True, True, False, False], maxlen=5)
        client._sent_total = 1000
        client._recv_total = 900

        stats = client.get_stats()
        assert stats["loss_rate"] == 0.4

    def test_jitter_zero_when_rtt_constant(self, client, monkeypatch):
        """Identical RTTs produce zero jitter."""
        for i in range(5):
            send_ns = TIME_BASE
            recv_ns = send_ns + int(20 * 1_000_000)
            client._outstanding[i + 1] = send_ns
            monkeypatch.setattr(time, "monotonic_ns", lambda ns=recv_ns: ns)
            msg = MagicMock()
            msg.data = json.dumps({"v": 1, "seq": i + 1})
            client._on_response(msg)

        stats = client.get_stats()
        assert stats["jitter"]["mean_ms"] == 0.0


# ---------------------------------------------------------------------------
# E. get_stats() Contract
# ---------------------------------------------------------------------------

class TestGetStats:
    def test_get_stats_returns_all_required_keys(self, client):
        """get_stats() includes all top-level keys."""
        stats = client.get_stats()
        required = {
            "sender_id", "protocol_version", "window_size",
            "sent_total", "recv_total", "loss_rate", "rtt",
            "jitter", "errors", "outstanding_count", "last_seq",
        }
        assert required.issubset(set(stats.keys()))

    def test_get_stats_rtt_subkeys(self, client):
        """RTT dict has mean_ms, p95_ms, count."""
        client._rtt_window = deque([10.0, 20.0, 30.0], maxlen=10)
        stats = client.get_stats()
        rtt = stats["rtt"]
        assert set(rtt.keys()) == {"count", "mean_ms", "p95_ms"}
        assert rtt["count"] == 3

    def test_get_stats_loss_rate_is_float(self, client):
        """loss_rate is a float between 0.0 and 1.0."""
        stats = client.get_stats()
        assert isinstance(stats["loss_rate"], float)
        assert 0.0 <= stats["loss_rate"] <= 1.0

    def test_get_stats_empty_state_no_crash(self, client):
        """Calling get_stats() with no sent probes returns all zeros, no crash."""
        stats = client.get_stats()
        assert stats["sent_total"] == 0
        assert stats["recv_total"] == 0
        assert stats["loss_rate"] == 0.0
        assert stats["rtt"]["count"] == 0
        assert stats["jitter"]["count"] == 0
        assert stats["last_seq"] == 0


# ---------------------------------------------------------------------------
# F. ProbeResponder Tests
# ---------------------------------------------------------------------------

class TestProbeResponder:
    def test_responder_echoes_correct_fields(self, responder, monkeypatch):
        """Responder echoes seq and probe_id from request."""
        responses = []

        def capture(msg):
            responses.append(json.loads(msg.data))

        responder._pub.publish.side_effect = capture
        monkeypatch.setattr(time, "monotonic_ns", lambda: TIME_BASE)

        request = MagicMock()
        request.data = json.dumps({"v": 1, "seq": 42, "probe_id": "client_1"})
        responder._on_request(request)

        r = responses[0]
        assert r["v"] == 1
        assert r["seq"] == 42
        assert r["probe_id"] == "client_1"

    def test_responder_injects_timestamps(self, responder, monkeypatch):
        """Response contains recv_time_ns, reply_time_ns, response_send_time_ns."""
        call_count = [0]
        times = [TIME_BASE, TIME_BASE + 500000]

        def fake_monotonic_ns():
            t = times[call_count[0]]
            call_count[0] += 1
            return t

        responses = []

        def capture(msg):
            responses.append(json.loads(msg.data))

        responder._pub.publish.side_effect = capture
        monkeypatch.setattr(time, "monotonic_ns", fake_monotonic_ns)

        request = MagicMock()
        request.data = json.dumps({"v": 1, "seq": 1, "probe_id": "x"})
        responder._on_request(request)

        r = responses[0]
        assert r["recv_time_ns"] == TIME_BASE
        assert r["reply_time_ns"] == TIME_BASE + 500000
        assert r["response_send_time_ns"] == TIME_BASE + 500000

    def test_responder_responder_id_in_payload(self, responder, monkeypatch):
        """responder_id field matches node name."""
        responses = []

        def capture(msg):
            responses.append(json.loads(msg.data))

        responder._pub.publish.side_effect = capture
        monkeypatch.setattr(time, "monotonic_ns", lambda: TIME_BASE)

        request = MagicMock()
        request.data = json.dumps({"v": 1, "seq": 1, "probe_id": "x"})
        responder._on_request(request)

        assert responses[0]["responder_id"] == "test_responder"

    def test_responder_handles_malformed_request(self, responder):
        """Non-JSON request triggers a warning logger call, no crash, no publish."""
        call_count = [0]

        def capture(_msg):
            call_count[0] += 1

        responder._pub.publish.side_effect = capture

        request = MagicMock()
        request.data = "garbage{{{{"

        responder._on_request(request)
        assert call_count[0] == 0


# ---------------------------------------------------------------------------
# End-to-end: sender -> responder -> client
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_full_round_trip(self, mock_ros_node, monkeypatch):
        """Simulate ProbeClient sending, ProbeResponder responding,
        and ProbeClient computing RTT — all mocked."""
        from adaptive_bridge.utils.probes import ProbeClient, ProbeResponder

        client = ProbeClient(
            node_name="e2e_client",
            rate_hz=5.0,
            window_size=10,
            timeout_ms=500,
        )
        client._pub = MagicMock()

        responder = ProbeResponder(node_name="e2e_responder")
        responder._pub = MagicMock()

        ts_counter = [TIME_BASE]

        def fake_monotonic_ns():
            ts_counter[0] += 1_000_000  # 1ms per call
            return ts_counter[0]

        monkeypatch.setattr(time, "monotonic_ns", fake_monotonic_ns)

        # Step 1: Client sends probe request
        request_msgs = []

        def capture_request(msg):
            request_msgs.append(msg)

        client._pub.publish.side_effect = capture_request
        client._on_send_timer()

        assert len(request_msgs) == 1

        # Step 2: Responder receives and responds
        response_msgs = []

        def capture_response(msg):
            response_msgs.append(msg)

        responder._pub.publish.side_effect = capture_response
        responder._on_request(request_msgs[0])

        assert len(response_msgs) == 1

        # Step 3: Client receives response and computes RTT
        client._on_response(response_msgs[0])

        assert client._recv_total == 1
        assert len(client._rtt_window) == 1
        assert client._rtt_window[0] > 0.0
