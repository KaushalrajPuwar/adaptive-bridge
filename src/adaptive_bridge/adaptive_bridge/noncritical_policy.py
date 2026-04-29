# src/adaptive_bridge/adaptive_bridge/noncritical_policy.py
import time
from typing import Tuple, Optional, Dict
from dataclasses import dataclass

from .config_manager import BridgeConfig
from .qos_manager import QoSManager
from .models import PolicyMode


@dataclass
class DropStats:
    rate_limit: int = 0
    queue_overflow: int = 0
    stale: int = 0
    disabled: int = 0


class NoncriticalPolicyEngine:
    """
    Engine to enforce noncritical degradation logic (rate limiting, queue drops, staleness).
    """

    def __init__(self, config: BridgeConfig, qos_manager: QoSManager):
        self.config = config
        self.qos_manager = qos_manager
        
        self.enabled = config.routing_policy.noncritical_enabled
        self.rate_hz = config.routing_policy.noncritical_max_rate_hz
        self.max_queue = config.safety.max_noncritical_queue
        
        # Token bucket state per topic
        self._tokens: Dict[str, float] = {}
        self._last_refill_ns: Dict[str, int] = {}
        self._mode: Dict[str, PolicyMode] = {}
        self._stats: Dict[str, DropStats] = {}

    def _init_topic(self, topic_id: str, now_ns: int):
        if topic_id not in self._tokens:
            self._tokens[topic_id] = float(self.max_queue) # Start full for burst
            self._last_refill_ns[topic_id] = now_ns
            self._mode[topic_id] = PolicyMode.NORMAL
            self._stats[topic_id] = DropStats()

    def allow_publish(self, topic_id: str, msg_ts_ns: int, now_ns: Optional[int] = None) -> Tuple[bool, Optional[str]]:
        if now_ns is None:
            now_ns = time.time_ns()
            
        self._init_topic(topic_id, now_ns)
        
        # 1. Disabled Check
        if not self.enabled or self._mode[topic_id] in (PolicyMode.DISABLED, PolicyMode.FAILURE):
            return False, "disabled"
            
        # 2. Staleness Check
        desc = self.qos_manager.describe(topic_id, "noncritical")
        lifespan_ms = desc.get("lifespan_ms")
        if lifespan_ms is None:
            lifespan_ms = self.config.routing_policy.stale_threshold_ms
            
        stale_threshold_ns = lifespan_ms * 1_000_000
        age_ns = now_ns - msg_ts_ns
        if age_ns > stale_threshold_ns:
            return False, "stale"
            
        # 3. Rate Limit (Token Bucket)
        elapsed_ns = now_ns - self._last_refill_ns[topic_id]
        if elapsed_ns > 0:
            added_tokens = (elapsed_ns / 1_000_000_000.0) * self.rate_hz
            self._tokens[topic_id] = min(float(self.max_queue), self._tokens[topic_id] + added_tokens)
            self._last_refill_ns[topic_id] = now_ns
            
        if self._tokens[topic_id] >= 1.0:
            self._tokens[topic_id] -= 1.0
            return True, None
            
        return False, "rate_limit"

    def record_drop(self, topic_id: str, reason: str) -> None:
        if topic_id not in self._stats:
            self._init_topic(topic_id, time.time_ns())
            
        stats = self._stats[topic_id]
        if reason == "disabled":
            stats.disabled += 1
        elif reason == "stale":
            stats.stale += 1
        elif reason == "rate_limit":
            stats.rate_limit += 1
        elif reason == "queue_overflow":
            stats.queue_overflow += 1

    def get_stats(self, topic_id: str) -> DropStats:
        return self._stats.get(topic_id, DropStats())

    def on_mode_change(self, topic_id: str, mode: PolicyMode) -> None:
        self._init_topic(topic_id, time.time_ns())
        self._mode[topic_id] = mode
