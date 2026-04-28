# src/adaptive_bridge/adaptive_bridge/proxy_node.py
import time
from typing import Callable, Optional
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile
from sensor_msgs.msg import LaserScan
from .config_manager import ConfigManager
from .qos_manager import QoSManager


class ProxyNode(Node):
    """
    Minimal adaptive bridge proxy for the sprint.

    Behavior:
      - Subscribes to an input topic (configurable).
      - Pre-creates two publishers per topic: critical and noncritical.
      - On message arrival, republishes to both outputs asynchronously.
      - Uses QoSManager to set QoS for each publisher.
    """

    def __init__(self, config_path: str = "", config: Optional[ConfigManager] = None):
        super().__init__("adaptive_bridge_proxy")
        # load config
        self.declare_parameter("config_path", config_path or "")
        cp = self.get_parameter(
            "config_path").get_parameter_value().string_value
        self.config = config or ConfigManager(cp)

        # qos manager
        self.qos_mgr = QoSManager()

        topics = self.config.get_topic_names()
        self._input_topic = topics["input_topic"]
        crit_prefix = topics["critical_prefix"]
        noncrit_prefix = topics["noncritical_prefix"]

        # determine output topic names
        # for generality we strip leading slash and create safe names
        self._input_topic = topics.get("input_topic") or "/input"
        base_name = (self._input_topic or "/input").strip("/").replace("/", "_") or "topic"
        self._crit_topic = f"{crit_prefix}/{base_name}"
        self._noncrit_topic = f"{noncrit_prefix}/{base_name}"

        # Select QoS profiles from config
        qos_map = self.config.get_qos_mapping()
        self._crit_qos = self.qos_mgr.get(
            qos_map.get("critical", "reliable_depth10"))
        self._noncrit_qos = self.qos_mgr.get(
            qos_map.get("noncritical", "besteffort_depth5"))

        # Pre-create publishers (prevents discovery churn at runtime)
        self.pub_crit = self.create_publisher(
            LaserScan, self._crit_topic, self._crit_qos)
        self.pub_noncrit = self.create_publisher(
            LaserScan, self._noncrit_topic, self._noncrit_qos)
        
        # Internal counters for metrics
        self._msg_count = 0

        # Subscriber: use small queue depth to simulate real pipeline
        sub_qos = QoSProfile(depth=10)
        self.subscription = self.create_subscription(
            LaserScan, self._input_topic, self._on_message, sub_qos
        )
        self._last_log = time.time()

        self.get_logger().info(
            f"Proxy listening: in='{self._input_topic}' out_crit='{self._crit_topic}' out_noncrit='{self._noncrit_topic}'")

    def _on_message(self, msg: LaserScan) -> None:
        # Simple forwarding policy: publish to critical always; noncritical optionally
        # Convert or annotate message if needed. For sprint we forward as-is.
        try:
            # Publish to critical path (RELIABLE)
            self.pub_crit.publish(msg)
            # Publish to non-critical (BEST_EFFORT)
            self.pub_noncrit.publish(msg)
            self._msg_count += 1
        except Exception as e:
            self.get_logger().error(f"Publish error: {e}")

        # periodic log to show message flow (not every message)
        now = time.time()
        if now - self._last_log > 5.0:
            self.get_logger().info(f"Forwarded {self._msg_count} messages to critical & noncritical. (Latest scan: {len(msg.ranges)} points)")
            self._last_log = now


def main(args=None):
    rclpy.init(args=args)
    node = ProxyNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
