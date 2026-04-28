"""
Step 1 placeholder classifier node.

This module intentionally exposes a deterministic entrypoint so package
executables remain coherent before classifier implementation (roadmap Step 10).
"""

import rclpy
from rclpy.node import Node
from .models import ClassifierSnapshot


class ClassifierPlaceholderNode(Node):
    """Minimal placeholder node that documents pending classifier work."""

    def __init__(self) -> None:
        super().__init__("adaptive_bridge_classifier_placeholder")
        self._sample_state = ClassifierSnapshot(
            subscriber_id="placeholder_subscriber",
            classification="UNKNOWN",
            reason_flags=("placeholder",),
            avg_rtt_ms=0.0,
            loss=0.0,
        )
        self.get_logger().warning(
            "classifier_node is a Step 1 placeholder. "
            "Full classifier runtime implementation is planned in roadmap Step 10."
        )


def main(args=None):
    """Run placeholder classifier entrypoint and exit cleanly."""
    rclpy.init(args=args)
    node = ClassifierPlaceholderNode()
    node.get_logger().info("Exiting placeholder classifier node.")
    node.destroy_node()
    rclpy.shutdown()
