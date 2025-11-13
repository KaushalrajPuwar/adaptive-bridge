# utils/probes.py
"""
Probe utilities: ProbeClient and ProbeResponder.

ProbeClient:
  - Periodically publishes probe requests with sequence number and timestamp on topic:
      /adaptive_bridge/probe_req
  - Listens for probe responses on:
      /adaptive_bridge/probe_resp
  - Computes per-peer RTT and loss estimates in a small sliding window.

ProbeResponder:
  - Simple echo server: subscribes to /adaptive_bridge/probe_req and republishes the same payload on /adaptive_bridge/probe_resp
  - Use this on subscriber/test nodes to ensure probes are responded to.

Message format (JSON string in std_msgs/String):
  {"seq": <int>, "ts": <float>, "src": "<node_id>"}
"""

import json
import time
from collections import deque
from typing import Dict, Deque, Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class ProbeClient(Node):
    """
    Active probe sender + receiver.

    Basic algorithm:
      - Maintain a monotonic sequence counter.
      - Every `rate_hz` seconds publish {seq, ts, src} on /adaptive_bridge/probe_req.
      - When a response arrives on /adaptive_bridge/probe_resp with same seq and src, compute RTT.
      - Maintain sliding window deque of last N RTTs and counts for loss estimation.

    Public API:
      - start(), stop()  -> manage timers
      - get_stats() -> returns dict with {"sent", "recv", "loss_rate", "rtt_mean_ms", "rtt_p95_ms"}
    """

    def __init__(self, node_name: str = "adaptive_bridge_probe_client", rate_hz: float = 5.0, window_size: int = 50):
        super().__init__(node_name)
        self._rate_hz = float(rate_hz)
        self._window_size = int(window_size)
        self._seq = 0

        # sent map: seq -> send_ts
        self._sent_map: Dict[int, float] = {}

        # sliding window of RTT samples in ms
        self._rtt_window: Deque[float] = deque(maxlen=self._window_size)

        # counters
        self._sent_total = 0
        self._recv_total = 0

        # publisher and subscriber
        self._pub = self.create_publisher(String, "/adaptive_bridge/probe_req", 10)
        self._sub = self.create_subscription(String, "/adaptive_bridge/probe_resp", self._on_response, 10)

        # timer (not started until start() is called)
        self._timer = None

        # src id: use node name by default
        self._src_id = node_name

        self.get_logger().info(f"ProbeClient initialized rate={self._rate_hz}Hz window={self._window_size}")

    # -----------------------
    # Public API
    # -----------------------
    def start(self) -> None:
        """Start periodic probe sending timer."""
        if self._timer is None:
            period = 1.0 / max(0.0001, self._rate_hz)
            self._timer = self.create_timer(period, self._on_timer)
            self.get_logger().info("ProbeClient started")

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
            self.get_logger().info("ProbeClient stopped")

    def get_stats(self) -> Dict:
        """Return aggregate stats computed from internal counters and RTT window."""
        loss_rate = 0.0
        if self._sent_total > 0:
            loss_rate = max(0.0, 1.0 - (self._recv_total / float(self._sent_total)))
        rtt_stats = {"count": 0, "mean_ms": 0.0, "p95_ms": 0.0}
        if len(self._rtt_window) > 0:
            arr = sorted(list(self._rtt_window))
            n = len(arr)
            rtt_stats["count"] = n
            rtt_stats["mean_ms"] = sum(arr) / n
            idx95 = int(max(0, min(n - 1, round(0.95 * (n - 1)))))
            rtt_stats["p95_ms"] = arr[idx95]
        return {
            "sent": self._sent_total,
            "recv": self._recv_total,
            "loss_rate": loss_rate,
            "rtt": rtt_stats,
            "last_seq": self._seq
        }

    # -----------------------
    # Internal callbacks
    # -----------------------
    def _on_timer(self) -> None:
        """Publish a probe request with seq and timestamp."""
        self._seq += 1
        seq = self._seq
        ts = time.time()
        payload = {"seq": seq, "ts": ts, "src": self._src_id}
        msg = String()
        msg.data = json.dumps(payload)
        try:
            self._sent_map[seq] = ts
            self._sent_total += 1
            self._pub.publish(msg)
        except Exception as e:
            self.get_logger().error(f"Probe publish failed: {e}")

    def _on_response(self, msg: String) -> None:
        """Handle probe replies and compute RTT if matching a sent seq."""
        try:
            data = json.loads(msg.data)
            seq = int(data.get("seq", 0))
            # In our simple setup, responder will echo src back; ignore if src mismatch
            # Compute RTT if we have a send timestamp for this seq
            send_ts = self._sent_map.pop(seq, None)
            if send_ts is not None:
                rtt_s = time.time() - float(send_ts)
                rtt_ms = rtt_s * 1000.0
                self._rtt_window.append(rtt_ms)
                self._recv_total += 1
            # else: response for unknown seq -> ignore
        except Exception as e:
            self.get_logger().error(f"Malformed probe response: {e}")

    # -----------------------
    # Standard node main
    # -----------------------
    def destroy(self) -> None:
        try:
            self.stop()
        except Exception:
            pass
        super().destroy_node()


class ProbeResponder(Node):
    """
    A minimal responder for probe requests. Useful to run on subscriber/test nodes.

    Behavior:
      - Subscribe to /adaptive_bridge/probe_req and immediately re-publish the same JSON to /adaptive_bridge/probe_resp
      - Keeps processing minimal and stateless (just echo)
    """

    def __init__(self, node_name: str = "adaptive_bridge_probe_responder"):
        super().__init__(node_name)
        self._sub = self.create_subscription(String, "/adaptive_bridge/probe_req", self._on_req, 10)
        self._pub = self.create_publisher(String, "/adaptive_bridge/probe_resp", 10)
        self.get_logger().info("ProbeResponder started")

    def _on_req(self, msg: String) -> None:
        # echo the same message onto the response topic
        try:
            self._pub.publish(msg)
        except Exception as e:
            self.get_logger().error(f"Failed to echo probe: {e}")

    def destroy(self) -> None:
        super().destroy_node()


# entrypoint convenience
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
    # quick manual mode: run client
    _probe_client_main()
