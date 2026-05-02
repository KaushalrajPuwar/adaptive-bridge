#!/usr/bin/env python3
"""
Shared base for evaluation subscriber nodes.

Env vars:
  SUBSCRIBE_TOPIC    – topic name (default /scan)
  SUBSCRIBE_MSG_TYPE – ROS 2 message type string (default sensor_msgs/LaserScan)
  CALLBACK_DELAY_MS  – optional delay in callback (default 0)
  TARGET_NODE        – label written to CSV (default derived from node name)
  RESULTS_DIR        – directory for CSV output
"""
import csv
import os
import time
from collections import deque
import importlib

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy

_FLUSH_INTERVAL = 50


def _resolve_msg_type(msg_type_str: str):
    pkg_name, msg_name = msg_type_str.split("/", 1)
    mod = importlib.import_module(f"{pkg_name}.msg")
    return getattr(mod, msg_name)


class BaseSubscriber(Node):
    """Latency-measuring subscriber node (pure evaluation infrastructure)."""

    def __init__(self, node_name: str):
        super().__init__(node_name)
        topic = os.environ.get("SUBSCRIBE_TOPIC", "/scan")
        msg_type_str = os.environ.get("SUBSCRIBE_MSG_TYPE", "sensor_msgs/LaserScan")
        self._msg_class = _resolve_msg_type(msg_type_str)
        self._delay_ms = float(os.environ.get("CALLBACK_DELAY_MS", "0"))
        self._target_node = os.environ.get("TARGET_NODE", node_name)
        results_dir = os.environ.get("RESULTS_DIR", "/results")
        os.makedirs(f"{results_dir}/metrics", exist_ok=True)

        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_ALL,
        )
        self._sub = self.create_subscription(self._msg_class, topic, self._cb, qos)
        self._results_dir = results_dir
        self._topic = topic
        self._latency_csv = f"{results_dir}/metrics/latency.csv"
        self._drops_csv = f"{results_dir}/metrics/drops.csv"
        self._buf = deque()
        self._drop_buf = deque()
        self._last_seq = -1
        self._recv = 0
        self._drops = 0
        self._lat_header = False
        self._drop_header = False
        self.get_logger().info(
            f"{node_name} listening on {topic} ({msg_type_str}), "
            f"target_node={self._target_node}, delay={self._delay_ms}ms"
        )

    def _cb(self, msg):
        if self._delay_ms > 0:
            time.sleep(self._delay_ms / 1000.0)
        now = self.get_clock().now()
        now_ns = now.nanoseconds
        stamp_ns = (msg.header.stamp.sec * 1_000_000_000
                    + msg.header.stamp.nanosec) if hasattr(msg, "header") else 0
        lat_ms = (now_ns - stamp_ns) / 1_000_000.0 if stamp_ns > 0 else 0.0
        self._recv += 1
        seq = stamp_ns
        if self._last_seq >= 0 and seq > self._last_seq:
            if seq - self._last_seq > 70_000_000:
                self._drops += 1
        self._last_seq = seq

        self._buf.append({
            "timestamp_ns": now_ns,
            "topic": self._topic,
            "source_node": "publisher",
            "target_node": self._target_node,
            "seq": seq,
            "msg_age_ms": round(lat_ms, 3),
            "e2e_latency_ms": round(lat_ms, 3),
        })

        if self._drops > 0:
            self._drop_buf.append({
                "timestamp_ns": now_ns,
                "topic": self._topic,
                "node": self._target_node,
                "dropped_count": self._drops,
                "total_received": self._recv,
                "total_expected": self._recv + self._drops,
                "drop_rate": round(
                    self._drops / max(1, self._recv + self._drops), 4),
            })
            self._drops = 0

        if len(self._buf) >= _FLUSH_INTERVAL:
            self._flush()

    def _flush(self):
        if self._buf:
            with open(self._latency_csv, "a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=[
                    "timestamp_ns", "topic", "source_node", "target_node",
                    "seq", "msg_age_ms", "e2e_latency_ms",
                ])
                if not self._lat_header:
                    w.writeheader()
                    self._lat_header = True
                while self._buf:
                    w.writerow(self._buf.popleft())
        if self._drop_buf:
            with open(self._drops_csv, "a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=[
                    "timestamp_ns", "topic", "node", "dropped_count",
                    "total_received", "total_expected", "drop_rate",
                ])
                if not self._drop_header:
                    w.writeheader()
                    self._drop_header = True
                while self._drop_buf:
                    w.writerow(self._drop_buf.popleft())

    def destroy_node(self):
        self._flush()
        super().destroy_node()
