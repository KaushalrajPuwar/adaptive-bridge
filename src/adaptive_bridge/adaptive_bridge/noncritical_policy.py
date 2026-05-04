"""
Token-bucket rate limiter and drop-policy engine for noncritical topics.

The :class:`NoncriticalPolicyEngine` implements per-topic rate limiting
(token bucket), staleness / TTL rejection, queue-overflow dropping, and
mode-driven policy switching (``NORMAL`` → ``DEGRADED`` → ``DISABLED``).
The critical publish path is guaranteed to never block on noncritical
policy operations.
"""
import time
from typing import Tuple, Optional, Dict
from dataclasses import dataclass

from .config_types import BridgeConfig
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

    Supports per-mode rate limits via the ``modes`` YAML section.  When a
    :class:`PolicyMode` changes via :meth:`on_mode_change`, the effective
    token-bucket refill rate for that topic is updated to the user-configured
    ``noncritical_max_rate_hz`` for that mode.  If no ``modes`` section exists
    in the config (backward compatibility), the top-level
    ``noncritical_max_rate_hz`` is used for every mode.
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
        self._rate_limits: Dict[str, float] = {}  # per-topic dynamic rate from current mode
        self._mode_policies: Dict[str, dict] = {}  # per-topic per-mode settings (reserved)
        self._stats: Dict[str, DropStats] = {}

    def _init_topic(self, topic_id: str, now_ns: int) -> None:
        if topic_id not in self._tokens:
            self._tokens[topic_id] = float(self.max_queue) # Start full for burst
            self._last_refill_ns[topic_id] = now_ns
            self._mode[topic_id] = PolicyMode.NORMAL
            self._rate_limits[topic_id] = self.rate_hz  # initial fallback to top-level rate
            self._stats[topic_id] = DropStats()

    def allow_publish(self, topic_id: str, msg_ts_ns: int, now_ns: Optional[int] = None) -> Tuple[bool, Optional[str]]:
        if now_ns is None:
            now_ns = time.time_ns()
            
        self._init_topic(topic_id, now_ns)
        
        # 1. Disabled Check
        # NOTE: FAILURE is deliberately NOT in this list — the user may
        # configure a non-zero failure rate to keep noncritical flowing
        # during the shutdown window.  The rate-limiting step below will
        # block when the user-configured (or default 0.0) rate is 0.0.
        if not self.enabled or self._mode[topic_id] == PolicyMode.DISABLED:
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
            
        # 3. Rate Limit (Token Bucket) — use per-topic dynamic rate from current mode
        effective_rate = self._rate_limits.get(topic_id, self.rate_hz)
        elapsed_ns = now_ns - self._last_refill_ns[topic_id]
        if elapsed_ns > 0:
            added_tokens = (elapsed_ns / 1_000_000_000.0) * effective_rate
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

    def _get_mode_rate(self, mode: PolicyMode) -> float:
        """Look up the user-configured rate for *mode*, with backward-compat fallback.

        Returns
        -------
        float
            The ``noncritical_max_rate_hz`` for the given mode, or a safe
            default if no per-mode config exists.
        """
        routing = self.config.routing_policy
        mode_key = mode.value.lower()
        if routing.modes and mode_key in routing.modes:
            return routing.modes[mode_key].noncritical_max_rate_hz
        # No per-mode config for this key — safe default per mode
        if mode in (PolicyMode.FAILURE, PolicyMode.EMERGENCY, PolicyMode.DISABLED):
            return 0.0  # block
        # NORMAL or DEGRADED: use the top-level configured rate
        return self.rate_hz

    def on_mode_change(self, topic_id: str, mode: PolicyMode) -> None:
        """Update the effective rate limit for a topic based on the given mode.

        Delegates rate lookup to :meth:`_get_mode_rate` which handles
        user-configured policies and backward-compat defaults.
        """
        self._init_topic(topic_id, time.time_ns())
        self._mode[topic_id] = mode
        self._mode_policies[topic_id] = {mode.value.lower(): {}}
        self._rate_limits[topic_id] = self._get_mode_rate(mode)
