# classifier_node.py
"""
Adaptive Bridge Classifier Node — Step 10 Runtime Integration.

Embeds ProbeClient for active metric ingestion, runs periodic classifier
evaluation at configurable rate, and publishes ClassificationDecision
JSON payloads to /adaptive_bridge/classifier/state.

Architecture:
  ProbeClient (probe req/resp) -> get_stats() -> ProbeMetrics
    -> SubscriberClassifier.update() -> ClassificationDecision
    -> JSON publish on /adaptive_bridge/classifier/state
"""

import json
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .classifier_core import SubscriberClassifier
from .classifier_types import ALL_STATES
from .config_manager import ConfigManager
from .utils.probes import ProbeClient, stats_to_probe_metrics
from .utils.security import SecurityManager


class ClassifierNode(Node):
    """Classifier node with runtime probe ingestion and decision publishing."""

    def __init__(self, config_path: str = "") -> None:
        super().__init__("adaptive_bridge_classifier")

        self.declare_parameter("config_path", config_path or "")
        cp = self.get_parameter("config_path").get_parameter_value().string_value
        self._config_manager = ConfigManager(cp)
        clf_cfg = self._config_manager.get_classifier_config()
        probe_cfg = self._config_manager.get_probe_config()
        forced_ids = self._config_manager.get_forced_critical_ids()

        # If the classifier is disabled in config, skip all initialization.
        # The node still spins but produces no probe traffic or state output.
        if not clf_cfg.enabled:
            self._probe_client = None
            self._state_pub = None
            self._eval_timer = None
            self._classifier = None
            self._subscriber_label = ""
            self.get_logger().info(
                "ClassifierNode disabled via config — "
                "no probe traffic or state publishing"
            )
            return

        self._classifier = SubscriberClassifier(
            config=clf_cfg,
            forced_critical_ids=forced_ids if forced_ids else None,
        )

        self._probe_client = ProbeClient(
            node_name="adaptive_bridge_classifier_probe",
            rate_hz=probe_cfg.rate_hz,
            window_size=probe_cfg.window_size,
            timeout_ms=probe_cfg.timeout_ms,
            request_topic=probe_cfg.request_topic,
            response_topic=probe_cfg.response_topic,
        )
        self._probe_client.start()

        # Subscriber identity label — configurable in YAML, falls back to
        # the ProbeClient's sender ID for backward compatibility.
        self._subscriber_label = clf_cfg.subscriber_id

        self._state_pub = self.create_publisher(
            String, "/adaptive_bridge/classifier/state", 10
        )

        eval_period = 1.0 / max(0.1, clf_cfg.evaluate_rate_hz)
        self._eval_timer = self.create_timer(eval_period, self._on_evaluate)

        self._eval_count: int = 0
        self._error_count: int = 0
        self._last_eval_ts_ns: int = 0

        sec_cfg = self._config_manager.get_security_config()
        self._security = SecurityManager(
            mode=self._map_trust_mode(sec_cfg.trust_mode),
            hmac_secret=sec_cfg.hmac_secret,
            replay_window_ms=sec_cfg.replay_window_ms,
        )
        self._security.set_log_callback(self.get_logger().warning)

        self.get_logger().info(
            f"ClassifierNode active — "
            f"eval={clf_cfg.evaluate_rate_hz}Hz, "
            f"hysteresis={clf_cfg.hysteresis_count}, "
            f"demote_rtt={clf_cfg.demote_rtt_ms}ms, "
            f"demote_loss={clf_cfg.demote_loss_threshold:.0%}, "
            f"probe_req={probe_cfg.request_topic}, "
            f"probe_resp={probe_cfg.response_topic}, "
            f"state_topic=/adaptive_bridge/classifier/state, "
            f"allow_unknown={clf_cfg.allow_unknown_state}"
        )

    def _on_evaluate(self) -> None:
        """Periodic evaluation: sample probes -> classify -> publish."""
        if self._eval_timer is None:  # disabled mode, timer should never fire
            return
        self._eval_count += 1
        now_ns = time.monotonic_ns()
        self._last_eval_ts_ns = now_ns

        try:
            stats = self._probe_client.get_stats()
            metrics = stats_to_probe_metrics(stats)

            subscriber_id = (self._subscriber_label if self._subscriber_label
                             else self._probe_client._sender_id)
            decision = self._classifier.update(subscriber_id, metrics, now_ns=now_ns)

            payload_dict = decision.to_dict()
            payload_dict["eval_count"] = self._eval_count
            payload_dict["error_count"] = self._error_count
            payload_dict["confidence"] = None

            self._security.sign(payload_dict)

            msg = String()
            msg.data = json.dumps(payload_dict)
            self._state_pub.publish(msg)

        except Exception as e:
            self._error_count += 1
            self.get_logger().error(
                f"Classifier evaluation error (eval #{self._eval_count}): {e}"
            )

    @staticmethod
    def _map_trust_mode(trust_mode: str) -> str:
        return {
            "default_deny": "enforce", "permissive": "log_only", "off": "off"
        }.get(trust_mode, "off")

    def get_classifier(self) -> SubscriberClassifier:
        """Expose the core classifier for diagnostics and integration."""
        return self._classifier

    def get_probe_client(self) -> ProbeClient:
        """Expose the probe client for inspection in tests and diagnostics."""
        return self._probe_client

    def get_error_count(self) -> int:
        """Return cumulative evaluation error count."""
        return self._error_count

    def get_eval_count(self) -> int:
        """Return cumulative evaluation cycle count."""
        return self._eval_count

    def destroy(self) -> None:
        if self._probe_client is not None:
            try:
                self._probe_client.stop()
            except Exception:
                pass
            try:
                self._probe_client.destroy()
            except Exception:
                pass
        super().destroy_node()


def main(args=None) -> None:
    """Run the classifier node."""
    from rclpy.executors import MultiThreadedExecutor

    rclpy.init(args=args)
    node = ClassifierNode()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    if node._probe_client is not None:
        executor.add_node(node._probe_client)
    try:
        executor.spin()
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        executor.shutdown()
        node.destroy()
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
