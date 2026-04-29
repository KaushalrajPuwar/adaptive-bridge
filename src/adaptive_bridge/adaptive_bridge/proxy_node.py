# src/adaptive_bridge/adaptive_bridge/proxy_node.py
import time
import queue
import threading
from typing import Callable, Optional
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSHistoryPolicy, QoSReliabilityPolicy, QoSDurabilityPolicy
from sensor_msgs.msg import LaserScan
from .config_manager import ConfigManager
from .config_types import QoSPolicy
from .models import TopicCounters, TopicRoute
from .topic_registry import TopicRegistry
from .qos_manager import QoSManager
from .noncritical_policy import NoncriticalPolicyEngine

class ProxyNode(Node):
    """
    Minimal adaptive bridge proxy for the sprint.

    Behavior:
      - Subscribes to an input topic (configurable).
      - Pre-creates two publishers per topic: critical and noncritical.
      - On message arrival, republishes to both outputs asynchronously.
      - Uses QoSManager to set QoS for each publisher.
      - Uses NoncriticalPolicyEngine and queues to prevent critical path blocking.
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
        self._running = True
        self._noncritical_queues = {}
        self._noncritical_threads = {}

        qos_raw = {}
        for name, policy in self.config._cfg().qos_profiles.items():
            qos_raw[name] = {
                "reliability": policy.reliability,
                "history": policy.history,
                "depth": policy.depth,
                "durability": policy.durability,
                "lifespan_ms": policy.lifespan_ms
            }
        self.qos_manager = QoSManager(
            qos_profiles=qos_raw,
            topic_qos_profiles=self.config._cfg().topic_qos_profiles
        )
        
        self.policy_engine = NoncriticalPolicyEngine(self.config._cfg(), self.qos_manager)

        self._initialize_entities()
        self._last_log = time.time()
        self._log_route_summary()

    def _initialize_entities(self) -> None:
        """Pre-create all publishers/subscribers at startup; never create during callbacks."""
        sub_qos = QoSProfile(depth=10)
        max_q = self.config._cfg().safety.max_noncritical_queue
        
        for topic_id, route in self._routes.items():
            crit_qos = self.qos_manager.resolve(topic_id, "critical")
            noncrit_qos = self.qos_manager.resolve(topic_id, "noncritical")
            self._publishers_critical[topic_id] = self.create_publisher(LaserScan, route.critical_output, crit_qos)
            self._publishers_noncritical[topic_id] = self.create_publisher(LaserScan, route.noncritical_output, noncrit_qos)
            
            self._noncritical_queues[topic_id] = queue.Queue(maxsize=max_q)
            t = threading.Thread(target=self._noncritical_worker, args=(topic_id,), daemon=True)
            self._noncritical_threads[topic_id] = t
            t.start()
            
            self._subscribers[topic_id] = self.create_subscription(
                LaserScan, route.input_topic, self._make_topic_callback(topic_id), sub_qos
            )

    def _noncritical_worker(self, topic_id: str) -> None:
        while rclpy.ok() and self._running:
            try:
                msg = self._noncritical_queues[topic_id].get(timeout=0.1)
                self._publishers_noncritical[topic_id].publish(msg)
                self._counters_by_topic[topic_id].total_forwarded_noncritical += 1
            except queue.Empty:
                pass
            except Exception as e:
                self.get_logger().error(f"Noncritical publish error for '{topic_id}': {e}")

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
            
            now_ns = time.time_ns()
            msg_ts_ns = now_ns
            if hasattr(msg, 'header') and hasattr(msg.header, 'stamp'):
                msg_ts_ns = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
                if msg_ts_ns == 0:
                    msg_ts_ns = now_ns
                    
            allowed, reason = self.policy_engine.allow_publish(topic_id, msg_ts_ns, now_ns)
            if allowed:
                try:
                    self._noncritical_queues[topic_id].put_nowait(msg)
                except queue.Full:
                    self.policy_engine.record_drop(topic_id, "queue_overflow")
            else:
                self.policy_engine.record_drop(topic_id, reason)
                
        except Exception as e:
            self.get_logger().error(f"Publish error for topic_id='{topic_id}': {e}")

        now = time.time()
        if now - self._last_log > 5.0:
            self._log_periodic_counts()
            self._last_log = now

    def _log_periodic_counts(self) -> None:
        summary = []
        for topic_id in self._routes:
            stats = self.policy_engine.get_stats(topic_id)
            c = self._counters_by_topic[topic_id]
            c.dropped_noncritical_rate_limit = stats.rate_limit
            c.dropped_noncritical_queue = stats.queue_overflow
            c.dropped_noncritical_stale = stats.stale
            
            summary.append(
                f"{topic_id}:rx={c.total_received},crit={c.total_forwarded_critical},"
                f"noncrit={c.total_forwarded_noncritical},drops(q={stats.queue_overflow},"
                f"rate={stats.rate_limit},stale={stats.stale},dis={stats.disabled})"
            )
        self.get_logger().info("Forwarding counters | " + " | ".join(summary))

    def _shutdown_entities(self) -> None:
        self._running = False
        for t in self._noncritical_threads.values():
            if t.is_alive():
                t.join(timeout=1.0)
                
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
