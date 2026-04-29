# src/tests/test_diagnostics_payload.py
"""
Unit tests for Step 7 — Diagnostics Contract and Observability Backbone.

All tests use DiagnosticsCollector (pure Python) and validate_payload()
from diagnostics_schema.py. No rclpy.init() is required.

Test coverage:
  1.  validate_payload — valid payload passes
  2.  validate_payload — missing top-level key detected
  3.  validate_payload — wrong type for ts_wall detected
  4.  validate_payload — missing topic-level key detected
  5.  validate_payload — missing counter sub-key detected
  6.  validate_payload — missing drop sub-key detected
  7.  DiagnosticsCollector.gather_payload — produces schema-valid payload
  8.  seq counter monotonically increases across gather_payload() calls
  9.  global mode reflected correctly in payload
  10. topic drop reasons reflected correctly in payload
  11. qos section present and contains expected role entries
  12. classifier snapshot reflected in payload
"""

from __future__ import annotations

import sys
import os

# Allow direct import from source tree without installing the package.
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "adaptive_bridge"),
)

import pytest

from adaptive_bridge.diagnostics import DiagnosticsCollector
from adaptive_bridge.diagnostics_schema import (
    SCHEMA_VERSION,
    validate_payload,
    assert_valid,
)


# ─────────────────────────────────────────────────────────────────────
# Helper: build a minimal valid payload dict
# ─────────────────────────────────────────────────────────────────────

def _make_valid_payload(topic_id: str = "scan_main") -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "ts_wall": 1_000_000.0,
        "seq": 1,
        "mode": "NORMAL",
        "topics": {
            topic_id: {
                "route": {
                    "topic_id": topic_id,
                    "input_topic": "/scan",
                    "critical_output": "/adaptive_bridge/critical/scan",
                    "noncritical_output": "/adaptive_bridge/noncritical/scan",
                },
                "counters": {
                    "total_received": 100,
                    "total_forwarded_critical": 100,
                    "total_forwarded_noncritical": 80,
                },
                "drops": {
                    "rate_limit": 10,
                    "queue_overflow": 5,
                    "stale": 2,
                    "disabled": 0,
                },
                "noncritical_mode": "NORMAL",
            }
        },
        "classifier": {},
        "qos": {
            topic_id: {
                "critical": {
                    "profile_name": "reliable_depth10",
                    "reason": "per-topic override",
                    "lifespan_ms": None,
                },
                "noncritical": {
                    "profile_name": "besteffort_depth5",
                    "reason": "per-topic override",
                    "lifespan_ms": 500,
                },
            }
        },
    }


# ─────────────────────────────────────────────────────────────────────
# Helper: minimal collector with one topic populated
# ─────────────────────────────────────────────────────────────────────

def _make_collector(topic_id: str = "scan_main") -> DiagnosticsCollector:
    c = DiagnosticsCollector()
    c.ingest_topic_route(topic_id, {
        "topic_id": topic_id,
        "input_topic": "/scan",
        "critical_output": "/adaptive_bridge/critical/scan",
        "noncritical_output": "/adaptive_bridge/noncritical/scan",
    })
    c.ingest_counters(topic_id, {
        "total_received": 50,
        "total_forwarded_critical": 50,
        "total_forwarded_noncritical": 40,
    })
    c.ingest_drop_stats(topic_id, {
        "rate_limit": 5,
        "queue_overflow": 2,
        "stale": 1,
        "disabled": 0,
    })
    c.ingest_noncritical_mode(topic_id, "NORMAL")
    c.ingest_qos_snapshot(topic_id, "critical", {
        "profile_name": "reliable_depth10",
        "reason": "per-topic override",
        "lifespan_ms": None,
    })
    c.ingest_qos_snapshot(topic_id, "noncritical", {
        "profile_name": "besteffort_depth5",
        "reason": "per-topic override",
        "lifespan_ms": 500,
    })
    return c


# ─────────────────────────────────────────────────────────────────────
# Test 1 — valid payload passes validation
# ─────────────────────────────────────────────────────────────────────

def test_validate_payload_valid():
    payload = _make_valid_payload()
    errors = validate_payload(payload)
    assert errors == [], f"Expected no errors, got: {errors}"


# ─────────────────────────────────────────────────────────────────────
# Test 2 — missing top-level key detected
# ─────────────────────────────────────────────────────────────────────

def test_validate_payload_missing_top_key():
    payload = _make_valid_payload()
    del payload["seq"]
    errors = validate_payload(payload)
    assert any("seq" in e for e in errors), (
        f"Expected error mentioning 'seq', got: {errors}"
    )


# ─────────────────────────────────────────────────────────────────────
# Test 3 — wrong type for ts_wall detected
# ─────────────────────────────────────────────────────────────────────

def test_validate_payload_wrong_type_ts_wall():
    payload = _make_valid_payload()
    payload["ts_wall"] = "not-a-float"
    errors = validate_payload(payload)
    assert any("ts_wall" in e for e in errors), (
        f"Expected error mentioning 'ts_wall', got: {errors}"
    )


# ─────────────────────────────────────────────────────────────────────
# Test 4 — missing topic-level key (drops) detected
# ─────────────────────────────────────────────────────────────────────

def test_validate_payload_missing_topic_key():
    payload = _make_valid_payload("scan_main")
    del payload["topics"]["scan_main"]["drops"]
    errors = validate_payload(payload)
    assert any("drops" in e for e in errors), (
        f"Expected error mentioning 'drops', got: {errors}"
    )


# ─────────────────────────────────────────────────────────────────────
# Test 5 — missing counter sub-key detected
# ─────────────────────────────────────────────────────────────────────

def test_validate_payload_missing_counter_key():
    payload = _make_valid_payload("scan_main")
    del payload["topics"]["scan_main"]["counters"]["total_received"]
    errors = validate_payload(payload)
    assert any("total_received" in e for e in errors), (
        f"Expected error mentioning 'total_received', got: {errors}"
    )


# ─────────────────────────────────────────────────────────────────────
# Test 6 — missing drop sub-key detected
# ─────────────────────────────────────────────────────────────────────

def test_validate_payload_missing_drop_key():
    payload = _make_valid_payload("scan_main")
    del payload["topics"]["scan_main"]["drops"]["stale"]
    errors = validate_payload(payload)
    assert any("stale" in e for e in errors), (
        f"Expected error mentioning 'stale', got: {errors}"
    )


# ─────────────────────────────────────────────────────────────────────
# Test 7 — collector produces schema-valid payload
# ─────────────────────────────────────────────────────────────────────

def test_diagnostics_collector_gather_payload_is_schema_valid():
    c = _make_collector()
    payload = c.gather_payload()
    errors = validate_payload(payload)
    assert errors == [], (
        f"Collector payload failed schema validation: {errors}\n"
        f"Payload was: {payload}"
    )


# ─────────────────────────────────────────────────────────────────────
# Test 8 — seq monotonically increases
# ─────────────────────────────────────────────────────────────────────

def test_seq_monotonically_increases():
    c = _make_collector()
    p1 = c.gather_payload()
    p2 = c.gather_payload()
    p3 = c.gather_payload()
    assert p1["seq"] < p2["seq"] < p3["seq"], (
        f"seq not monotonically increasing: {p1['seq']}, {p2['seq']}, {p3['seq']}"
    )


# ─────────────────────────────────────────────────────────────────────
# Test 9 — global mode reflected in payload
# ─────────────────────────────────────────────────────────────────────

def test_global_mode_reflected():
    c = _make_collector()
    c.set_global_mode("DEGRADED")
    payload = c.gather_payload()
    assert payload["mode"] == "DEGRADED", (
        f"Expected mode='DEGRADED', got '{payload['mode']}'"
    )


# ─────────────────────────────────────────────────────────────────────
# Test 10 — drop reasons reflected in payload
# ─────────────────────────────────────────────────────────────────────

def test_topic_drop_reasons_reflected():
    c = _make_collector()
    c.ingest_drop_stats("scan_main", {
        "rate_limit": 7,
        "queue_overflow": 3,
        "stale": 5,
        "disabled": 1,
    })
    payload = c.gather_payload()
    drops = payload["topics"]["scan_main"]["drops"]
    assert drops["stale"] == 5, f"Expected stale=5, got {drops['stale']}"
    assert drops["rate_limit"] == 7, f"Expected rate_limit=7, got {drops['rate_limit']}"
    assert drops["queue_overflow"] == 3, f"Expected queue_overflow=3, got {drops['queue_overflow']}"
    assert drops["disabled"] == 1, f"Expected disabled=1, got {drops['disabled']}"


# ─────────────────────────────────────────────────────────────────────
# Test 11 — qos section present with expected role entries
# ─────────────────────────────────────────────────────────────────────

def test_qos_section_present_and_correct():
    c = _make_collector()
    payload = c.gather_payload()
    assert "qos" in payload, "Expected 'qos' key in payload"
    assert "scan_main" in payload["qos"], (
        f"Expected 'scan_main' in payload['qos'], got: {list(payload['qos'].keys())}"
    )
    qos_entry = payload["qos"]["scan_main"]
    assert "critical" in qos_entry, (
        f"Expected 'critical' in qos entry, got: {list(qos_entry.keys())}"
    )
    assert "noncritical" in qos_entry, (
        f"Expected 'noncritical' in qos entry, got: {list(qos_entry.keys())}"
    )
    assert qos_entry["critical"]["profile_name"] == "reliable_depth10", (
        f"Unexpected critical profile: {qos_entry['critical']}"
    )


# ─────────────────────────────────────────────────────────────────────
# Test 12 — classifier snapshot reflected in payload
# ─────────────────────────────────────────────────────────────────────

def test_classifier_section_reflected():
    c = _make_collector()
    classifier_data = {
        "remote_node": {
            "state": "NONCRITICAL",
            "reason": "high_rtt",
            "confidence": 0.9,
        }
    }
    c.ingest_classifier_snapshot(classifier_data)
    payload = c.gather_payload()
    assert "classifier" in payload, "Expected 'classifier' key in payload"
    assert payload["classifier"] == classifier_data, (
        f"Classifier snapshot mismatch: {payload['classifier']}"
    )


# ─────────────────────────────────────────────────────────────────────
# Bonus: assert_valid raises on invalid payload
# ─────────────────────────────────────────────────────────────────────

def test_assert_valid_raises_on_invalid():
    payload = _make_valid_payload()
    del payload["mode"]
    with pytest.raises(ValueError, match="mode"):
        assert_valid(payload)


# ─────────────────────────────────────────────────────────────────────
# Bonus: validate_payload returns error for non-dict input
# ─────────────────────────────────────────────────────────────────────

def test_validate_payload_non_dict_input():
    errors = validate_payload("not-a-dict")
    assert len(errors) == 1 and "dict" in errors[0], (
        f"Expected single dict-type error, got: {errors}"
    )


# ─────────────────────────────────────────────────────────────────────
# Bonus: schema_version in payload matches module constant
# ─────────────────────────────────────────────────────────────────────

def test_schema_version_in_payload():
    c = _make_collector()
    payload = c.gather_payload()
    assert payload["schema_version"] == SCHEMA_VERSION, (
        f"Expected schema_version='{SCHEMA_VERSION}', got '{payload['schema_version']}'"
    )
