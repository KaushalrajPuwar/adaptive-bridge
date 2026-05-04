#!/usr/bin/env python3
"""
Evaluation publisher node — publishes messages at a fixed rate.

Env vars:
  PUBLISH_TOPIC      – topic name (default /scan)
  PUBLISH_RATE_HZ    – publish rate in Hz (default 30)
  PUBLISH_MSG_TYPE   – ROS 2 message type string, e.g. "sensor_msgs/LaserScan"
                       (default: sensor_msgs/LaserScan)

Runs as a standalone script (not a ROS2 package node).
QoS: RELIABLE + KEEP_ALL — triggers DDS backpressure on slow subscribers.

Note: message construction is LaserScan-specific by default.  To use a
different message type, set PUBLISH_MSG_TYPE and override the _build_msg()
method or provide a message factory callback.
"""
import csv
import os
import time
import importlib
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy


def _resolve_msg_type(msg_type_str: str):
    """Convert 'sensor_msgs/LaserScan' -> Python message class."""
    pkg_name, msg_name = msg_type_str.split("/", 1)
    mod = importlib.import_module(f"{pkg_name}.msg")
    return getattr(mod, msg_name)


class EvalPublisher(Node):
    def __init__(self):
        super().__init__("eval_publisher")
        rate_hz = float(os.environ.get("PUBLISH_RATE_HZ", "30"))
        topic = os.environ.get("PUBLISH_TOPIC", "/scan")
        msg_type_str = os.environ.get("PUBLISH_MSG_TYPE", "sensor_msgs/LaserScan")
        self._msg_class = _resolve_msg_type(msg_type_str)
        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_ALL,
            depth=200,  # Embedded-grade max_samples (600 KB at 3KB/msg)
        )
        self._pub = self.create_publisher(self._msg_class, topic, qos)
        period = 1.0 / rate_hz
        self._timer = self.create_timer(period, self._cb)
        self._count = 0
        self._last_log_ns = time.monotonic_ns()
        self._last_log_count = 0
        self._results_dir = os.environ.get("RESULTS_DIR", "/results")
        self.get_logger().info(
            f"EvalPublisher: {msg_type_str} on {topic}, {rate_hz}Hz, RELIABLE/KEEP_ALL"
        )

    def _build_msg(self):
        """Build a valid message.  LaserScan-specific construction by default."""
        msg = self._msg_class()
        if hasattr(msg, "header") and hasattr(msg.header, "stamp"):
            msg.header.stamp = self.get_clock().now().to_msg()
        if hasattr(msg, "header") and hasattr(msg.header, "frame_id"):
            msg.header.frame_id = "eval_frame"
        # LaserScan construction
        if hasattr(msg, "ranges"):
            msg.angle_min = 0.0
            msg.angle_max = 6.283185
            msg.angle_increment = 0.017453
            msg.time_increment = 0.0
            msg.scan_time = 1.0 / 30.0
            msg.range_min = 0.1
            msg.range_max = 100.0
            msg.ranges = [1.0] * 360
            msg.intensities = [0.0] * 360
        return msg

    def _cb(self):
        self._count += 1
        msg = self._build_msg()
        try:
            self._pub.publish(msg)
        except Exception:
            # Writer pool full (max_samples reached) — skip gracefully.
            # The node stays alive and retries on the next timer tick.
            pass

        now_ns = time.monotonic_ns()
        if now_ns - self._last_log_ns >= 5_000_000_000:
            delta_s = (now_ns - self._last_log_ns) / 1e9
            rate = (self._count - self._last_log_count) / delta_s if delta_s > 0 else 0
            self.get_logger().info(f"Published {self._count} msgs, rate: {rate:.1f} Hz")
            self._write_throughput(now_ns, rate, delta_s)
            self._last_log_ns = now_ns
            self._last_log_count = self._count


    def _write_throughput(self, timestamp_ns: int, rate_hz: float, window_s: float) -> None:
        """Append one row to metrics/throughput.csv (5-second windows)."""
        topic = os.environ.get("PUBLISH_TOPIC", "/scan")
        path = f"{self._results_dir}/metrics/throughput.csv"
        os.makedirs(f"{self._results_dir}/metrics", exist_ok=True)
        file_exists = os.path.isfile(path)
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            if not file_exists:
                w.writerow(["timestamp_ns", "topic", "node", "rate_hz", "window_s"])
            w.writerow([timestamp_ns, topic, "publisher",
                        round(rate_hz, 1), round(window_s, 1)])


def main():
    rclpy.init()
    node = EvalPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
