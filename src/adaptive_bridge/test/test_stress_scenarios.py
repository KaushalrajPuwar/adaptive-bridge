# src/tests/test_stress_scenarios.py
"""
Stress tests for Step 15 — Test Pyramid Completion.

All tests are pure Python (no rclpy).  They validate component behaviour
under sustained/high-throughput demand rather than hardware-level stress.
"""
from __future__ import annotations

import sys
import os
import queue as _queue

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "adaptive_bridge"),
)
sys.path.insert(0, os.path.dirname(__file__))

import time
import pytest

from adaptive_bridge.noncritical_policy import NoncriticalPolicyEngine, DropStats
from adaptive_bridge.safety_supervisor import SafetySupervisor
from adaptive_bridge.models import PolicyMode
from fixtures.fixtures import make_test_config


# ------------------------------------------------------------------
# A. Sustained high-rate ingress (token bucket)
# ------------------------------------------------------------------

class TestTokenBucket:
    def test_token_bucket_depletes_under_sustained_load(self):
        """Request 100 publishes at zero interval with rate_hz=10.
        Verify that the bucket limits throughput and subsequent requests
        are rate-limited."""
        cfg = make_test_config({"routing_policy": {"noncritical_max_rate_hz": 10.0}})
        from adaptive_bridge.config_types import BridgeConfig
        bridge_cfg = BridgeConfig.from_dict(cfg)
        from adaptive_bridge.qos_manager import QoSManager
        qos = QoSManager(
            qos_profiles=cfg["qos_profiles"],
            topic_qos_profiles=cfg["topic_qos_profiles"],
        )
        engine = NoncriticalPolicyEngine(bridge_cfg, qos)
        now_ns = time.time_ns()

        allowed_count = 0
        for _ in range(100):
            ok, _ = engine.allow_publish("test_scan", now_ns, now_ns)
            if ok:
                allowed_count += 1

        # With rate_hz=10 and max_queue=50, initial burst is at most 50 tokens.
        # 10Hz * 1s = 10 tokens per second. At time=0, the bucket has max_queue
        # tokens. After depletion, no more until refill.
        assert allowed_count <= 55, (
            f"Sustained load should not exceed initial burst, got {allowed_count}"
        )
        assert allowed_count >= 1, "At least one request should be allowed"

    def test_token_bucket_refills_and_allows_after_wait(self):
        """Deplete bucket, then wait 2 seconds — token bucket should
        refill and allow more publishes."""
        cfg = make_test_config({"routing_policy": {"noncritical_max_rate_hz": 10.0}})
        from adaptive_bridge.config_types import BridgeConfig
        bridge_cfg = BridgeConfig.from_dict(cfg)
        from adaptive_bridge.qos_manager import QoSManager
        qos = QoSManager(
            qos_profiles=cfg["qos_profiles"],
            topic_qos_profiles=cfg["topic_qos_profiles"],
        )
        engine = NoncriticalPolicyEngine(bridge_cfg, qos)
        now_ns = time.time_ns()

        # Deplete the bucket — all 100 requests at once
        for _ in range(100):
            engine.allow_publish("test_scan", now_ns, now_ns)

        # Advance time by 2 seconds — enough for 20 new tokens at 10Hz
        now_ns += 2_000_000_000

        allowed_after = 0
        for _ in range(50):
            ok, _ = engine.allow_publish("test_scan", now_ns, now_ns)
            if ok:
                allowed_after += 1

        assert allowed_after > 5, (
            f"Expected refill after wait, got {allowed_after}"
        )
        assert allowed_after <= 25, (
            f"Refill should not exceed capacity, got {allowed_after}"
        )

    def test_max_queue_caps_token_bucket(self):
        """Token bucket never exceeds max_queue during idle periods."""
        cfg = make_test_config({"safety": {"max_noncritical_queue": 5}})
        from adaptive_bridge.config_types import BridgeConfig
        bridge_cfg = BridgeConfig.from_dict(cfg)
        from adaptive_bridge.qos_manager import QoSManager
        qos = QoSManager(
            qos_profiles=cfg["qos_profiles"],
            topic_qos_profiles=cfg["topic_qos_profiles"],
        )
        engine = NoncriticalPolicyEngine(bridge_cfg, qos)
        now_ns = time.time_ns()

        # Idle for 10 simulated seconds
        now_ns += 10_000_000_000

        # After 10s idle, bucket should have at most max_queue tokens
        allowed = 0
        for _ in range(10):
            ok, _ = engine.allow_publish("test_scan", now_ns, now_ns)
            if ok:
                allowed += 1

        assert allowed <= 5, (
            f"Token bucket exceeded max_queue after idle, got {allowed}"
        )


# ------------------------------------------------------------------
# B. Drop counters under sustained demand
# ------------------------------------------------------------------

class TestDropCounters:
    def test_rate_limit_drop_counter_increments(self):
        """After bucket depletion, each denied request should
        have a corresponding rate_limit reason."""
        cfg = make_test_config({"routing_policy": {"noncritical_max_rate_hz": 10.0}})
        from adaptive_bridge.config_types import BridgeConfig
        bridge_cfg = BridgeConfig.from_dict(cfg)
        from adaptive_bridge.qos_manager import QoSManager
        qos = QoSManager(
            qos_profiles=cfg["qos_profiles"],
            topic_qos_profiles=cfg["topic_qos_profiles"],
        )
        engine = NoncriticalPolicyEngine(bridge_cfg, qos)
        now_ns = time.time_ns()

        rate_limited = 0
        for _ in range(100):
            ok, reason = engine.allow_publish("test_scan", now_ns, now_ns)
            if not ok and reason == "rate_limit":
                engine.record_drop("test_scan", "rate_limit")
                rate_limited += 1

        stats = engine.get_stats("test_scan")
        assert rate_limited > 0, f"Expected some rate-limited, got {rate_limited}"
        assert stats.rate_limit == rate_limited, (
            f"Rate limit counter mismatch: stats={stats.rate_limit}, denied={rate_limited}"
        )

    def test_stale_drops_increment_under_sustained_old_messages(self):
        """50 messages all with timestamps older than stale_threshold
        should all be rejected as stale."""
        cfg = make_test_config({"routing_policy": {"stale_threshold_ms": 500}})
        from adaptive_bridge.config_types import BridgeConfig
        bridge_cfg = BridgeConfig.from_dict(cfg)
        from adaptive_bridge.qos_manager import QoSManager
        qos = QoSManager(
            qos_profiles=cfg["qos_profiles"],
            topic_qos_profiles=cfg["topic_qos_profiles"],
        )
        engine = NoncriticalPolicyEngine(bridge_cfg, qos)
        now_ns = time.time_ns()
        old_ts = now_ns - 2_000_000_000  # 2 seconds ago (> 500ms stale)

        stale_count = 0
        for _ in range(50):
            ok, reason = engine.allow_publish("test_scan", old_ts, now_ns)
            if not ok and reason == "stale":
                engine.record_drop("test_scan", "stale")
                stale_count += 1

        stats = engine.get_stats("test_scan")
        assert stale_count == 50, f"Expected all 50 stale, got {stale_count}"
        assert stats.stale == 50, f"DropStats.stale should be 50, got {stats.stale}"

    def test_queue_overflow_drops_counted(self):
        """Verify queue overflow drops are counted when put_nowait fails."""
        engine = NoncriticalPolicyEngine.__new__(NoncriticalPolicyEngine)
        engine._tokens = {}
        engine._last_refill_ns = {}
        engine._mode = {}
        engine._stats = {"test_topic": DropStats()}

        test_queue = _queue.Queue(maxsize=3)
        for i in range(3):
            test_queue.put_nowait(i)

        overflow_count = 0
        for _ in range(5):
            try:
                test_queue.put_nowait("overflow")
            except _queue.Full:
                engine.record_drop("test_topic", "queue_overflow")
                overflow_count += 1

        assert overflow_count == 5, f"Expected 5 overflow attempts, got {overflow_count}"
        assert engine._stats["test_topic"].queue_overflow == 5, (
            f"DropStats should show 5 overflow, got {engine._stats['test_topic'].queue_overflow}"
        )


# ------------------------------------------------------------------
# C. Recovery transitions
# ------------------------------------------------------------------

class TestRecoveryTransitions:
    def test_full_recovery_cycle(self):
        """Drive SafetySupervisor through pressure -> DEGRADED -> overflow
        -> EMERGENCY -> clean -> DEGRADED -> normal."""
        sup = SafetySupervisor(
            degrade_windows=2, restore_windows=3,
            degrade_queue_pct=0.50, restore_low_pct=0.10, restore_mid_pct=0.30,
            max_noncritical_queue=100,
        )

        # Phase 1: pressure -> DEGRADED
        for _ in range(2):
            sup.evaluate([60], 0, 0)
        assert sup.get_mode() == PolicyMode.DEGRADED

        # Phase 2: overflow -> EMERGENCY
        for _ in range(2):
            sup.evaluate([60], 1, 0)
        assert sup.get_mode() == PolicyMode.EMERGENCY

        # Phase 3: clean -> DEGRADED (needs 3 windows below 30%)
        for _ in range(3):
            sup.evaluate([20], 0, 0)
        assert sup.get_mode() == PolicyMode.DEGRADED

        # Phase 4: clean -> NORMAL (needs 3 windows below 10%)
        for _ in range(3):
            sup.evaluate([5], 0, 0)
        assert sup.get_mode() == PolicyMode.NORMAL

    def test_safety_noncritical_lockout(self):
        """In DEGRADED mode, the supervisor's mode overrides any per-topic
        setting — even when clean metrics return."""
        sup = SafetySupervisor(
            degrade_windows=1, restore_windows=3,
            degrade_queue_pct=0.50, restore_low_pct=0.10, restore_mid_pct=0.30,
            max_noncritical_queue=100,
        )

        # Drive to DEGRADED
        sup.evaluate([60], 0, 0)

        # Even with clean metrics, a single window doesn't recover (needs 3)
        sup.evaluate([5], 0, 0)
        sup.evaluate([5], 0, 0)

        # Should still be DEGRADED (only 2 clean windows, need 3)
        assert sup.get_mode() == PolicyMode.DEGRADED, (
            "Safety supervisor should stay DEGRADED until restore_windows threshold"
        )

        # Third clean window
        sup.evaluate([5], 0, 0)
        assert sup.get_mode() == PolicyMode.NORMAL

    def test_error_count_triggers_failure(self):
        """Cumulative component errors eventually trigger FAILURE
        regardless of queue metrics."""
        sup = SafetySupervisor(degrade_windows=3, max_noncritical_queue=100)
        # Inject errors directly
        sup.record_fault(5)
        sup.record_fault(5)
        mode, _ = sup.evaluate([0], 0, 0)
        assert sup.get_mode() == PolicyMode.FAILURE
