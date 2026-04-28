# src/adaptive_bridge/adaptive_bridge/proxy_node.py
import time
from typing import Callable, Optional
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSHistoryPolicy, QoSReliabilityPolicy, QoSDurabilityPolicy
from sensor_msgs.msg import LaserScan
from .config_manager import ConfigManager
from .config_types import QoSPolicy


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

        topics = self.config.get_topics()
        route = topics[0]
        self._topic_id = route.id
        self._input_topic = route.input_topic
        self._crit_topic = route.critical_output
        self._noncrit_topic = route.noncritical_output

        self._crit_qos = self._to_rclpy_qos(self.config.get_qos_policy("critical", self._topic_id))
        self._noncrit_qos = self._to_rclpy_qos(self.config.get_qos_policy("noncritical", self._topic_id))

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

    @staticmethod
    def _to_rclpy_qos(policy: QoSPolicy) -> QoSProfile:
        history = QoSHistoryPolicy.KEEP_LAST if policy.history == "KEEP_LAST" else QoSHistoryPolicy.KEEP_ALL
        reliability = (
            QoSReliabilityPolicy.RELIABLE
            if policy.reliability == "RELIABLE"
            else QoSReliabilityPolicy.BEST_EFFORT
        )
        durability = (
            QoSDurabilityPolicy.VOLATILE
            if policy.durability == "VOLATILE"
            else QoSDurabilityPolicy.TRANSIENT_LOCAL
        )
        return QoSProfile(history=history, depth=policy.depth, reliability=reliability, durability=durability)

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
