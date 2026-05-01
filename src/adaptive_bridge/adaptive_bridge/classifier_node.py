# classifier_node.py
"""
Adaptive Bridge Classifier Node — Step 9 upgrade.

Step 9 delivers the pure-Python classifier core (classifier_core.py).
This module is the thin ROS entrypoint shell that wraps it.

Current state:
  - Holds a SubscriberClassifier instance (ready for Step 10 wiring).
  - Starts and shuts down cleanly in a live ROS2 session.
  - Does NOT yet subscribe to probe topics or publish decisions — that
    is Step 10 (Classifier Node Runtime Integration).

Step 10 will:
  - Subscribe to /adaptive_bridge/probe_resp
  - Run a periodic evaluation timer
  - Publish to /adaptive_bridge/classifier/state
"""

import rclpy
from rclpy.node import Node

from .classifier_core import SubscriberClassifier
from .classifier_types import ProbeMetrics
from .config_manager import ConfigManager


class ClassifierNode(Node):
    """Classifier node shell — core logic ready, ROS wiring pending Step 10."""

    def __init__(self, config_path: str = "") -> None:
        super().__init__("adaptive_bridge_classifier")

        self.declare_parameter("config_path", config_path or "")
        cp = self.get_parameter("config_path").get_parameter_value().string_value
        self._config_manager = ConfigManager(cp)
        clf_cfg = self._config_manager.get_classifier_config()
        forced_ids = self._config_manager.get_forced_critical_ids()

        self._classifier = SubscriberClassifier(
            config=clf_cfg,
            forced_critical_ids=forced_ids if forced_ids else None,
        )

        self.get_logger().info(
            f"ClassifierNode ready — core logic loaded "
            f"(hysteresis={clf_cfg.hysteresis_count}, "
            f"demote_rtt={clf_cfg.demote_rtt_ms}ms, "
            f"demote_loss={clf_cfg.demote_loss_threshold:.0%}). "
            f"ROS probe/decision wiring pending Step 10."
        )

    def get_classifier(self) -> SubscriberClassifier:
        """Expose the core classifier for Step 10 wiring."""
        return self._classifier


def main(args=None) -> None:
    """Run the classifier node."""
    rclpy.init(args=args)
    node = ClassifierNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
