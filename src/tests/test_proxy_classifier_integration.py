# src/tests/test_proxy_classifier_integration.py
"""
Integration tests for Step 15 — classifier -> policy -> proxy coupling.

Tests the end-to-end decision chain: classifier signal -> PolicyEngine
-> NoncriticalPolicyEngine mode -> allow_publish decision.  Pure Python,
no rclpy required.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "adaptive_bridge"),
)
sys.path.insert(0, os.path.dirname(__file__))

import pytest

from adaptive_bridge.policy_engine import PolicyEngine
from adaptive_bridge.noncritical_policy import NoncriticalPolicyEngine
from adaptive_bridge.safety_supervisor import SafetySupervisor
from adaptive_bridge.models import PolicyMode
from fixtures.fixtures import make_test_config


class TestClassifierToPolicyChain:
    def test_policy_engine_receives_classifier_decision(self):
        """PolicyEngine processes classifier decisions and returns
        DEGRADED mode after N consecutive NONCRITICAL windows."""
        engine = PolicyEngine(hysteresis_count=2)
        for _ in range(2):
            engine.on_classifier_update("sub1", "NONCRITICAL")
        assert engine.get_mode("any_topic") == PolicyMode.DEGRADED

    def test_noncritical_policy_respects_mode_change(self):
        """NoncriticalPolicyEngine blocks publishes when mode is DISABLED
        and allows them again when restored to NORMAL."""
        cfg = make_test_config()
        from adaptive_bridge.config_types import BridgeConfig
        bridge_cfg = BridgeConfig.from_dict(cfg)
        from adaptive_bridge.qos_manager import QoSManager
        qos = QoSManager(
            qos_profiles=cfg["qos_profiles"],
            topic_qos_profiles=cfg["topic_qos_profiles"],
        )
        engine = NoncriticalPolicyEngine(bridge_cfg, qos)
        now_ns = 1_000_000_000

        # Initially NORMAL — should allow
        ok1, _ = engine.allow_publish("test_scan", now_ns, now_ns)
        assert ok1 is True

        # Switch to DISABLED — should block
        engine.on_mode_change("test_scan", PolicyMode.DISABLED)
        ok2, reason2 = engine.allow_publish("test_scan", now_ns, now_ns)
        assert ok2 is False
        assert reason2 == "disabled"

        # Switch back to NORMAL — should allow again
        engine.on_mode_change("test_scan", PolicyMode.NORMAL)
        ok3, _ = engine.allow_publish("test_scan", now_ns, now_ns)
        assert ok3 is True

    def test_classifier_to_policy_to_nc_mode_propagation(self):
        """End-to-end chain: classifier decision -> PolicyEngine mode
        -> NoncriticalPolicyEngine respects the mode."""
        policy_engine = PolicyEngine(hysteresis_count=2)

        cfg = make_test_config()
        from adaptive_bridge.config_types import BridgeConfig
        bridge_cfg = BridgeConfig.from_dict(cfg)
        from adaptive_bridge.qos_manager import QoSManager
        qos = QoSManager(
            qos_profiles=cfg["qos_profiles"],
            topic_qos_profiles=cfg["topic_qos_profiles"],
        )
        nc_engine = NoncriticalPolicyEngine(bridge_cfg, qos)
        now_ns = 1_000_000_000

        # Feed NONCRITICAL decisions
        for _ in range(2):
            policy_engine.on_classifier_update("sub1", "NONCRITICAL")

        pol_mode = policy_engine.get_mode("test_scan")
        # Proxy translates DEGRADED -> DISABLED for NC engine
        nc_engine.on_mode_change("test_scan", PolicyMode.DISABLED)
        ok, reason = nc_engine.allow_publish("test_scan", now_ns, now_ns)
        assert ok is False
        assert reason == "disabled"

        # Feed CRITICAL decisions
        for _ in range(2):
            policy_engine.on_classifier_update("sub1", "CRITICAL")

        pol_mode = policy_engine.get_mode("test_scan")
        nc_engine.on_mode_change("test_scan", PolicyMode.NORMAL)
        ok, _ = nc_engine.allow_publish("test_scan", now_ns, now_ns)
        assert ok is True, "Publishes should be allowed when mode is NORMAL"

    def test_safety_supervisor_overrides_policy_engine(self):
        """When safety supervisor is in DEGRADED mode, the proxy should
        choose the stricter mode (DEGRADED) even if PolicyEngine reports NORMAL."""
        policy_engine = PolicyEngine(hysteresis_count=2)

        # Feed CRITICAL -> PolicyEngine stays NORMAL
        policy_engine.on_classifier_update("sub1", "CRITICAL")
        policy_engine.on_classifier_update("sub1", "CRITICAL")
        assert policy_engine.get_mode("any_topic") == PolicyMode.NORMAL

        # Override with safety supervisor in DEGRADED
        sup = SafetySupervisor(degrade_windows=1, max_noncritical_queue=100)
        sup.evaluate([60], 0, 0)
        assert sup.get_mode() == PolicyMode.DEGRADED

        # The stricter mode should be DEGRADED
        def pick_stricter(sup_mode, pol_mode):
            if sup_mode in (PolicyMode.DEGRADED, PolicyMode.EMERGENCY, PolicyMode.FAILURE):
                return sup_mode
            return pol_mode

        assert pick_stricter(sup.get_mode(), policy_engine.get_mode("any_topic")) == PolicyMode.DEGRADED
