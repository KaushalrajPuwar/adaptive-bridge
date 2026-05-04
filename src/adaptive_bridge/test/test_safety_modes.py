# src/tests/test_safety_modes.py
"""
Unit tests for Step 12 — Safety Supervisor and Failure-Mode Runtime.

All tests are pure Python (no rclpy) — they instantiate SafetySupervisor
directly and verify state machine transitions, hysteresis, recovery
cooldowns, and terminal FAILURE behavior.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "adaptive_bridge"),
)

import pytest

from adaptive_bridge.safety_supervisor import SafetySupervisor
from adaptive_bridge.models import PolicyMode


# ------------------------------------------------------------------
# A. Initialization
# ------------------------------------------------------------------

class TestInitialization:
    def test_initial_mode_is_normal(self):
        sup = SafetySupervisor()
        assert sup.get_mode() == PolicyMode.NORMAL

    def test_initial_shutdown_not_requested(self):
        sup = SafetySupervisor()
        assert sup.is_shutdown_requested() is False

    def test_evaluate_returns_steady(self):
        sup = SafetySupervisor()
        mode, reason = sup.evaluate([0], 0, 0)
        assert mode == "NORMAL"
        assert reason == "steady"


# ------------------------------------------------------------------
# B. Degrade Triggers
# ------------------------------------------------------------------

class TestDegrade:
    def test_queue_pressure_degrades(self):
        sup = SafetySupervisor(degrade_windows=3, max_noncritical_queue=100)
        for _ in range(3):
            mode, _ = sup.evaluate([60], 0, 0)
        assert sup.get_mode() == PolicyMode.DEGRADED

    def test_single_pressure_window_no_degrade(self):
        sup = SafetySupervisor(degrade_windows=3, max_noncritical_queue=100)
        mode, _ = sup.evaluate([60], 0, 0)
        assert sup.get_mode() == PolicyMode.NORMAL

    def test_overflow_triggers_degrade(self):
        sup = SafetySupervisor(degrade_windows=3, max_noncritical_queue=100)
        for _ in range(3):
            mode, _ = sup.evaluate([0], 1, 0)
        assert sup.get_mode() == PolicyMode.DEGRADED

    def test_overflow_then_clean_stays_normal(self):
        sup = SafetySupervisor(degrade_windows=3, max_noncritical_queue=100)
        sup.evaluate([0], 1, 0)  # counter=1
        sup.evaluate([0], 1, 0)  # counter=2
        sup.evaluate([0], 0, 0)  # counter resets
        assert sup.get_mode() == PolicyMode.NORMAL


# ------------------------------------------------------------------
# C. Escalation to EMERGENCY
# ------------------------------------------------------------------

class TestEscalation:
    def test_overflow_in_degraded_escalates(self):
        sup = SafetySupervisor(degrade_windows=3, max_noncritical_queue=100)
        for _ in range(3):
            sup.evaluate([60], 0, 0)
        assert sup.get_mode() == PolicyMode.DEGRADED
        for _ in range(3):
            sup.evaluate([60], 1, 0)
        assert sup.get_mode() == PolicyMode.EMERGENCY

    def test_pressure_in_emergency_stays(self):
        sup = SafetySupervisor(degrade_windows=1, restore_windows=5,
                               restore_mid_pct=0.30, max_noncritical_queue=100)
        sup.evaluate([60], 0, 0)   # NORMAL -> DEGRADED
        sup.evaluate([60], 1, 0)   # DEGRADED -> EMERGENCY
        sup.evaluate([60], 0, 0)   # EMERGENCY stays (pressure)
        assert sup.get_mode() == PolicyMode.EMERGENCY


# ------------------------------------------------------------------
# D. Recovery
# ------------------------------------------------------------------

class TestRecovery:
    def test_emergency_to_degraded(self):
        sup = SafetySupervisor(degrade_windows=1, restore_windows=5,
                               restore_low_pct=0.10, restore_mid_pct=0.30,
                               max_noncritical_queue=100)
        sup.evaluate([60], 0, 0)   # -> DEGRADED
        sup.evaluate([60], 1, 0)   # -> EMERGENCY
        for _ in range(5):
            sup.evaluate([20], 0, 0)  # <30%, >=5 windows -> DEGRADED
        assert sup.get_mode() == PolicyMode.DEGRADED

    def test_degraded_to_normal(self):
        sup = SafetySupervisor(degrade_windows=3, restore_windows=5,
                               restore_low_pct=0.10,
                               max_noncritical_queue=100)
        for _ in range(3):
            sup.evaluate([60], 0, 0)   # -> DEGRADED
        for _ in range(5):
            sup.evaluate([5], 0, 0)   # <10%, >=5 windows -> NORMAL
        assert sup.get_mode() == PolicyMode.NORMAL

    def test_interrupted_recovery_resets(self):
        sup = SafetySupervisor(degrade_windows=1, restore_windows=5,
                               restore_low_pct=0.10, restore_mid_pct=0.30,
                               max_noncritical_queue=100)
        sup.evaluate([60], 0, 0)   # -> DEGRADED
        sup.evaluate([60], 1, 0)   # -> EMERGENCY
        for _ in range(3):
            sup.evaluate([20], 0, 0)  # 3 clean windows
        sup.evaluate([20], 1, 0)      # overflow resets restore counter
        for _ in range(5):
            sup.evaluate([20], 0, 0)  # 5 clean windows -> DEGRADED
        assert sup.get_mode() == PolicyMode.DEGRADED


# ------------------------------------------------------------------
# E. FAILURE Mode
# ------------------------------------------------------------------

class TestFailure:
    def test_component_errors_trigger_failure(self):
        sup = SafetySupervisor()
        sup.record_fault(10)
        sup.evaluate([0], 0, 0)
        assert sup.get_mode() == PolicyMode.FAILURE

    def test_failure_is_terminal(self):
        sup = SafetySupervisor()
        sup.record_fault(10)
        sup.evaluate([0], 0, 0)
        assert sup.get_mode() == PolicyMode.FAILURE
        sup.evaluate([0], 0, 0)
        assert sup.get_mode() == PolicyMode.FAILURE  # stays

    def test_failure_sets_shutdown_flag(self):
        sup = SafetySupervisor()
        sup.record_fault(10)
        sup.evaluate([0], 0, 0)
        assert sup.is_shutdown_requested() is True


# ------------------------------------------------------------------
# F. Edge Cases
# ------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_queue_list(self):
        sup = SafetySupervisor()
        mode, _ = sup.evaluate([], 0, 0)
        assert mode == "NORMAL"

    def test_negative(self):
        sup = SafetySupervisor(degrade_windows=3, max_noncritical_queue=100)
        for _ in range(3):
            sup.evaluate([95], 0, 0)   # >50% for 3 windows
        assert sup.get_mode() == PolicyMode.DEGRADED


# ------------------------------------------------------------------
# G. Integration with PolicyMode enum
# ------------------------------------------------------------------

class TestPolicyModeCompliance:
    def test_emergency_exists_in_enum(self):
        assert hasattr(PolicyMode, "EMERGENCY")
        assert PolicyMode.EMERGENCY.value == "EMERGENCY"
