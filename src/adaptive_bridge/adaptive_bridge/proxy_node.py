# src/adaptive_bridge/adaptive_bridge/proxy_node.py
"""
Adaptive Bridge ProxyNode — Step 11 Policy Coupling upgrade.

Wires classifier decisions into runtime noncritical degradation:
  - Subscribes to /adaptive_bridge/classifier/state
  - PolicyEngine maps subscriber states -> per-topic PolicyMode
  - NoncriticalPolicyEngine applies rate limiting based on mode
  - Transition damping prevents oscillation (hysteresis_count windows)
  - Safety bias: UNKNOWN -> treat as CRITICAL -> NORMAL mode
  - Refactored all config access to public ConfigManager API

History:
  Step 4: Multi-topic proxy with precreated endpoints.
  Step 5: QoS Manager integration (profile resolution).
  Step 6: NoncriticalPolicyEngine with token-bucket rate limiting.
  Step 7: DiagnosticsCollector + ROS diagnostics publisher/timer.
  Step 8: Probe protocol v1 (client/responder in utils/probes.py; no proxy changes).
  Step 11: Policy coupling: classifier sub + PolicyEngine + mode-driven degradation.
"""

import json
import time
import queue
import threading
from typing import Callable, Optional

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String

from .config_manager import ConfigManager
from .models import TopicCounters, TopicRoute
from .topic_registry import TopicRegistry
from .qos_manager import QoSManager
from .noncritical_policy import NoncriticalPolicyEngine
from .policy_engine import PolicyEngine
from .diagnostics import DiagnosticsCollector


class ProxyNode(Node):
    """
    Adaptive bridge proxy for multi-topic LaserScan forwarding.

    Behavior:
      - Subscribes to configured input topics.
      - Pre-creates one critical publisher and one noncritical publisher per topic.
      - On message arrival: publishes to critical immediately; enqueues noncritical.
      - Background worker thread per topic drains the noncritical queue.
      - NoncriticalPolicyEngine enforces rate limiting, staleness, queue-overflow drops.
      - PolicyEngine drives mode changes from classifier decisions.
      - DiagnosticsCollector aggregates runtime state; ProxyNode owns the ROS
        publisher + timer and calls gather_payload() + publish on each tick.
        Publish failures are never fatal.
    """

    def __init__(self, config_path: str = "", config: Optional[ConfigManager] = None):
        super().__init__("adaptive_bridge_proxy")

        # Config
        self.declare_parameter("config_path", config_path or "")
        cp = self.get_parameter("config_path").get_parameter_value().string_value
        self.config = config or ConfigManager(cp)

        # Topic routing
        topics = self.config.get_topics()
        self._registry = TopicRegistry()
        self._routes = self._registry.build_routes(topics)
        self._subscribers: dict = {}
        self._publishers_critical: dict = {}
        self._publishers_noncritical: dict = {}
        self._counters_by_topic: dict = {
            topic_id: TopicCounters() for topic_id in self._routes
        }
        self._running = True
        self._noncritical_queues: dict = {}
        self._noncritical_threads: dict = {}

        # QoS manager (public ConfigManager API)
        self.qos_manager = QoSManager(
            qos_profiles=self.config.get_qos_profiles_dict(),
            topic_qos_profiles=self.config.get_topic_qos_profiles_dict(),
        )
        full_cfg = self.config.get_bridge_config()

        # Noncritical policy engine (low-level rate limiter)
        self._nc_policy = NoncriticalPolicyEngine(full_cfg, self.qos_manager)

        # High-level policy engine (classifier -> mode mapping)
        self._policy_engine = PolicyEngine(
            hysteresis_count=full_cfg.classifier.hysteresis_count,
            forced_critical_ids=self.config.get_forced_critical_ids(),
        )

        # Global mode (extended by SafetySupervisor in Step 12)
        self._global_mode: str = "NORMAL"

        # DiagnosticsCollector (pure Python, no Node)
        self._diag_collector = DiagnosticsCollector()

        # Pre-register route metadata and QoS snapshots (stable at runtime)
        for topic_id, route in self._routes.items():
            self._diag_collector.ingest_topic_route(topic_id, route.to_dict())
            self._diag_collector.ingest_noncritical_mode(topic_id, "NORMAL")
            for role in ("critical", "noncritical"):
                desc = self.qos_manager.describe(topic_id, role)
                self._diag_collector.ingest_qos_snapshot(topic_id, role, desc)

        # Diagnostics ROS publisher + timer (public ConfigManager API)
        diag_cfg = self.config.get_diagnostics_config()
        self._diag_pub = self.create_publisher(String, diag_cfg.topic, 10)
        self._diag_timer = self.create_timer(
            diag_cfg.publish_interval_s, self._publish_diagnostics
        )

        # Pre-create publishers/subscribers
        self._initialize_entities()
        self._log_route_summary()

        # Subscribe to classifier decisions
        self._classifier_sub = self.create_subscription(
            String,
            "/adaptive_bridge/classifier/state",
            self._on_classifier_update,
            10,
        )

    # ── Startup helpers ───────────────────────────────────────────────

    def _initialize_entities(self) -> None:
        """Pre-create all publishers and subscribers at startup (never in callbacks)."""
        sub_qos = QoSProfile(depth=10)
        max_q = self.config.get_safety_config().max_noncritical_queue

        for topic_id, route in self._routes.items():
            crit_qos = self.qos_manager.resolve(topic_id, "critical")
            noncrit_qos = self.qos_manager.resolve(topic_id, "noncritical")

            self._publishers_critical[topic_id] = self.create_publisher(
                LaserScan, route.critical_output, crit_qos
            )
            self._publishers_noncritical[topic_id] = self.create_publisher(
                LaserScan, route.noncritical_output, noncrit_qos
            )

            self._noncritical_queues[topic_id] = queue.Queue(maxsize=max_q)
            t = threading.Thread(
                target=self._noncritical_worker, args=(topic_id,), daemon=True
            )
            self._noncritical_threads[topic_id] = t
            t.start()

            self._subscribers[topic_id] = self.create_subscription(
                LaserScan,
                route.input_topic,
                self._make_topic_callback(topic_id),
                sub_qos,
            )

    def _log_route_summary(self) -> None:
        for topic_id, route in self._routes.items():
            self.get_logger().info(
                f"Route initialized topic_id='{topic_id}' "
                f"in='{route.input_topic}' "
                f"out_crit='{route.critical_output}' "
                f"out_noncrit='{route.noncritical_output}'"
            )

    # ── Message forwarding (hot path) ─────────────────────────────────

    def _make_topic_callback(self, topic_id: str) -> Callable[[LaserScan], None]:
        def _cb(msg: LaserScan) -> None:
            self._forward_message(topic_id, msg)
        return _cb

    def _forward_message(self, topic_id: str, msg: LaserScan) -> None:
        """Critical hot path — minimal, lock-free."""
        counters = self._counters_by_topic[topic_id]
        try:
            counters.total_received += 1

            # Critical path (always forward)
            self._publishers_critical[topic_id].publish(msg)
            counters.total_forwarded_critical += 1

            # Noncritical path (policy-gated)
            now_ns = time.time_ns()
            msg_ts_ns = now_ns
            if hasattr(msg, "header") and hasattr(msg.header, "stamp"):
                raw = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
                if raw > 0:
                    msg_ts_ns = raw

            allowed, reason = self._nc_policy.allow_publish(
                topic_id, msg_ts_ns, now_ns
            )
            if allowed:
                try:
                    self._noncritical_queues[topic_id].put_nowait(msg)
                except queue.Full:
                    self._nc_policy.record_drop(topic_id, "queue_overflow")
            else:
                self._nc_policy.record_drop(topic_id, reason)

        except Exception as exc:
            self.get_logger().error(f"Publish error for topic_id='{topic_id}': {exc}")

    # ── Classifier update callback ────────────────────────────────────

    def _on_classifier_update(self, msg: String) -> None:
        """Process classifier decision -> update policy engine modes."""
        try:
            decision = json.loads(msg.data)
            sub_id = decision.get("subscriber_id", "")
            state = decision.get("state", "UNKNOWN")
            self._policy_engine.on_classifier_update(sub_id, state)

            for topic_id in self._routes:
                mode = self._policy_engine.get_mode(topic_id)
                self._nc_policy.on_mode_change(topic_id, mode)

        except Exception as e:
            self.get_logger().warning(f"Classifier update failed: {e}")

    # ── Noncritical background worker ─────────────────────────────────

    def _noncritical_worker(self, topic_id: str) -> None:
        """Background thread: drains noncritical queue and publishes."""
        while rclpy.ok() and self._running:
            try:
                msg = self._noncritical_queues[topic_id].get(timeout=0.1)
                self._publishers_noncritical[topic_id].publish(msg)
                self._counters_by_topic[topic_id].total_forwarded_noncritical += 1
            except queue.Empty:
                pass
            except Exception as exc:
                self.get_logger().error(
                    f"Noncritical publish error for '{topic_id}': {exc}"
                )

    # ── Diagnostics timer callback ────────────────────────────────────

    def _publish_diagnostics(self) -> None:
        """Periodic ROS timer: snapshot state, gather payload, publish JSON.

        Never propagates exceptions — any failure is only logged.
        This is the single authoritative diagnostics publish point.
        """
        try:
            for topic_id in self._routes:
                c = self._counters_by_topic[topic_id]

                # Sync drop counters from noncritical policy
                stats = self._nc_policy.get_stats(topic_id)
                c.dropped_noncritical_rate_limit = stats.rate_limit
                c.dropped_noncritical_queue = stats.queue_overflow
                c.dropped_noncritical_stale = stats.stale

                self._diag_collector.ingest_counters(topic_id, c.to_dict())
                self._diag_collector.ingest_drop_stats(topic_id, {
                    "rate_limit": stats.rate_limit,
                    "queue_overflow": stats.queue_overflow,
                    "stale": stats.stale,
                    "disabled": stats.disabled,
                })

                nc_mode = self._nc_policy._mode.get(topic_id, None)
                if nc_mode is not None:
                    self._diag_collector.ingest_noncritical_mode(
                        topic_id, nc_mode.value
                    )

            # Ingest classifier snapshots into diagnostics
            combined_snapshots = {}
            for sub_id, curr_state in self._policy_engine.get_subscriber_states().items():
                combined_snapshots[sub_id] = {
                    "classification": curr_state,
                }
            if combined_snapshots:
                self._diag_collector.ingest_classifier_snapshot(combined_snapshots)

            self._diag_collector.set_global_mode(self._global_mode)

            payload = self._diag_collector.gather_payload()
            msg = String()
            msg.data = json.dumps(payload)
            self._diag_pub.publish(msg)
            self.get_logger().debug(f"Diagnostics published seq={payload['seq']}")

        except Exception as exc:
            self.get_logger().error(f"Diagnostics publish failed: {exc}")

    # ── Shutdown ──────────────────────────────────────────────────────

    def _shutdown_entities(self) -> None:
        self._running = False
        try:
            self._diag_timer.cancel()
        except Exception:
            pass

        for t in self._noncritical_threads.values():
            if t.is_alive():
                t.join(timeout=1.0)

        for sub in self._subscribers.values():
            self.destroy_subscription(sub)
        for pub in self._publishers_critical.values():
            self.destroy_publisher(pub)
        for pub in self._publishers_noncritical.values():
            self.destroy_publisher(pub)

        try:
            self.destroy_subscription(self._classifier_sub)
        except Exception:
            pass

        self._subscribers.clear()
        self._publishers_critical.clear()
        self._publishers_noncritical.clear()


def main(args=None) -> None:
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
