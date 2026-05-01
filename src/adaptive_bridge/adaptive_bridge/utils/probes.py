# utils/probes.py
"""
Probe utilities: ProbeClient and ProbeResponder (Step 8 — Hardened Protocol v1).

ProbeClient:
  - Periodically publishes versioned probe requests with monotonic nanosecond
    timestamps, sequence number, sender ID, and probe ID on a configurable
    request topic.
  - Listens for probe responses on a configurable response topic.
  - Enforces receive-side sanity checks: malformed JSON, stale responses,
    unknown sequences, wrong protocol version.
  - Maintains bounded outstanding-sequence map to prevent unbounded memory growth.
  - Computes rolling-window metrics: mean RTT, p95 RTT, loss rate (windowed),
    and jitter estimate.
  - Configurable probe timeout via `timeout_ms` in ProbeConfig.

ProbeResponder:
  - Subscribes to probe request topic and responds with versioned response
    payloads containing receiver-side timestamps (recv_time_ns, reply_time_ns,
    response_send_time_ns) and responder identity.

Probe request message format (JSON via std_msgs/String):
  {"v": 1, "seq": <int>, "send_time_ns": <int>, "sender_id": "<str>", "probe_id": "<str>"}

Probe response message format (JSON via std_msgs/String):
  {"v": 1, "seq": <int>, "probe_id": "<str>",
   "recv_time_ns": <int>, "reply_time_ns": <int>, "response_send_time_ns": <int>,
   "responder_id": "<str>"}
"""

import json
import time
from collections import deque
from typing import Deque, Dict, Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from ..classifier_types import ProbeMetrics

PROBE_PROTOCOL_VERSION = 1
PROBE_REQ_DEFAULT_TOPIC = "/adaptive_bridge/probe_req"
PROBE_RESP_DEFAULT_TOPIC = "/adaptive_bridge/probe_resp"
DEFAULT_TIMEOUT_MS = 500
DEFAULT_WINDOW_SIZE = 50
DEFAULT_RATE_HZ = 5.0


def stats_to_probe_metrics(stats: dict) -> ProbeMetrics:
    """Convert ProbeClient.get_stats() dict to ProbeMetrics dataclass.

    Bridges the probe subsystem's rolling-window aggregate dict
    into the classifier's typed input contract.
    """
    rtt = stats.get("rtt", {})
    jitter = stats.get("jitter", {})

    return ProbeMetrics(
        avg_rtt_ms=float(rtt.get("mean_ms", 0.0)),
        loss=float(stats.get("loss_rate", 0.0)),
        sample_count=int(rtt.get("count", 0)),
        p95_rtt_ms=float(rtt.get("p95_ms", 0.0)),
        jitter_ms=float(jitter.get("mean_ms", 0.0)),
    )


class ProbeClient(Node):
    """
    Hardened active probe sender + receiver (Step 8).

    Features:
      - Versioned protocol (v=1) with monotonic nanosecond timestamps
      - Bounded outstanding sequence map (prevents unbounded memory growth)
      - Sliding-window loss rate (not lifetime-cumulative)
      - Jitter estimate (abs diff of consecutive RTT samples)
      - Configurable timeout with stale response rejection
      - Receive-side sanity checks: malformed JSON, unknown seq, wrong version

    Public API:
      - start(), stop()  -> manage timers
      - get_stats() -> structured metrics dict compatible with classifier input schema
    """

    def __init__(
        self,
        node_name: str = "adaptive_bridge_probe_client",
        rate_hz: float = DEFAULT_RATE_HZ,
        window_size: int = DEFAULT_WINDOW_SIZE,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        request_topic: str = PROBE_REQ_DEFAULT_TOPIC,
        response_topic: str = PROBE_RESP_DEFAULT_TOPIC,
    ):
        super().__init__(node_name)
        self._rate_hz = float(rate_hz)
        self._window_size = int(window_size)
        self._timeout_ms = max(1, int(timeout_ms))
        self._protocol_version = PROBE_PROTOCOL_VERSION
        self._sender_id = node_name

        self._seq_counter = 0

        self._max_outstanding = self._window_size * 3
        self._outstanding: Dict[int, int] = {}

        self._rtt_window: Deque[float] = deque(maxlen=self._window_size)
        self._jitter_window: Deque[float] = deque(maxlen=self._window_size)
        self._results_window: Deque[bool] = deque(maxlen=self._window_size)

        self._sent_total = 0
        self._recv_total = 0
        self._malformed_count = 0
        self._stale_count = 0
        self._unknown_seq_count = 0

        self._pub = self.create_publisher(String, request_topic, 10)
        self._sub = self.create_subscription(String, response_topic, self._on_response, 10)

        self._send_timer = None
        self._cleanup_timer = None

        self.get_logger().info(
            f"ProbeClient v{self._protocol_version} initialized "
            f"rate={self._rate_hz}Hz window={self._window_size} "
            f"timeout={self._timeout_ms}ms"
        )

    # -----------------------
    # Public API
    # -----------------------
    def start(self) -> None:
        if self._send_timer is None:
            period = 1.0 / max(0.0001, self._rate_hz)
            self._send_timer = self.create_timer(period, self._on_send_timer)
            self.get_logger().info("ProbeClient send timer started")

        if self._cleanup_timer is None:
            cleanup_period = max(0.1, self._timeout_ms / 2000.0)
            self._cleanup_timer = self.create_timer(cleanup_period, self._on_cleanup_timer)
            self.get_logger().info("ProbeClient cleanup timer started")

    def stop(self) -> None:
        if self._send_timer is not None:
            self._send_timer.cancel()
            self._send_timer = None
        if self._cleanup_timer is not None:
            self._cleanup_timer.cancel()
            self._cleanup_timer = None
        self.get_logger().info("ProbeClient stopped")

    def get_stats(self) -> Dict:
        loss_rate = 0.0
        if len(self._results_window) > 0:
            received = sum(1 for ok in self._results_window if ok)
            loss_rate = max(0.0, 1.0 - (received / len(self._results_window)))

        rtt_stats = {"count": 0, "mean_ms": 0.0, "p95_ms": 0.0}
        if len(self._rtt_window) > 0:
            arr = sorted(list(self._rtt_window))
            n = len(arr)
            rtt_stats["count"] = n
            rtt_stats["mean_ms"] = round(sum(arr) / n, 2)
            idx95 = int(max(0, min(n - 1, round(0.95 * (n - 1)))))
            rtt_stats["p95_ms"] = round(arr[idx95], 2)

        jitter_stats = {"count": 0, "mean_ms": 0.0, "p95_ms": 0.0}
        if len(self._jitter_window) > 0:
            arr = sorted(list(self._jitter_window))
            n = len(arr)
            jitter_stats["count"] = n
            jitter_stats["mean_ms"] = round(sum(arr) / n, 2)
            idx95 = int(max(0, min(n - 1, round(0.95 * (n - 1)))))
            jitter_stats["p95_ms"] = round(arr[idx95], 2)

        error_stats: Dict[str, int] = {}
        if self._malformed_count > 0:
            error_stats["malformed"] = self._malformed_count
        if self._stale_count > 0:
            error_stats["stale"] = self._stale_count
        if self._unknown_seq_count > 0:
            error_stats["unknown_seq"] = self._unknown_seq_count

        return {
            "sender_id": self._sender_id,
            "protocol_version": self._protocol_version,
            "window_size": self._window_size,
            "sent_total": self._sent_total,
            "recv_total": self._recv_total,
            "loss_rate": round(loss_rate, 4),
            "rtt": rtt_stats,
            "jitter": jitter_stats,
            "errors": error_stats,
            "outstanding_count": len(self._outstanding),
            "last_seq": self._seq_counter,
        }

    # -----------------------
    # Internal: send probe request
    # -----------------------
    def _on_send_timer(self) -> None:
        self._seq_counter += 1
        seq = self._seq_counter
        send_time_ns = time.monotonic_ns()

        if len(self._outstanding) >= self._max_outstanding:
            oldest_seq = next(iter(self._outstanding))
            del self._outstanding[oldest_seq]
            self._results_window.append(False)

        payload = {
            "v": self._protocol_version,
            "seq": seq,
            "send_time_ns": send_time_ns,
            "sender_id": self._sender_id,
            "probe_id": self._sender_id,
        }
        msg = String()
        msg.data = json.dumps(payload)
        try:
            self._outstanding[seq] = send_time_ns
            self._sent_total += 1
            self._pub.publish(msg)
        except Exception as e:
            self.get_logger().error(f"Probe publish failed: {e}")

    # -----------------------
    # Internal: receive probe response
    # -----------------------
    def _on_response(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
        except (json.JSONDecodeError, TypeError) as e:
            self._malformed_count += 1
            self.get_logger().warning(f"Malformed probe response (invalid JSON): {e}")
            return

        if not isinstance(data, dict):
            self._malformed_count += 1
            self.get_logger().warning("Malformed probe response (not a JSON object)")
            return

        seq = data.get("seq")
        if not isinstance(seq, int) or seq <= 0:
            self._malformed_count += 1
            self.get_logger().warning("Malformed probe response (missing or invalid seq)")
            return

        if data.get("v") != self._protocol_version:
            self._malformed_count += 1
            self.get_logger().warning(
                f"Probe response protocol version mismatch: "
                f"expected {self._protocol_version}, got {data.get('v')}"
            )
            return

        send_time_ns = self._outstanding.pop(seq, None)
        if send_time_ns is None:
            self._unknown_seq_count += 1
            return

        now_ns = time.monotonic_ns()
        rtt_ns = now_ns - send_time_ns
        rtt_ms = rtt_ns / 1_000_000.0

        if rtt_ms > self._timeout_ms:
            self._stale_count += 1
            self._results_window.append(False)
            return

        if len(self._rtt_window) > 0:
            jitter_ms = abs(rtt_ms - self._rtt_window[-1])
            self._jitter_window.append(jitter_ms)

        self._rtt_window.append(rtt_ms)
        self._recv_total += 1
        self._results_window.append(True)

    # -----------------------
    # Internal: cleanup timed-out outstanding probes
    # -----------------------
    def _on_cleanup_timer(self) -> None:
        now_ns = time.monotonic_ns()
        timeout_ns = self._timeout_ms * 1_000_000
        expired = [
            seq for seq, send_ns in self._outstanding.items()
            if now_ns - send_ns > timeout_ns
        ]
        for seq in expired:
            del self._outstanding[seq]
            self._results_window.append(False)

    # -----------------------
    # Lifecycle
    # -----------------------
    def destroy(self) -> None:
        try:
            self.stop()
        except Exception:
            pass
        super().destroy_node()


class ProbeResponder(Node):
    """
    Hardened probe responder (Step 8).

    Subscribes to probe request topic and publishes versioned response payloads
    with receiver-side timestamps and responder identity.

    Response payload fields:
      - v: protocol version (echoed from request)
      - seq: sequence number (echoed from request)
      - probe_id: probe identifier (echoed from request)
      - recv_time_ns: monotonic time when request was received
      - reply_time_ns: monotonic time right before response is published
      - response_send_time_ns: same as reply_time_ns (immediate send)
      - responder_id: this node's name
    """

    def __init__(
        self,
        node_name: str = "adaptive_bridge_probe_responder",
        request_topic: str = PROBE_REQ_DEFAULT_TOPIC,
        response_topic: str = PROBE_RESP_DEFAULT_TOPIC,
    ):
        super().__init__(node_name)
        self._responder_id = node_name
        self._sub = self.create_subscription(String, request_topic, self._on_request, 10)
        self._pub = self.create_publisher(String, response_topic, 10)
        self.get_logger().info("ProbeResponder v1 started")

    def _on_request(self, msg: String) -> None:
        recv_time_ns = time.monotonic_ns()

        try:
            data = json.loads(msg.data)
        except (json.JSONDecodeError, TypeError):
            self.get_logger().warning("ProbeResponder received malformed JSON request, skipping")
            return

        if not isinstance(data, dict):
            self.get_logger().warning("ProbeResponder received non-object JSON, skipping")
            return

        reply_time_ns = time.monotonic_ns()

        response = String()
        response.data = json.dumps({
            "v": data.get("v", PROBE_PROTOCOL_VERSION),
            "seq": data.get("seq", 0),
            "probe_id": data.get("probe_id", ""),
            "recv_time_ns": recv_time_ns,
            "reply_time_ns": reply_time_ns,
            "response_send_time_ns": reply_time_ns,
            "responder_id": self._responder_id,
        })

        try:
            self._pub.publish(response)
        except Exception as e:
            self.get_logger().error(f"Failed to publish probe response: {e}")

    def destroy(self) -> None:
        super().destroy_node()


def _probe_client_main():
    rclpy.init()
    client = ProbeClient()
    client.start()
    try:
        rclpy.spin(client)
    finally:
        client.destroy()
        rclpy.shutdown()


def _probe_responder_main():
    rclpy.init()
    node = ProbeResponder()
    try:
        rclpy.spin(node)
    finally:
        node.destroy()
        rclpy.shutdown()


if __name__ == "__main__":
    _probe_client_main()
