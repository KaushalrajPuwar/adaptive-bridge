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
  - Generic message-type support: any ROS 2 message type configurable via YAML

History:
  Step 4: Multi-topic proxy with precreated endpoints.
  Step 5: QoS Manager integration (profile resolution).
  Step 6: NoncriticalPolicyEngine with token-bucket rate limiting.
  Step 7: DiagnosticsCollector + ROS diagnostics publisher/timer.
  Step 8: Probe protocol v1 (client/responder in utils/probes.py; no proxy changes).
  Step 11: Policy coupling: classifier sub + PolicyEngine + mode-driven degradation.
  Step 16: Generic message-type support: resolved dynamically from config.
"""

import importlib
import json
import time
import queue
import threading
from typing import Any, Callable, Optional

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile
from std_msgs.msg import String

from .config_manager import ConfigManager
from .models import TopicCounters, TopicRoute, PolicyMode
from .topic_registry import TopicRegistry
from .qos_manager import QoSManager
from .noncritical_policy import NoncriticalPolicyEngine
from .policy_engine import PolicyEngine
from .safety_supervisor import SafetySupervisor
from .utils.security import SecurityManager, SecurityMode
from .diagnostics import DiagnosticsCollector


def _resolve_msg_type(msg_type_str: str):
    """Convert 'sensor_msgs/LaserScan' -> Python message class.

    Raises ImportError or ValueError with a clear message if the type
    cannot be resolved.
    """
    try:
        pkg_name, msg_name = msg_type_str.split("/", 1)
    except ValueError:
        raise ValueError(
            f"Invalid message_type '{msg_type_str}'. Must be 'pkg_name/MsgName'."
        )
    try:
        mod = importlib.import_module(f"{pkg_name}.msg")
    except ImportError:
        raise ImportError(
            f"Package '{pkg_name}' not found. "
            f"Is ros-{pkg_name.replace('_', '-')} installed?"
        )
    msg_class = getattr(mod, msg_name, None)
    if msg_class is None:
        raise ValueError(
            f"Message type '{msg_name}' not found in {pkg_name}.msg."
        )
    return msg_class


class ProxyNode(Node):
    """
    Adaptive bridge proxy for multi-topic message forwarding.

    Supports any ROS 2 message type configured via YAML ``message_type`` field.

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

        # Safety supervisor (global mode machine)
        self._supervisor = SafetySupervisor(
            max_noncritical_queue=self.config.get_safety_config().max_noncritical_queue,
        )

        # Security manager (HMAC signing verification)
        sec_cfg = self.config.get_security_config()
        self._security = SecurityManager(
            mode=self._map_trust_mode(sec_cfg.trust_mode),
            hmac_secret=sec_cfg.hmac_secret,
            replay_window_ms=sec_cfg.replay_window_ms,
        )
        self._security.set_log_callback(self.get_logger().warning)

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

            # Dynamic message-type resolution
            msg_class = _resolve_msg_type(route.message_type)

            self._publishers_critical[topic_id] = self.create_publisher(
                msg_class, route.critical_output, crit_qos
            )
            self._publishers_noncritical[topic_id] = self.create_publisher(
                msg_class, route.noncritical_output, noncrit_qos
            )

            self._noncritical_queues[topic_id] = queue.Queue(maxsize=max_q)
            t = threading.Thread(
                target=self._noncritical_worker, args=(topic_id,), daemon=True
            )
            self._noncritical_threads[topic_id] = t
            t.start()

            self._subscribers[topic_id] = self.create_subscription(
                msg_class,
                route.input_topic,
                self._make_topic_callback(topic_id),
                sub_qos,
            )

    def _log_route_summary(self) -> None:
        for topic_id, route in self._routes.items():
            self.get_logger().info(
                f"Route initialized topic_id='{topic_id}' "
                f"msg_type='{route.message_type}' "
                f"in='{route.input_topic}' "
                f"out_crit='{route.critical_output}' "
                f"out_noncrit='{route.noncritical_output}'"
            )

    # ── Message forwarding (hot path) ─────────────────────────────────

    def _make_topic_callback(self, topic_id: str) -> Callable[[Any], None]:
        def _cb(msg: Any) -> None:
            self._forward_message(topic_id, msg)
        return _cb

    def _forward_message(self, topic_id: str, msg: Any) -> None:
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

    @staticmethod
    def _map_trust_mode(trust_mode: str) -> str:
        return {
            "default_deny": "enforce", "permissive": "log_only", "off": "off"
        }.get(trust_mode, "off")

    def _on_classifier_update(self, msg: String) -> None:
        """Process classifier decision -> verify HMAC -> update policy engine."""
        try:
            decision = json.loads(msg.data)

            if "_hmac" in decision:
                valid, reason = self._security.verify(decision)
                if not valid:
                    self.get_logger().warning(
                        f"Classifier HMAC {reason}"
                    )
                    if self._security.mode == SecurityMode.ENFORCE:
                        return

            if hasattr(self, '_supervisor') and self._security.get_stats().get("replay_count", 0) > 3:
                self._supervisor.record_fault(1)

            sub_id = decision.get("subscriber_id", "")
            state = decision.get("state", "UNKNOWN")
            self._policy_engine.on_classifier_update(sub_id, state, decision)

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

            # Ingest classifier snapshots into diagnostics (full decision data)
            decisions = self._policy_engine.get_subscriber_decisions()
            if decisions:
                self._diag_collector.ingest_classifier_snapshot(decisions)

            # Ingest security stats into diagnostics
            sec_stats = self._security.get_stats()
            if sec_stats.get("invalid_sig_count", 0) > 0 or sec_stats.get("replay_count", 0) > 0:
                self._diag_collector.ingest_classifier_snapshot({
                    "security": sec_stats,
                })

            # Evaluate safety supervisor each diagnostics tick
            queue_sizes = [q.qsize() for q in self._noncritical_queues.values()]
            overflow_count = sum(
                self._nc_policy.get_stats(tid).queue_overflow
                for tid in self._routes
            )
            mode_str, reason = self._supervisor.evaluate(
                queue_sizes, overflow_count, 0
            )
            self._diag_collector.set_global_mode(mode_str)

            # ── Safety mode overrides on noncritical policy ──────────────
            # Each mode applies its own user-configured policy from the
            # `modes` YAML section.  SafetySupervisor ALWAYS wins when it
            # enters EMERGENCY or FAILURE.
            supervisor_mode = self._supervisor.get_mode()
            bridge_cfg = self.config.get_bridge_config()
            routing = bridge_cfg.routing_policy

            if supervisor_mode == PolicyMode.EMERGENCY:
                emergency_cfg = routing.modes.get("emergency") if routing.modes else None
                if emergency_cfg is not None:
                    emergency_rate = emergency_cfg.noncritical_max_rate_hz
                    normal_cfg = routing.modes.get("normal")
                    normal_rate = normal_cfg.noncritical_max_rate_hz if normal_cfg else routing.noncritical_max_rate_hz

                    if emergency_rate == 0.0:
                        self.get_logger().error("SAFETY: EMERGENCY — all noncritical disabled")
                    elif emergency_rate >= normal_rate:
                        self.get_logger().error(
                            f"SAFETY: EMERGENCY entered but noncritical policy set to "
                            f"{emergency_rate} Hz by user override"
                        )
                    else:
                        self.get_logger().error(
                            f"SAFETY: EMERGENCY — noncritical reduced to "
                            f"{emergency_rate} Hz per user policy"
                        )
                else:
                    self.get_logger().error(
                        "SAFETY: EMERGENCY — no per-mode policy configured; "
                        "noncritical path blocked (default behaviour)"
                    )

                for tid in self._routes:
                    self._nc_policy.on_mode_change(tid, PolicyMode.EMERGENCY)

            elif supervisor_mode == PolicyMode.DEGRADED:
                for tid in self._routes:
                    self._nc_policy.on_mode_change(tid, PolicyMode.DEGRADED)

            elif supervisor_mode == PolicyMode.NORMAL:
                for tid in self._routes:
                    self._nc_policy.on_mode_change(tid, PolicyMode.NORMAL)

            # FAILURE is handled by is_shutdown_requested(), applied below

            if self._supervisor.is_shutdown_requested():
                failure_cfg = routing.modes.get("failure") if routing.modes else None
                failure_rate = failure_cfg.noncritical_max_rate_hz if failure_cfg else 0.0

                if failure_rate > 0.0:
                    self.get_logger().error(
                        f"SAFETY: FAILURE mode — user policy overrides shutdown. "
                        f"Noncritical={failure_rate} Hz. Proxy may be unstable."
                    )
                else:
                    self.get_logger().error("SAFETY: FAILURE mode — initiating shutdown")

                self._running = False
                for tid in self._routes:
                    self._nc_policy.on_mode_change(tid, PolicyMode.FAILURE)

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

        if hasattr(self, '_supervisor') and self._supervisor.get_mode() == PolicyMode.FAILURE:
            self.get_logger().error("ProxyNode shutdown: FAILURE mode active")

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
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node._shutdown_entities()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
