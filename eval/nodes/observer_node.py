#!/usr/bin/env python3
"""
Observer node — system-wide metrics collector.

Subscribes to monitored topics, counts messages, and periodically writes
throughput, CPU, and classifier CSVs.  Uses BEST_EFFORT QoS so it never
contributes to backpressure.

Env vars:
  MODE             – "baseline" or "adaptive" (default adaptive)
  MONITOR_TOPICS   – comma-separated topic list (defaults derived from MODE)
  MONITOR_MSG_TYPE – message type for monitoring topics (default sensor_msgs/LaserScan)
  RESULTS_DIR      – CSV output directory (default /results)
"""
import csv
import importlib
import json
import os
import time
from collections import defaultdict

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import String

_INTERVAL_S = 5


def _resolve_msg_type(msg_type_str: str):
    pkg_name, msg_name = msg_type_str.split("/", 1)
    mod = importlib.import_module(f"{pkg_name}.msg")
    return getattr(mod, msg_name)


def _make_best_effort():
    return QoSProfile(
        reliability=ReliabilityPolicy.BEST_EFFORT,
        history=HistoryPolicy.KEEP_LAST,
        depth=10,
    )


class Observer(Node):
    def __init__(self):
        super().__init__("eval_observer")
        mode = os.environ.get("MODE", "adaptive")
        results_dir = os.environ.get("RESULTS_DIR", "/results")
        os.makedirs(f"{results_dir}/metrics", exist_ok=True)
        self._results_dir = results_dir
        self._mode = mode
        self._topic_counts = defaultdict(int)
        self._last_counts = defaultdict(int)
        qos = _make_best_effort()

        msg_type_str = os.environ.get("MONITOR_MSG_TYPE", "sensor_msgs/LaserScan")
        msg_class = _resolve_msg_type(msg_type_str)

        # Determine topics to monitor
        if mode == "baseline":
            topics = os.environ.get("MONITOR_TOPICS", "/scan").split(",")
        else:
            topics = os.environ.get(
                "MONITOR_TOPICS",
                "/adaptive_bridge/critical/scan,/adaptive_bridge/noncritical/scan"
            ).split(",")
        for topic in topics:
            topic = topic.strip()
            if topic:
                self.create_subscription(
                    msg_class, topic, self._make_counter(topic), qos)

        # Classifier + diagnostics (always String type)
        if mode != "baseline":
            self.create_subscription(
                String, "/adaptive_bridge/classifier/state", self._clf_cb, qos)
            self._classifier_csv = f"{results_dir}/metrics/classifier.csv"
            self._classifier_buf = []
            self._clf_h = False

        self._throughput_csv = f"{results_dir}/metrics/throughput.csv"
        self._cpu_csv = f"{results_dir}/metrics/cpu.csv"
        self._thr_h = False
        self._cpu_h = False
        self._last_cpu_jiffies = 0
        self._ticks_per_sec = os.sysconf("SC_CLK_TCK")
        self._timer = self.create_timer(_INTERVAL_S, self._timer_cb)
        self._last_mono_ns = time.monotonic_ns()
        self.get_logger().info(
            f"Observer mode={mode}, msg_type={msg_type_str}, "
            f"topics={list(topics)}, ticks/s={self._ticks_per_sec}"
        )

    def _make_counter(self, topic):
        def _cb(_msg):
            self._topic_counts[topic] += 1
        return _cb

    def _clf_cb(self, msg):
        try:
            data = json.loads(msg.data)
        except Exception:
            return
        self._classifier_buf.append({
            "timestamp_ns": time.monotonic_ns(),
            "subscriber_id": data.get("subscriber_id", ""),
            "subscriber_node": data.get("subscriber_id", ""),
            "state": data.get("state", ""),
            "confidence": data.get("confidence", ""),
            "reason": data.get("reason", ""),
        })

    def _read_cpu_jiffies(self) -> int:
        try:
            with open("/proc/self/stat") as f:
                parts = f.read().split()
                utime = int(parts[13]) if len(parts) > 13 else 0
                stime = int(parts[14]) if len(parts) > 14 else 0
                cutime = int(parts[15]) if len(parts) > 15 else 0
                cstime = int(parts[16]) if len(parts) > 16 else 0
                return utime + stime + cutime + cstime
        except Exception:
            return 0

    def _timer_cb(self):
        now_ns = time.monotonic_ns()
        window_s = (now_ns - self._last_mono_ns) / 1e9
        self._last_mono_ns = now_ns

        # --- Throughput ---
        with open(self._throughput_csv, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "timestamp_ns", "topic", "node", "rate_hz", "window_s",
            ])
            if not self._thr_h:
                w.writeheader()
                self._thr_h = True
            for topic, count in self._topic_counts.items():
                prev = self._last_counts.get(topic, 0)
                rate = (count - prev) / window_s if window_s > 0 else 0
                w.writerow({
                    "timestamp_ns": now_ns,
                    "topic": topic,
                    "node": "observer",
                    "rate_hz": round(rate, 2),
                    "window_s": round(window_s, 2),
                })
        self._last_counts = dict(self._topic_counts)

        # --- CPU ---
        curr_jiffies = self._read_cpu_jiffies()
        jiffies_delta = curr_jiffies - self._last_cpu_jiffies
        self._last_cpu_jiffies = curr_jiffies
        cpu_pct = round(
            (jiffies_delta / self._ticks_per_sec / window_s) * 100.0, 2
        ) if window_s > 0 else 0.0
        with open(self._cpu_csv, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "timestamp_ns", "node", "cpu_percent", "mem_mb", "threads",
            ])
            if not self._cpu_h:
                w.writeheader()
                self._cpu_h = True
            w.writerow({
                "timestamp_ns": now_ns,
                "node": "observer",
                "cpu_percent": cpu_pct,
                "mem_mb": 0,
                "threads": 1,
            })

        # --- Classifier state ---
        if hasattr(self, '_classifier_buf') and self._classifier_buf:
            with open(self._classifier_csv, "a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=[
                    "timestamp_ns", "subscriber_id", "subscriber_node",
                    "state", "confidence", "reason",
                ])
                if not self._clf_h:
                    w.writeheader()
                    self._clf_h = True
                for row in self._classifier_buf:
                    w.writerow(row)
                self._classifier_buf.clear()

    def flush(self):
        """Write any buffered data to disk (called on shutdown)."""
        self._timer_cb()

    def destroy_node(self):
        self.flush()
        super().destroy_node()


def main():
    rclpy.init()
    node = Observer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
