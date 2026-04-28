# diagnostics.py
"""
Diagnostics publisher for Adaptive Bridge.

Exports a simple JSON metrics message periodically to:
  /adaptive_bridge/diagnostics   (std_msgs/String)

Responsibilities:
  - Track forwarded message counts (critical/noncritical).
  - Track last-forward timestamp.
  - Optionally record simple latency samples (caller can call record_latency()).
  - Publish an aggregated JSON once per `publish_interval` seconds.

Why:
  - Provides a single, simple diagnostics stream for WS2's metrics logger.
  - Keeps runtime overhead very low; JSON strings are easy to parse in tests.
"""

from collections import deque
import json
import time
from typing import Deque, Dict, List, Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from .models import TopicCounters, TopicRuntimeState


class DiagnosticsPublisher(Node):
    """
    Node to collect and publish lightweight diagnostics for the adaptive bridge.

    Public API (used by the Proxy / Classifier):
      - increment_forwarded(path: str)               # path: "critical" or "noncritical"
      - record_latency(path: str, ms: float)        # optional latency samples
      - start() / stop()                             # manage rclpy timers if used standalone
    """

    def __init__(self, node_name: str = "adaptive_bridge_diagnostics", publish_interval: float = 1.0):
        super().__init__(node_name)

        # Counters for forwarded messages
        self._counters: Dict[str, int] = {"critical": 0, "noncritical": 0}

        # Last forwarded timestamp (wall time seconds)
        self._last_forward_ts: Optional[float] = None

        # Sliding windows for latency per path
        self._latency_windows: Dict[str, Deque[float]] = {
            "critical": deque(maxlen=100),
            "noncritical": deque(maxlen=100),
        }

        # Exposed publish frequency
        self._publish_interval = float(publish_interval)
        self._topic_states: Dict[str, TopicRuntimeState] = {}

        # ROS publisher for diagnostics JSON
        self._pub = self.create_publisher(String, "/adaptive_bridge/diagnostics", 10)

        # Timer to emit diagnostics periodically
        self._timer = self.create_timer(self._publish_interval, self._on_timer)

        # Internal last publish (avoid publishing identical timestamps rapidly)
        self.get_logger().debug(f"DiagnosticsPublisher started, publish_interval={self._publish_interval}s")

    # -----------------------
    # Public helper methods
    # -----------------------
    def increment_forwarded(self, path: str) -> None:
        """Increment the forwarded message counter for a given path."""
        if path not in self._counters:
            self._counters[path] = 0
        self._counters[path] += 1
        self._last_forward_ts = time.time()

    def record_latency(self, path: str, ms: float) -> None:
        """Record a latency sample in milliseconds for a named path."""
        if path not in self._latency_windows:
            self._latency_windows[path] = deque(maxlen=100)
        self._latency_windows[path].append(float(ms))

    def ingest_topic_counters(self, topic_id: str, counters: TopicCounters) -> None:
        """Store per-topic counters from shared Step 3 models."""
        if topic_id not in self._topic_states:
            return
        self._topic_states[topic_id].counters = counters

    def ingest_topic_state(self, state: TopicRuntimeState) -> None:
        """Store full per-topic runtime state from shared Step 3 models."""
        self._topic_states[state.route.topic_id] = state

    # -----------------------
    # Internal helpers
    # -----------------------
    def _compute_stats(self, samples: Deque[float]) -> Dict[str, float]:
        """Return simple stats from a deque of floats (ms)."""
        if not samples:
            return {"count": 0, "mean": 0.0, "p95": 0.0}
        arr = list(samples)
        arr_sorted = sorted(arr)
        n = len(arr_sorted)
        mean = sum(arr_sorted) / n
        # p95 approx:
        idx95 = int(max(0, min(n - 1, round(0.95 * (n - 1)))))
        p95 = arr_sorted[idx95]
        return {"count": n, "mean": mean, "p95": p95}

    def _gather_payload(self) -> Dict:
        """Build the diagnostics payload as a serializable dict."""
        payload = {
            "ts_wall": time.time(),
            "counters": dict(self._counters),
            "last_forward_ts": self._last_forward_ts,
            "latency": {
                p: self._compute_stats(self._latency_windows.get(p, deque()))
                for p in self._latency_windows
            },
            "topics": {
                topic_id: state.to_dict() for topic_id, state in self._topic_states.items()
            },
        }
        return payload

    # -----------------------
    # Timer callback
    # -----------------------
    def _on_timer(self) -> None:
        """Periodic timer: publish diagnostics JSON to /adaptive_bridge/diagnostics."""
        payload = self._gather_payload()
        msg = String()
        msg.data = json.dumps(payload)
        try:
            self._pub.publish(msg)
            self.get_logger().debug("Diagnostics published")
        except Exception as e:
            # don't raise; diagnostics must never crash the bridge
            self.get_logger().error(f"Failed to publish diagnostics: {e}")

    # -----------------------
    # Standard Node lifecycle helpers
    # -----------------------
    def start(self) -> None:
        """Alias to ensure node is active (no-op; node timer already started)."""
        self.get_logger().info("DiagnosticsPublisher start requested (no-op)")

    def stop(self) -> None:
        """Cancel timer; keep internal data for inspection."""
        self._timer.cancel()
        self.get_logger().info("DiagnosticsPublisher stopped")
        

def main(args=None):
    rclpy.init(args=args)
    node = DiagnosticsPublisher()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
