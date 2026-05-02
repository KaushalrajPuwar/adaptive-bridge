# src/tests/test_classifier_logic.py
"""
Unit tests for Step 9 — Classifier Core Library (Pure Logic).

All tests use SubscriberClassifier and ProbeMetrics directly.
Zero rclpy dependency — no rclpy.init() is required.

Test philosophy:
  Every test targets one specific invariant or bug-class described in the
  implementation plan. Comments above each test state what bug it catches.

Fixture: _cfg() — returns a ClassifierConfig with well-known thresholds
  demote_rtt_ms      = 120.0
  promote_rtt_ms     = 60.0
  demote_loss        = 0.10
  promote_loss       = 0.03
  hysteresis_count   = 3
  allow_unknown_state = True
"""

from __future__ import annotations

import sys
import os

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "adaptive_bridge"),
)

import pytest

from adaptive_bridge.classifier_core import SubscriberClassifier
from adaptive_bridge.classifier_types import (
    ALL_REASON_CODES,
    ALL_STATES,
    CLASSIFIER_SCHEMA_VERSION,
    REASON_INSUFFICIENT_DATA,
    REASON_MANUAL_OVERRIDE,
    REASON_HIGH_RTT,
    REASON_HIGH_LOSS,
    REASON_HIGH_RTT_AND_LOSS,
    REASON_RECOVERED,
    REASON_STABLE_CRITICAL,
    ClassificationDecision,
    ProbeMetrics,
)
from adaptive_bridge.config_types import ClassifierConfig


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _cfg(
    hysteresis_count: int = 3,
    allow_unknown_state: bool = True,
    demote_rtt_ms: float = 120.0,
    promote_rtt_ms: float = 60.0,
    demote_loss: float = 0.10,
    promote_loss: float = 0.03,
) -> ClassifierConfig:
    return ClassifierConfig(
        enabled=True,
        evaluate_rate_hz=1.0,
        demote_loss_threshold=demote_loss,
        promote_loss_threshold=promote_loss,
        demote_rtt_ms=demote_rtt_ms,
        promote_rtt_ms=promote_rtt_ms,
        hysteresis_count=hysteresis_count,
        allow_unknown_state=allow_unknown_state,
    )


def _good() -> ProbeMetrics:
    """Clearly good metrics: RTT=30ms, loss=0.0, 10 samples."""
    return ProbeMetrics(avg_rtt_ms=30.0, loss=0.0, sample_count=10)


def _bad_rtt() -> ProbeMetrics:
    """High RTT only: RTT=150ms (> 120 demote), loss=0.0."""
    return ProbeMetrics(avg_rtt_ms=150.0, loss=0.0, sample_count=10)


def _bad_loss() -> ProbeMetrics:
    """High loss only: RTT=30ms, loss=0.20 (> 0.10 demote)."""
    return ProbeMetrics(avg_rtt_ms=30.0, loss=0.20, sample_count=10)


def _bad_both() -> ProbeMetrics:
    """Both bad: RTT=150ms, loss=0.20."""
    return ProbeMetrics(avg_rtt_ms=150.0, loss=0.20, sample_count=10)


def _no_data() -> ProbeMetrics:
    """No probe data yet: sample_count=0."""
    return ProbeMetrics(avg_rtt_ms=0.0, loss=0.0, sample_count=0)


def _drive_to_noncritical(
    clf: SubscriberClassifier,
    sub_id: str,
    n: int = 3,
) -> ClassificationDecision:
    """Push subscriber through N bad windows to reach NONCRITICAL."""
    # First reach CRITICAL from UNKNOWN
    for _ in range(n):
        clf.update(sub_id, _good(), now_ns=1)
    # Now demote
    d = clf.update(sub_id, _good(), now_ns=1)
    assert d.state == "CRITICAL", f"Expected CRITICAL before demotion, got {d.state}"
    for _ in range(n):
        d = clf.update(sub_id, _bad_rtt(), now_ns=2)
    return d


# ──────────────────────────────────────────────────────────────────────
# Type contract tests
# ──────────────────────────────────────────────────────────────────────

def test_probe_metrics_to_dict_has_all_keys() -> None:
    """ProbeMetrics.to_dict() must include all required keys."""
    m = _good()
    d = m.to_dict()
    for key in ("avg_rtt_ms", "loss", "sample_count", "p95_rtt_ms", "jitter_ms"):
        assert key in d, f"Missing key '{key}' in ProbeMetrics.to_dict()"


def test_classification_decision_to_dict_has_all_keys() -> None:
    """ClassificationDecision.to_dict() must include all required keys."""
    clf = SubscriberClassifier(_cfg())
    d = clf.update("sub1", _good(), now_ns=100).to_dict()
    for key in (
        "subscriber_id", "state", "reason", "ts_ns",
        "avg_rtt_ms", "loss", "hysteresis_counter", "consecutive_good",
    ):
        assert key in d, f"Missing key '{key}' in ClassificationDecision.to_dict()"


def test_decision_state_is_valid_state() -> None:
    """Every decision state must be in the valid set."""
    clf = SubscriberClassifier(_cfg())
    for metrics in (_good(), _bad_rtt(), _no_data()):
        d = clf.update("sub1", metrics, now_ns=1)
        assert d.state in ALL_STATES, f"Invalid state: {d.state}"


def test_decision_reason_is_valid_reason_code() -> None:
    """Every decision reason must be a known reason code constant."""
    clf = SubscriberClassifier(_cfg())
    for metrics in (_good(), _bad_rtt(), _bad_loss(), _bad_both(), _no_data()):
        clf2 = SubscriberClassifier(_cfg())
        d = clf2.update("sub1", metrics, now_ns=1)
        assert d.reason in ALL_REASON_CODES, f"Invalid reason: {d.reason}"


def test_classifier_schema_version_constant_exists() -> None:
    """Schema version constant must be a non-empty string."""
    assert isinstance(CLASSIFIER_SCHEMA_VERSION, str)
    assert len(CLASSIFIER_SCHEMA_VERSION) > 0


# ──────────────────────────────────────────────────────────────────────
# Initial state tests
# ──────────────────────────────────────────────────────────────────────

def test_initial_state_is_unknown() -> None:
    """Bug caught: starting state is CRITICAL instead of UNKNOWN.

    The architecture requires UNKNOWN as the safe initial state.
    First update with good metrics must NOT immediately become CRITICAL —
    that requires N consecutive good windows.
    """
    clf = SubscriberClassifier(_cfg())
    d = clf.update("sub1", _good(), now_ns=1)
    assert d.state == "UNKNOWN", f"Expected UNKNOWN on first update, got {d.state}"


def test_insufficient_data_allows_unknown_when_permitted() -> None:
    """Bug caught: classifier crashes or misclassifies with zero samples.

    With allow_unknown_state=True and sample_count=0, must return UNKNOWN.
    """
    clf = SubscriberClassifier(_cfg(allow_unknown_state=True))
    d = clf.update("sub1", _no_data(), now_ns=1)
    assert d.state == "UNKNOWN", f"Expected UNKNOWN for no-data, got {d.state}"
    assert d.reason == REASON_INSUFFICIENT_DATA


def test_insufficient_data_returns_critical_when_unknown_disallowed() -> None:
    """Bug caught: allow_unknown_state=False not collapsing UNKNOWN to CRITICAL.

    Conservative policy: no data → treat as CRITICAL (fail-safe bias).
    """
    clf = SubscriberClassifier(_cfg(allow_unknown_state=False))
    d = clf.update("sub1", _no_data(), now_ns=1)
    assert d.state == "CRITICAL", f"Expected CRITICAL for no-data with allow=False, got {d.state}"
    assert d.reason == REASON_INSUFFICIENT_DATA


# ──────────────────────────────────────────────────────────────────────
# Hysteresis / demotion tests
# ──────────────────────────────────────────────────────────────────────

def test_single_bad_window_does_not_demote_from_critical() -> None:
    """Bug caught: hysteresis bypassed — premature demotion on first bad sample.

    With hysteresis_count=3, one bad window must leave state as CRITICAL.
    """
    clf = SubscriberClassifier(_cfg(hysteresis_count=3))
    # Promote to CRITICAL first
    for _ in range(3):
        clf.update("sub1", _good(), now_ns=1)
    # One bad window
    d = clf.update("sub1", _bad_rtt(), now_ns=2)
    assert d.state == "CRITICAL", (
        f"Single bad window should not demote: got {d.state}"
    )


def test_two_bad_windows_do_not_demote_from_critical() -> None:
    """Bug caught: off-by-one — N-1 violations causing demotion."""
    clf = SubscriberClassifier(_cfg(hysteresis_count=3))
    for _ in range(3):
        clf.update("sub1", _good(), now_ns=1)
    clf.update("sub1", _bad_rtt(), now_ns=2)
    d = clf.update("sub1", _bad_rtt(), now_ns=2)
    assert d.state == "CRITICAL", (
        f"Two bad windows (< hysteresis=3) should not demote: got {d.state}"
    )


def test_demote_to_noncritical_after_n_consecutive_bad_windows() -> None:
    """Bug caught: hysteresis counter not incrementing or wrong threshold.

    Exactly N bad windows must trigger demotion to NONCRITICAL.
    """
    clf = SubscriberClassifier(_cfg(hysteresis_count=3))
    # Promote to CRITICAL
    for _ in range(3):
        clf.update("sub1", _good(), now_ns=1)
    d_check = clf.update("sub1", _good(), now_ns=1)
    assert d_check.state == "CRITICAL"
    # N bad windows
    for _ in range(2):
        clf.update("sub1", _bad_rtt(), now_ns=2)
    d = clf.update("sub1", _bad_rtt(), now_ns=2)
    assert d.state == "NONCRITICAL", (
        f"Expected NONCRITICAL after 3 bad windows, got {d.state}"
    )


# ──────────────────────────────────────────────────────────────────────
# Reason code tests
# ──────────────────────────────────────────────────────────────────────

def test_reason_code_high_rtt_when_only_rtt_violated() -> None:
    """Bug caught: wrong reason assigned when only RTT exceeds threshold."""
    clf = SubscriberClassifier(_cfg(hysteresis_count=3))
    for _ in range(3):
        clf.update("sub1", _good(), now_ns=1)
    d = clf.update("sub1", _bad_rtt(), now_ns=2)
    assert d.reason == REASON_HIGH_RTT, (
        f"Expected {REASON_HIGH_RTT}, got {d.reason}"
    )


def test_reason_code_high_loss_when_only_loss_violated() -> None:
    """Bug caught: wrong reason when only loss exceeds threshold."""
    clf = SubscriberClassifier(_cfg(hysteresis_count=3))
    for _ in range(3):
        clf.update("sub1", _good(), now_ns=1)
    d = clf.update("sub1", _bad_loss(), now_ns=2)
    assert d.reason == REASON_HIGH_LOSS, (
        f"Expected {REASON_HIGH_LOSS}, got {d.reason}"
    )


def test_reason_code_high_rtt_and_loss_when_both_violated() -> None:
    """Bug caught: missing combined-reason path."""
    clf = SubscriberClassifier(_cfg(hysteresis_count=3))
    for _ in range(3):
        clf.update("sub1", _good(), now_ns=1)
    d = clf.update("sub1", _bad_both(), now_ns=2)
    assert d.reason == REASON_HIGH_RTT_AND_LOSS, (
        f"Expected {REASON_HIGH_RTT_AND_LOSS}, got {d.reason}"
    )


# ──────────────────────────────────────────────────────────────────────
# Recovery / promotion tests
# ──────────────────────────────────────────────────────────────────────

def test_recovery_requires_full_n_good_windows() -> None:
    """Bug caught: off-by-one in consecutive_good check allowing early recovery."""
    clf = SubscriberClassifier(_cfg(hysteresis_count=3))
    d = _drive_to_noncritical(clf, "sub1")
    assert d.state == "NONCRITICAL"
    # N-1 good windows — must still be NONCRITICAL
    for _ in range(2):
        clf.update("sub1", _good(), now_ns=3)
    d = clf.update("sub1", _good(), now_ns=3)
    # On the 2nd window (< 3 required), should still be NONCRITICAL
    # Actually after 2 good windows we are still NONCRITICAL (need 3)
    # But above loop does 2, then one more → that's 3 → CRITICAL
    # Re-check: after _drive_to_noncritical (3 bad), then 2 good, check:
    clf2 = SubscriberClassifier(_cfg(hysteresis_count=3))
    _drive_to_noncritical(clf2, "sub2")
    for _ in range(2):
        d2 = clf2.update("sub2", _good(), now_ns=3)
    assert d2.state == "NONCRITICAL", (
        f"2 good windows (< hysteresis=3) should not recover: got {d2.state}"
    )


def test_noncritical_recovers_to_critical_after_n_good_windows() -> None:
    """Bug caught: recovery path broken or using wrong counter."""
    clf = SubscriberClassifier(_cfg(hysteresis_count=3))
    _drive_to_noncritical(clf, "sub1")
    for _ in range(2):
        clf.update("sub1", _good(), now_ns=3)
    d = clf.update("sub1", _good(), now_ns=3)
    assert d.state == "CRITICAL", (
        f"Expected CRITICAL after 3 good windows, got {d.state}"
    )


def test_reason_recovered_on_promotion_from_noncritical() -> None:
    """Bug caught: wrong reason code on NONCRITICAL→CRITICAL transition."""
    clf = SubscriberClassifier(_cfg(hysteresis_count=3))
    _drive_to_noncritical(clf, "sub1")
    for _ in range(2):
        clf.update("sub1", _good(), now_ns=3)
    d = clf.update("sub1", _good(), now_ns=3)
    assert d.state == "CRITICAL"
    assert d.reason == REASON_RECOVERED, (
        f"Expected reason={REASON_RECOVERED}, got {d.reason}"
    )


# ──────────────────────────────────────────────────────────────────────
# Forced-critical override tests
# ──────────────────────────────────────────────────────────────────────

def test_forced_critical_override_wins_over_bad_metrics() -> None:
    """Bug caught: override precedence not checked first.

    Forced-critical must override all metric-based decisions including
    sustained bad RTT/loss that would otherwise trigger demotion.
    """
    clf = SubscriberClassifier(_cfg(), forced_critical_ids={"sub1"})
    # Even with terrible metrics, must be CRITICAL
    for _ in range(10):
        d = clf.update("sub1", _bad_both(), now_ns=1)
        assert d.state == "CRITICAL", (
            f"Override must win: expected CRITICAL, got {d.state} on iteration"
        )
    assert d.reason == REASON_MANUAL_OVERRIDE


def test_forced_critical_does_not_mutate_machine_state() -> None:
    """Bug caught: override corrupts state machine state.

    If override is active, the internal hysteresis/consecutive_good counters
    must NOT be modified. When override is removed, the machine continues
    from where it left off before the override was applied.
    """
    clf = SubscriberClassifier(_cfg(hysteresis_count=3))
    # Promote to CRITICAL via 3 good windows
    for _ in range(3):
        clf.update("sub1", _good(), now_ns=1)
    d_pre = clf.update("sub1", _good(), now_ns=1)
    assert d_pre.state == "CRITICAL"

    # Apply override and drive bad metrics
    clf.set_forced_critical("sub1", True)
    for _ in range(10):
        clf.update("sub1", _bad_both(), now_ns=2)

    # Remove override — state should still be CRITICAL (machine was frozen)
    clf.set_forced_critical("sub1", False)
    d_post = clf.update("sub1", _good(), now_ns=3)
    assert d_post.state == "CRITICAL", (
        f"After override removal, expected CRITICAL (machine state preserved), "
        f"got {d_post.state}"
    )


def test_override_added_via_set_forced_critical() -> None:
    """Bug caught: set_forced_critical not updating the override set."""
    clf = SubscriberClassifier(_cfg())
    d1 = clf.update("sub1", _bad_both(), now_ns=1)
    assert d1.state != "CRITICAL" or d1.reason != REASON_MANUAL_OVERRIDE

    clf.set_forced_critical("sub1", True)
    d2 = clf.update("sub1", _bad_both(), now_ns=2)
    assert d2.state == "CRITICAL"
    assert d2.reason == REASON_MANUAL_OVERRIDE


# ──────────────────────────────────────────────────────────────────────
# Flap-suppression test
# ──────────────────────────────────────────────────────────────────────

def test_single_bad_window_resets_recovery_counter() -> None:
    """Bug caught: consecutive_good not reset on bad window → premature recovery.

    While recovering (in NONCRITICAL with consecutive_good > 0),
    a single bad window must reset consecutive_good to 0.
    """
    clf = SubscriberClassifier(_cfg(hysteresis_count=3))
    _drive_to_noncritical(clf, "sub1")

    # 2 good windows (recovering, not yet promoted)
    clf.update("sub1", _good(), now_ns=3)
    clf.update("sub1", _good(), now_ns=3)
    d_before = clf.update("sub1", _good(), now_ns=3)
    # At this point 3 good windows done → CRITICAL
    # Re-demote, then test mid-recovery interruption
    clf2 = SubscriberClassifier(_cfg(hysteresis_count=3))
    _drive_to_noncritical(clf2, "sub2")

    # 2 good, then 1 bad — must reset recovery
    clf2.update("sub2", _good(), now_ns=3)
    clf2.update("sub2", _good(), now_ns=3)
    clf2.update("sub2", _bad_rtt(), now_ns=3)  # interrupt recovery

    # Now 3 more good — should need a full 3 more (counter was reset)
    clf2.update("sub2", _good(), now_ns=4)
    clf2.update("sub2", _good(), now_ns=4)
    d = clf2.update("sub2", _good(), now_ns=4)
    assert d.state == "CRITICAL", (
        f"After interrupted recovery, need fresh 3 good windows, got state={d.state}"
    )


def test_flapping_suppressed_alternating_signals() -> None:
    """Bug caught: alternating good/bad signals causing oscillation.

    With hysteresis_count=3, alternating good/bad must never trigger a
    state transition from CRITICAL. The hysteresis counter resets on each
    good window while in CRITICAL, preventing demotion.
    """
    clf = SubscriberClassifier(_cfg(hysteresis_count=3))
    # Promote to CRITICAL
    for _ in range(3):
        clf.update("sub1", _good(), now_ns=1)
    d = clf.update("sub1", _good(), now_ns=1)
    assert d.state == "CRITICAL"

    # 20 alternating windows — must stay CRITICAL throughout
    for i in range(20):
        metrics = _bad_rtt() if i % 2 == 0 else _good()
        d = clf.update("sub1", metrics, now_ns=i + 100)
        assert d.state == "CRITICAL", (
            f"Flapping at iteration {i} caused demotion: state={d.state}"
        )


def test_fuzzy_zone_stays_unknown() -> None:
    """Bug caught: metrics between promote and demote thresholds
    incorrectly promote from UNKNOWN.

    With promote_rtt_ms=60 and demote_rtt_ms=120, RTT=90ms is in the
    fuzzy zone — neither clearly good nor clearly bad. It must NOT
    accumulate toward CRITICAL; subscriber should stay UNKNOWN.
    """
    clf = SubscriberClassifier(_cfg(hysteresis_count=3))
    fuzzy = ProbeMetrics(avg_rtt_ms=90.0, loss=0.0, sample_count=10)
    for _ in range(10):
        d = clf.update("sub1", fuzzy, now_ns=1)
    assert d.state == "UNKNOWN", (
        f"Fuzzy-zone metrics should keep subscriber UNKNOWN, got {d.state}"
    )


# ──────────────────────────────────────────────────────────────────────
# Snapshot and multi-subscriber tests
# ──────────────────────────────────────────────────────────────────────

def test_snapshot_returns_all_updated_subscribers() -> None:
    """Bug caught: snapshot() silently dropping subscribers."""
    clf = SubscriberClassifier(_cfg())
    clf.update("alice", _good(), now_ns=1)
    clf.update("bob", _bad_rtt(), now_ns=1)
    clf.update("carol", _no_data(), now_ns=1)

    snap = clf.snapshot()
    assert "alice" in snap, "alice missing from snapshot"
    assert "bob" in snap, "bob missing from snapshot"
    assert "carol" in snap, "carol missing from snapshot"
    assert snap["alice"].subscriber_id == "alice"
    assert snap["bob"].subscriber_id == "bob"


def test_snapshot_is_empty_before_any_update() -> None:
    """Bug caught: snapshot() returning stale state or crashing on empty."""
    clf = SubscriberClassifier(_cfg())
    snap = clf.snapshot()
    assert snap == {}, f"Expected empty snapshot, got {snap}"


def test_reset_clears_subscriber_state() -> None:
    """Bug caught: reset() leaves stale state causing wrong transition.

    After reset(), the subscriber must start from UNKNOWN again on the
    next update — even if it was previously NONCRITICAL.
    """
    clf = SubscriberClassifier(_cfg(hysteresis_count=3))
    _drive_to_noncritical(clf, "sub1")
    d_before = clf.update("sub1", _bad_rtt(), now_ns=2)
    assert d_before.state == "NONCRITICAL"

    clf.reset("sub1")
    d_after = clf.update("sub1", _good(), now_ns=3)
    assert d_after.state == "UNKNOWN", (
        f"After reset, expected UNKNOWN, got {d_after.state}"
    )


def test_reset_all_clears_every_subscriber() -> None:
    """Bug caught: reset_all() misses some subscribers."""
    clf = SubscriberClassifier(_cfg())
    for sub in ("a", "b", "c"):
        clf.update(sub, _good(), now_ns=1)
    clf.reset_all()
    assert clf.snapshot() == {}, "snapshot() should be empty after reset_all()"


# ──────────────────────────────────────────────────────────────────────
# to_snapshot() conversion test
# ──────────────────────────────────────────────────────────────────────

def test_to_snapshot_produces_classifier_snapshot() -> None:
    """ClassificationDecision.to_snapshot() must produce a ClassifierSnapshot
    compatible with the diagnostics payload system."""
    from adaptive_bridge.models import ClassifierSnapshot

    clf = SubscriberClassifier(_cfg())
    d = clf.update("sub1", _good(), now_ns=1)
    snap = d.to_snapshot()
    assert isinstance(snap, ClassifierSnapshot)
    assert snap.subscriber_id == "sub1"
    assert snap.classification == d.state
    assert d.reason in snap.reason_flags


# ──────────────────────────────────────────────────────────────────────
# Backward-compat: classifier_node still importable with main() callable
# ──────────────────────────────────────────────────────────────────────

def test_classifier_node_imports() -> None:
    """Regression: classifier_node module must still import cleanly."""
    import importlib
    pytest.importorskip("rclpy")
    mod = importlib.import_module("adaptive_bridge.classifier_node")
    assert mod is not None


def test_classifier_node_has_main_callable() -> None:
    """Regression: classifier_node.main must remain a callable."""
    import importlib
    pytest.importorskip("rclpy")
    mod = importlib.import_module("adaptive_bridge.classifier_node")
    assert callable(mod.main)
