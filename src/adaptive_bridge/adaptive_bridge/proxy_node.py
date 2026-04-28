# src/adaptive_bridge/adaptive_bridge/proxy_node.py
import time
from typing import Callable, Optional
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSHistoryPolicy, QoSReliabilityPolicy, QoSDurabilityPolicy
from sensor_msgs.msg import LaserScan
from .config_manager import ConfigManager
from .config_types import QoSPolicy
from .models import TopicCounters, TopicRoute
from .topic_registry import TopicRegistry


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
        self._registry = TopicRegistry()
        self._routes = self._registry.build_routes(topics)
        self._subscribers = {}
        self._publishers_critical = {}
        self._publishers_noncritical = {}
        self._counters_by_topic = {topic_id: TopicCounters() for topic_id in self._routes}

        self._initialize_entities()
        self._last_log = time.time()
        self._log_route_summary()

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

    def _initialize_entities(self) -> None:
        """Pre-create all publishers/subscribers at startup; never create during callbacks."""
        sub_qos = QoSProfile(depth=10)
        for topic_id, route in self._routes.items():
            crit_qos = self._to_rclpy_qos(self.config.get_qos_policy("critical", topic_id))
            noncrit_qos = self._to_rclpy_qos(self.config.get_qos_policy("noncritical", topic_id))
            self._publishers_critical[topic_id] = self.create_publisher(LaserScan, route.critical_output, crit_qos)
            self._publishers_noncritical[topic_id] = self.create_publisher(LaserScan, route.noncritical_output, noncrit_qos)
            self._subscribers[topic_id] = self.create_subscription(
                LaserScan, route.input_topic, self._make_topic_callback(topic_id), sub_qos
            )

    def _log_route_summary(self) -> None:
        for topic_id, route in self._routes.items():
            self.get_logger().info(
                f"Route initialized topic_id='{topic_id}' in='{route.input_topic}' "
                f"out_crit='{route.critical_output}' out_noncrit='{route.noncritical_output}'"
            )

    def _make_topic_callback(self, topic_id: str) -> Callable[[LaserScan], None]:
        def _cb(msg: LaserScan) -> None:
            self._forward_message(topic_id, msg)
        return _cb

    def _forward_message(self, topic_id: str, msg: LaserScan) -> None:
        # Keep forwarding path lock-minimal and callback-latency aware.
        counters = self._counters_by_topic[topic_id]
        try:
            counters.total_received += 1
            self._publishers_critical[topic_id].publish(msg)
            counters.total_forwarded_critical += 1
            self._publishers_noncritical[topic_id].publish(msg)
            counters.total_forwarded_noncritical += 1
        except Exception as e:
            self.get_logger().error(f"Publish error for topic_id='{topic_id}': {e}")
            counters.dropped_noncritical_queue += 1

        now = time.time()
        if now - self._last_log > 5.0:
            self._log_periodic_counts()
            self._last_log = now

    def _log_periodic_counts(self) -> None:
        summary = []
        for topic_id in self._routes:
            c = self._counters_by_topic[topic_id]
            summary.append(
                f"{topic_id}:rx={c.total_received},crit={c.total_forwarded_critical},"
                f"noncrit={c.total_forwarded_noncritical},drop_noncrit={c.dropped_noncritical_queue}"
            )
        self.get_logger().info("Forwarding counters | " + " | ".join(summary))

    def _shutdown_entities(self) -> None:
        for sub in self._subscribers.values():
            self.destroy_subscription(sub)
        for pub in self._publishers_critical.values():
            self.destroy_publisher(pub)
        for pub in self._publishers_noncritical.values():
            self.destroy_publisher(pub)
        self._subscribers.clear()
        self._publishers_critical.clear()
        self._publishers_noncritical.clear()


def main(args=None):
    rclpy.init(args=args)
    node = ProxyNode()
    try:
        rclpy.spin(node)
    finally:
        node._shutdown_entities()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
