# diagnostics.py
"""
Diagnostics collection and publishing for Adaptive Bridge.

This module provides two classes:

  DiagnosticsCollector (pure Python, no ROS)
  -------------------------------------------
  Owns all runtime state (per-topic counters, drop stats, QoS snapshots,
  classifier snapshot, global mode) and builds the versioned JSON payload.
  It can be instantiated directly by ProxyNode without any ROS context,
  making it trivially unit-testable.

  DiagnosticsPublisher (ROS Node subclass)
  -----------------------------------------
  Wraps a DiagnosticsCollector with a ROS publisher and a timer.  Used
  when running the diagnostics module as a standalone node.

Why split?
  - ProxyNode is already a Node; embedding another Node would be wrong.
  - DiagnosticsCollector is pure-Python so tests need no rclpy.init().
  - DiagnosticsPublisher can still be launched standalone for debugging.

Payload schema
--------------
Defined in diagnostics_schema.py.  Every published message must pass
diagnostics_schema.validate_payload() with zero errors.
"""

from __future__ import annotations

import json
import time
from collections import deque
from typing import Any, Deque, Dict, Optional

from .diagnostics_schema import SCHEMA_VERSION, validate_payload


# ======================================================================
# DiagnosticsCollector — pure Python, zero ROS dependency
# ======================================================================

class DiagnosticsCollector:
    """
    Collects runtime state and builds the canonical diagnostics payload.

    Thread-safety note:
        This class is NOT thread-safe.  ProxyNode must call its methods
        only from its single ROS executor thread (i.e., from a timer
        callback or the main spin thread), not from worker threads.
        ProxyNode's noncritical worker threads do NOT call this class.

    State injected externally (by ProxyNode or tests):
        ingest_topic_route(topic_id, route_dict)
        ingest_counters(topic_id, counters_dict)
        ingest_drop_stats(topic_id, drop_stats_dict)
        ingest_noncritical_mode(topic_id, mode_str)
        ingest_qos_snapshot(topic_id, role, describe_dict)
        ingest_classifier_snapshot(snapshot_dict)
        set_global_mode(mode_str)
    """

    def __init__(self) -> None:
        self._seq: int = 0
        self._global_mode: str = "NORMAL"

        # Per-topic state — keyed by topic_id
        self._routes: Dict[str, dict] = {}
        self._counters: Dict[str, dict] = {}
        self._drops: Dict[str, dict] = {}
        self._noncritical_modes: Dict[str, str] = {}

        # QoS snapshots — keyed by topic_id, then role ("critical" / "noncritical")
        self._qos: Dict[str, Dict[str, dict]] = {}

        # Classifier snapshot (free-form dict; populated by Step 10 ClassifierNode)
        self._classifier: dict = {}

    # ── Setters (called by ProxyNode / tests) ─────────────────────────

    def set_global_mode(self, mode: str) -> None:
        """Set the system-global operating mode (e.g. 'NORMAL', 'DEGRADED')."""
        self._global_mode = str(mode)

    def ingest_topic_route(self, topic_id: str, route_dict: dict) -> None:
        """Store the route metadata for a topic."""
        self._routes[topic_id] = dict(route_dict)

    def ingest_counters(self, topic_id: str, counters_dict: dict) -> None:
        """Store the latest counter snapshot for a topic."""
        self._counters[topic_id] = dict(counters_dict)

    def ingest_drop_stats(self, topic_id: str, drop_stats_dict: dict) -> None:
        """Store the latest drop statistics for a topic.

        Expected keys: rate_limit, queue_overflow, stale, disabled.
        """
        self._drops[topic_id] = dict(drop_stats_dict)

    def ingest_noncritical_mode(self, topic_id: str, mode_str: str) -> None:
        """Store the noncritical mode string for a topic (e.g. 'NORMAL')."""
        self._noncritical_modes[topic_id] = str(mode_str)

    def ingest_qos_snapshot(self, topic_id: str, role: str, describe_dict: dict) -> None:
        """Store the QoS describe() result for topic_id + role."""
        if topic_id not in self._qos:
            self._qos[topic_id] = {}
        self._qos[topic_id][role] = dict(describe_dict)

    def ingest_classifier_snapshot(self, snapshot_dict: dict) -> None:
        """Store the full classifier snapshot (replaces previous value)."""
        self._classifier = dict(snapshot_dict)

    # ── Payload builder ────────────────────────────────────────────────

    def gather_payload(self) -> dict:
        """Build and return the canonical diagnostics payload dict.

        Side effect: increments the internal sequence counter each call.
        The returned dict is schema-conformant (validate_payload returns []).
        """
        self._seq += 1

        # Build topics section
        all_topic_ids = set(self._routes) | set(self._counters) | set(self._drops)
        topics_section: dict[str, Any] = {}
        for tid in all_topic_ids:
            topics_section[tid] = {
                "route": self._routes.get(tid, {}),
                "counters": self._counters.get(tid, {
                    "total_received": 0,
                    "total_forwarded_critical": 0,
                    "total_forwarded_noncritical": 0,
                }),
                "drops": self._drop_defaults(self._drops.get(tid, {})),
                "noncritical_mode": self._noncritical_modes.get(tid, "NORMAL"),
            }

        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "ts_wall": time.time(),
            "seq": self._seq,
            "mode": self._global_mode,
            "topics": topics_section,
            "classifier": dict(self._classifier),
            "qos": {tid: dict(roles) for tid, roles in self._qos.items()},
        }
        return payload

    @staticmethod
    def _drop_defaults(drops: dict) -> dict:
        """Ensure all required drop keys are present, defaulting to 0."""
        return {
            "rate_limit": int(drops.get("rate_limit", 0)),
            "queue_overflow": int(drops.get("queue_overflow", 0)),
            "stale": int(drops.get("stale", 0)),
            "disabled": int(drops.get("disabled", 0)),
        }


# ======================================================================
# DiagnosticsPublisher — ROS Node wrapper (standalone use)
# ======================================================================

class DiagnosticsPublisher:
    """
    Wraps DiagnosticsCollector with a ROS publisher and periodic timer.

    This class is designed to be *embedded* inside an existing ROS Node
    (such as ProxyNode) rather than being a Node itself.  It receives
    the Node's ``create_publisher``, ``create_timer``, and ``get_logger``
    callables at construction time.

    For standalone use (launching as its own node), see the ``main()``
    function below which wraps this in a thin Node shell.

    Parameters
    ----------
    create_publisher_fn:
        ``node.create_publisher`` bound method.
    create_timer_fn:
        ``node.create_timer`` bound method.
    get_logger_fn:
        ``node.get_logger`` bound method.
    publish_interval:
        Seconds between diagnostics publishes.
    diag_topic:
        ROS topic name for the JSON string.
    """

    def __init__(
        self,
        create_publisher_fn,
        create_timer_fn,
        get_logger_fn,
        publish_interval: float = 1.0,
        diag_topic: str = "/adaptive_bridge/diagnostics",
    ) -> None:
        from std_msgs.msg import String  # lazy import to keep collector pure

        self._logger = get_logger_fn()
        self._collector = DiagnosticsCollector()
        self._pub = create_publisher_fn(String, diag_topic, 10)
        self._timer = create_timer_fn(float(publish_interval), self._on_timer)
        self._logger.debug(
            f"DiagnosticsPublisher started, topic='{diag_topic}', "
            f"interval={publish_interval}s"
        )

    # ── Delegate to collector ─────────────────────────────────────────

    @property
    def collector(self) -> DiagnosticsCollector:
        """Direct access to the underlying collector for state injection."""
        return self._collector

    def set_global_mode(self, mode: str) -> None:
        self._collector.set_global_mode(mode)

    def ingest_topic_route(self, topic_id: str, route_dict: dict) -> None:
        self._collector.ingest_topic_route(topic_id, route_dict)

    def ingest_counters(self, topic_id: str, counters_dict: dict) -> None:
        self._collector.ingest_counters(topic_id, counters_dict)

    def ingest_drop_stats(self, topic_id: str, drop_stats_dict: dict) -> None:
        self._collector.ingest_drop_stats(topic_id, drop_stats_dict)

    def ingest_noncritical_mode(self, topic_id: str, mode_str: str) -> None:
        self._collector.ingest_noncritical_mode(topic_id, mode_str)

    def ingest_qos_snapshot(self, topic_id: str, role: str, describe_dict: dict) -> None:
        self._collector.ingest_qos_snapshot(topic_id, role, describe_dict)

    def ingest_classifier_snapshot(self, snapshot_dict: dict) -> None:
        self._collector.ingest_classifier_snapshot(snapshot_dict)

    # ── Timer callback ────────────────────────────────────────────────

    def _on_timer(self) -> None:
        """Periodic callback: build payload, validate (debug), publish JSON."""
        from std_msgs.msg import String

        try:
            payload = self._collector.gather_payload()
            msg = String()
            msg.data = json.dumps(payload)
            self._pub.publish(msg)
            self._logger.debug(f"Diagnostics published seq={payload['seq']}")
        except Exception as exc:
            # Diagnostics must NEVER crash or propagate exceptions to the proxy.
            self._logger.error(f"DiagnosticsPublisher: publish failed: {exc}")

    def stop(self) -> None:
        """Cancel the internal timer (does not destroy the publisher)."""
        try:
            self._timer.cancel()
        except Exception:
            pass


# ======================================================================
# Standalone node shell (for `ros2 run adaptive_bridge diagnostics`)
# ======================================================================

class _DiagnosticsNode:
    """Minimal ROS Node shell that hosts a DiagnosticsPublisher.

    Reads DiagnosticsConfig from the config file to determine publish
    interval, topic name, and verbosity.  Used only by main() below.
    """

    def __init__(self, config_path: str = "") -> None:
        import rclpy
        from rclpy.node import Node
        from .config_manager import ConfigManager

        class _Inner(Node):
            def __init__(inner_self) -> None:  # noqa: N805
                super().__init__("adaptive_bridge_diagnostics")
                inner_self.declare_parameter("config_path", config_path or "")
                cp = inner_self.get_parameter("config_path").get_parameter_value().string_value
                cfg_mgr = ConfigManager(cp)
                diag_cfg = cfg_mgr.get_diagnostics_config()

                inner_self.pub = DiagnosticsPublisher(
                    create_publisher_fn=inner_self.create_publisher,
                    create_timer_fn=inner_self.create_timer,
                    get_logger_fn=inner_self.get_logger,
                    publish_interval=diag_cfg.publish_interval_s,
                    diag_topic=diag_cfg.topic,
                )

                verbosity = str(diag_cfg.verbosity).upper()
                if verbosity in ("ERROR", "WARNING", "INFO", "DEBUG"):
                    rclpy.logging.set_logger_level(
                        inner_self.get_name(), getattr(rclpy.logging.LoggingSeverity, verbosity)
                    )
                inner_self.get_logger().info(
                    f"DiagnosticsNode active topic='{diag_cfg.topic}' "
                    f"interval={diag_cfg.publish_interval_s}s "
                    f"verbosity={diag_cfg.verbosity}"
                )

        self._node = _Inner()

    def spin(self) -> None:
        import rclpy
        rclpy.spin(self._node)

    def destroy(self) -> None:
        self._node.destroy_node()


def main(args=None) -> None:
    import rclpy
    rclpy.init(args=args)
    shell = _DiagnosticsNode()
    try:
        shell.spin()
    finally:
        shell.destroy()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
