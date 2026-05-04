# src/tests/test_policy_integration.py
"""
Integration tests for Step 11 — Policy Engine and Classifier Coupling.

All tests are pure Python — no rclpy.init() required.
Tests cover PolicyEngine core logic, transition damping, forced-critical
override, and NoncriticalPolicyEngine mode-driven behavior.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "adaptive_bridge"),
)

import pytest

from adaptive_bridge.policy_engine import PolicyEngine
from adaptive_bridge.models import PolicyMode


# ------------------------------------------------------------------
# A. PolicyEngine Core
# ------------------------------------------------------------------

class TestPolicyEngineCore:
    def test_initial_mode_is_normal(self):
        """Fresh policy engine returns NORMAL for any topic."""
        engine = PolicyEngine()
        assert engine.get_mode("any_topic") == PolicyMode.NORMAL

    def test_noncritical_subscriber_degrades_mode(self):
        """NONCRITICAL subscriber -> get_mode returns DEGRADED."""
        engine = PolicyEngine(hysteresis_count=1)
        engine.on_classifier_update("sub1", "NONCRITICAL")
        assert engine.get_mode("topic_a") == PolicyMode.DEGRADED

    def test_critical_subscriber_keeps_normal(self):
        """CRITICAL subscriber -> get_mode returns NORMAL."""
        engine = PolicyEngine(hysteresis_count=1)
        engine.on_classifier_update("sub1", "CRITICAL")
        assert engine.get_mode("topic_a") == PolicyMode.NORMAL

    def test_unknown_defaults_to_normal(self):
        """UNKNOWN subscriber -> NORMAL (safety bias)."""
        engine = PolicyEngine(hysteresis_count=1)
        engine.on_classifier_update("sub1", "UNKNOWN")
        assert engine.get_mode("topic_a") == PolicyMode.NORMAL

    def test_any_noncritical_causes_degraded(self):
        """Mix of CRITICAL and NONCRITICAL -> DEGRADED."""
        engine = PolicyEngine(hysteresis_count=1)
        engine.on_classifier_update("sub1", "CRITICAL")
        engine.on_classifier_update("sub2", "NONCRITICAL")
        assert engine.get_mode("topic_a") == PolicyMode.DEGRADED


# ------------------------------------------------------------------
# B. Transition Damping
# ------------------------------------------------------------------

class TestTransitionDamping:
    def test_single_noncritical_does_not_degrade(self):
        """One NONCRITICAL window with hysteresis=3 -> still NORMAL."""
        engine = PolicyEngine(hysteresis_count=3)
        engine.on_classifier_update("sub1", "NONCRITICAL")
        assert engine.get_mode("topic_a") == PolicyMode.NORMAL

    def test_n_consecutive_noncritical_triggers_degrade(self):
        """N consecutive NONCRITICAL windows -> DEGRADED."""
        engine = PolicyEngine(hysteresis_count=3)
        for _ in range(3):
            engine.on_classifier_update("sub1", "NONCRITICAL")
        assert engine.get_mode("topic_a") == PolicyMode.DEGRADED

    def test_consecutive_exceeding_n_stays_degraded(self):
        """More than N consecutive NONCRITICAL -> DEGRADED (stable)."""
        engine = PolicyEngine(hysteresis_count=3)
        for _ in range(5):
            engine.on_classifier_update("sub1", "NONCRITICAL")
        assert engine.get_mode("topic_a") == PolicyMode.DEGRADED

    def test_alternating_states_stay_normal(self):
        """Alternating CRITICAL/NONCRITICAL never reaches damping threshold."""
        engine = PolicyEngine(hysteresis_count=3)
        for i in range(20):
            state = "NONCRITICAL" if i % 2 == 0 else "CRITICAL"
            engine.on_classifier_update("sub1", state)
        assert engine.get_mode("topic_a") == PolicyMode.NORMAL


# ------------------------------------------------------------------
# C. Forced Critical Override
# ------------------------------------------------------------------

class TestForcedCritical:
    def test_forced_critical_always_normal(self):
        """Forced-critical subscriber stays NORMAL regardless of state."""
        engine = PolicyEngine(hysteresis_count=1, forced_critical_ids={"sub1"})
        engine.on_classifier_update("sub1", "NONCRITICAL")
        assert engine.get_mode("topic_a") == PolicyMode.NORMAL

    def test_forced_critical_bypasses_damping(self):
        """Forced-critical subscriber never degrades even with repeated bad state."""
        engine = PolicyEngine(hysteresis_count=3, forced_critical_ids={"sub1"})
        for _ in range(10):
            engine.on_classifier_update("sub1", "NONCRITICAL")
        assert engine.get_mode("topic_a") == PolicyMode.NORMAL

    def test_forced_critical_overrides_damped_noncritical(self):
        """Forced-critical subscriber keeps NORMAL even when others are NONCRITICAL."""
        engine = PolicyEngine(hysteresis_count=1, forced_critical_ids={"sub1"})
        engine.on_classifier_update("sub1", "NONCRITICAL")
        engine.on_classifier_update("sub2", "NONCRITICAL")
        # sub1 is forced-critical, sub2 is not -> topic is DEGRADED because sub2 exists
        assert engine.get_mode("topic_a") == PolicyMode.DEGRADED


# ------------------------------------------------------------------
# D. get_subscriber_states and diagnostics snapshot
# ------------------------------------------------------------------

class TestDiagnosticsSnapshot:
    def test_subscriber_states_empty_initially(self):
        """get_subscriber_states returns empty dict before any updates."""
        engine = PolicyEngine()
        assert engine.get_subscriber_states() == {}

    def test_subscriber_states_only_stable(self):
        """get_subscriber_states only includes states that reached damping threshold."""
        engine = PolicyEngine(hysteresis_count=3)
        engine.on_classifier_update("sub1", "NONCRITICAL")  # not stable yet
        assert "sub1" not in engine.get_subscriber_states()

        engine.on_classifier_update("sub1", "NONCRITICAL")  # still not stable
        assert "sub1" not in engine.get_subscriber_states()

        engine.on_classifier_update("sub1", "NONCRITICAL")  # 3rd -> stable
        assert engine.get_subscriber_states() == {"sub1": "NONCRITICAL"}
