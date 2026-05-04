# src/tests/test_security_controls.py
"""
Unit tests for Step 13 — Security Controls for Control Plane Signals.

All tests are pure Python (no rclpy). Tests cover HMAC signing/verification,
replay protection, security mode enforcement, and diagnostics counters.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "adaptive_bridge"),
)

import copy
import pytest
import time

from adaptive_bridge.utils.security import (
    SecurityMode,
    ReplayProtector,
    SecurityManager,
)


# ------------------------------------------------------------------
# A. HMAC Sign/Verify
# ------------------------------------------------------------------

class TestHMAC:
    def test_sign_produces_hex_signature(self):
        mgr = SecurityManager(mode="enforce", hmac_secret="deadbeef" * 4)
        payload = {"subscriber_id": "test", "state": "CRITICAL"}
        sig = mgr.sign(payload)
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA-256 hex digest length

    def test_sign_attaches_fields(self):
        mgr = SecurityManager(mode="enforce", hmac_secret="deadbeef" * 4)
        payload = {"subscriber_id": "test", "state": "CRITICAL"}
        mgr.sign(payload)
        assert "_hmac" in payload
        assert "_nonce" in payload
        assert "_ts_ns" in payload

    def test_verify_valid_signature(self):
        mgr = SecurityManager(mode="enforce", hmac_secret="deadbeef" * 4)
        payload = {"subscriber_id": "test", "state": "CRITICAL"}
        mgr.sign(payload)
        valid, reason = mgr.verify(payload)
        assert valid is True
        assert reason == "ok"

    def test_verify_tampered_payload(self):
        mgr = SecurityManager(mode="enforce", hmac_secret="deadbeef" * 4)
        payload = {"subscriber_id": "test", "state": "CRITICAL"}
        mgr.sign(payload)
        payload["state"] = "NONCRITICAL"  # tamper
        valid, reason = mgr.verify(payload)
        assert valid is False
        assert reason == "invalid_signature"

    def test_off_mode_no_sign(self):
        mgr = SecurityManager(mode="off", hmac_secret="deadbeef" * 4)
        payload = {"subscriber_id": "test"}
        sig = mgr.sign(payload)
        assert sig is None
        assert "_hmac" not in payload

    def test_off_mode_verify_passes(self):
        mgr = SecurityManager(mode="off", hmac_secret="deadbeef" * 4)
        payload = {"subscriber_id": "test", "_hmac": "garbage", "_nonce": 1, "_ts_ns": 1}
        valid, reason = mgr.verify(payload)
        assert valid is True
        assert reason == "off"


# ------------------------------------------------------------------
# B. Replay Protection
# ------------------------------------------------------------------

class TestReplayProtection:
    def test_fresh_nonce_accepted(self):
        rp = ReplayProtector(window_ms=30000)
        now_ns = time.monotonic_ns()
        assert rp.check("sub1", now_ns, 1) is False

    def test_duplicate_nonce_rejected(self):
        rp = ReplayProtector(window_ms=30000)
        now_ns = time.monotonic_ns()
        rp.check("sub1", now_ns, 42)
        assert rp.check("sub1", now_ns, 42) is True

    def test_different_identity_independent(self):
        rp = ReplayProtector(window_ms=30000)
        now_ns = time.monotonic_ns()
        rp.check("sub1", now_ns, 42)
        assert rp.check("sub2", now_ns, 42) is False

    def test_stale_timestamp_rejected(self):
        rp = ReplayProtector(window_ms=100)  # 100ms window
        stale_ns = time.monotonic_ns() - 200_000_000  # 200ms ago
        assert rp.check("sub1", stale_ns, 1) is True

    def test_max_tracked_no_crash(self):
        rp = ReplayProtector(window_ms=30000, max_tracked=5)
        now_ns = time.monotonic_ns()
        for i in range(10):
            rp.check("sub1", now_ns, i)
        assert rp._seen["sub1"].__len__() <= 5


# ------------------------------------------------------------------
# C. Security Modes
# ------------------------------------------------------------------

class TestSecurityModes:
    def test_log_only_allows_violation(self):
        mgr = SecurityManager(mode="log_only", hmac_secret="deadbeef" * 4)
        now = time.monotonic_ns()
        payload = {"subscriber_id": "test", "state": "CRITICAL", "_hmac": "bad", "_nonce": 1, "_ts_ns": now}
        valid, reason = mgr.verify(payload)
        assert valid is False
        assert reason == "invalid_signature"

    def test_enforce_rejects_violation(self):
        mgr = SecurityManager(mode="enforce", hmac_secret="deadbeef" * 4)
        now = time.monotonic_ns()
        payload = {"subscriber_id": "test", "state": "CRITICAL", "_hmac": "bad", "_nonce": 1, "_ts_ns": now}
        valid, reason = mgr.verify(payload)
        assert valid is False
        assert reason == "invalid_signature"

    def test_missing_hmac_fields_rejected(self):
        mgr = SecurityManager(mode="enforce", hmac_secret="deadbeef" * 4)
        payload = {"subscriber_id": "test"}
        valid, reason = mgr.verify(payload)
        assert valid is False
        assert reason == "missing_hmac_fields"

    def test_security_mode_enum_values(self):
        assert SecurityMode.OFF.value == "off"
        assert SecurityMode.LOG_ONLY.value == "log_only"
        assert SecurityMode.ENFORCE.value == "enforce"


# ------------------------------------------------------------------
# D. Diagnostics Counters
# ------------------------------------------------------------------

class TestDiagnostics:
    def test_invalid_sig_counter_increments(self):
        mgr = SecurityManager(mode="enforce", hmac_secret="deadbeef" * 4)
        now = time.monotonic_ns()
        payload = {"subscriber_id": "test", "_hmac": "bad", "_nonce": 1, "_ts_ns": now}
        mgr.verify(payload)
        assert mgr.get_stats()["invalid_sig_count"] == 1

    def test_replay_counter_increments(self):
        mgr = SecurityManager(mode="enforce", hmac_secret="deadbeef" * 4)
        payload = {"subscriber_id": "test", "state": "CRITICAL"}
        mgr.sign(payload)
        # First verify succeeds
        valid1, reason1 = mgr.verify(dict(payload))
        assert valid1 is True
        assert reason1 == "ok"
        # Second verify of same payload is replay
        valid2, reason2 = mgr.verify(dict(payload))
        assert valid2 is False
        assert reason2 == "replay"
        assert mgr.get_stats()["replay_count"] == 1

    def test_get_stats_returns_both_fields(self):
        mgr = SecurityManager(mode="enforce", hmac_secret="deadbeef" * 4)
        stats = mgr.get_stats()
        assert "invalid_sig_count" in stats
        assert "replay_count" in stats


# ------------------------------------------------------------------
# E. Full Round-Trip
# ------------------------------------------------------------------

class TestRoundTrip:
    def test_sign_verify_round_trip(self):
        sender = SecurityManager(mode="enforce", hmac_secret="deadbeef" * 4)
        receiver = SecurityManager(mode="enforce", hmac_secret="deadbeef" * 4)
        payload = {"subscriber_id": "node1", "state": "CRITICAL"}
        sender.sign(payload)
        valid, reason = receiver.verify(payload)
        assert valid is True
        assert reason == "ok"

    def test_key_mismatch_fails(self):
        sender = SecurityManager(mode="enforce", hmac_secret="aaaa" * 8)
        receiver = SecurityManager(mode="enforce", hmac_secret="bbbb" * 8)
        payload = {"subscriber_id": "node1", "state": "CRITICAL"}
        sender.sign(payload)
        valid, reason = receiver.verify(payload)
        assert valid is False
        assert reason == "invalid_signature"

    def test_replay_detected_after_signing_twice(self):
        mgr = SecurityManager(mode="enforce", hmac_secret="deadbeef" * 4)
        p1 = {"subscriber_id": "node1", "state": "CRITICAL"}
        mgr.sign(p1)
        valid1, reason1 = mgr.verify(dict(p1))
        assert valid1 is True
        assert reason1 == "ok"
        valid2, reason2 = mgr.verify(dict(p1))
        assert valid2 is False
        assert reason2 == "replay"
