#!/usr/bin/env python3
"""
Classifier state logger — writes classifier.csv on state transitions only.

Replaces the observer's classifier-logging function without requiring a
dedicated container.  Runs as a background process alongside other nodes
inside the slow_subscriber container in bridge experiments.

Only writes a row when the classifier decision state changes, not on
every 2 Hz tick — avoids spam while capturing every transition.
"""
import csv
import json
import os
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import String


class ClassifierLogger(Node):
    """Listens to classifier state, writes CSV rows on state transitions."""

    def __init__(self):
        super().__init__("classifier_logger")
        results_dir = os.environ.get("RESULTS_DIR", "/results")
        os.makedirs(f"{results_dir}/metrics", exist_ok=True)
        self._csv_path = f"{results_dir}/metrics/classifier.csv"
        self._last_state: str | None = None
        self._header_written = False
        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        self._sub = self.create_subscription(
            String, "/adaptive_bridge/classifier/state", self._cb, qos
        )
        self.get_logger().info("ClassifierLogger started")

    def _cb(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
        except (json.JSONDecodeError, TypeError):
            return
        state = data.get("state", "")
        if state == self._last_state:
            return  # only log on transitions — skip 2 Hz spam
        self._last_state = state

        with open(self._csv_path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "timestamp_ns", "subscriber_id", "subscriber_node",
                "state", "confidence", "reason",
            ])
            if not self._header_written:
                f.seek(0, os.SEEK_END)
                if f.tell() == 0:
                    w.writeheader()
                self._header_written = True
            w.writerow({
                "timestamp_ns": time.monotonic_ns(),
                "subscriber_id": data.get("subscriber_id", ""),
                "subscriber_node": data.get("subscriber_id", ""),
                "state": state,
                "confidence": data.get("confidence", ""),
                "reason": data.get("reason", ""),
            })


def main(args=None):
    rclpy.init(args=args)
    node = ClassifierLogger()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
