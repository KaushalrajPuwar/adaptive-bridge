# src/tests/fixtures/fixtures.py
"""
Shared test helpers for Adaptive Bridge tests.

Used by stress, integration, and unit tests to avoid duplicating
common mock classes and sample data across files.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


def make_test_config(overrides: Optional[dict] = None) -> dict:
    """Build a minimal BridgeConfig-compatible dictionary.

    Provides sensible defaults for all required sections.  Callers can
    override any section by passing ``overrides``, e.g.::

        cfg = make_test_config({"classifier": {"hysteresis_count": 5}})

    The returned dict is ready for ``BridgeConfig.from_dict()``.
    """
    config = {
        "version": "2.0",
        "classifier": {
            "enabled": True,
            "evaluate_rate_hz": 1.0,
            "demote_loss_threshold": 0.10,
            "promote_loss_threshold": 0.03,
            "demote_rtt_ms": 120.0,
            "promote_rtt_ms": 60.0,
            "hysteresis_count": 3,
            "allow_unknown_state": True,
        },
        "probes": {
            "enabled": True,
            "rate_hz": 5.0,
            "rtt_threshold_ms": 100.0,
            "loss_threshold": 0.05,
            "jitter_threshold_ms": 25.0,
            "window_size": 50,
            "hysteresis_count": 3,
            "timeout_ms": 500,
            "request_topic": "/adaptive_bridge/probe_req",
            "response_topic": "/adaptive_bridge/probe_resp",
        },
        "topics": [
            {"id": "test_scan", "input_topic": "/scan",
             "critical_output": "/adaptive_bridge/critical/scan",
             "noncritical_output": "/adaptive_bridge/noncritical/scan",
             "message_type": "sensor_msgs/LaserScan"},
        ],
        "qos_profiles": {
            "reliable_depth10": {
                "reliability": "RELIABLE", "history": "KEEP_LAST",
                "depth": 10, "durability": "VOLATILE", "lifespan_ms": None,
            },
            "besteffort_depth5": {
                "reliability": "BEST_EFFORT", "history": "KEEP_LAST",
                "depth": 5, "durability": "VOLATILE", "lifespan_ms": None,
            },
        },
        "topic_qos_profiles": {
            "test_scan": {"critical": "reliable_depth10", "noncritical": "besteffort_depth5"},
        },
        "routing_policy": {
            "critical_always_forward": True,
            "noncritical_enabled": True,
            "noncritical_max_rate_hz": 10.0,
            "noncritical_drop_policy": "drop_oldest",
            "stale_threshold_ms": 500,
        },
        "safety": {
            "preserve_critical_path": True,
            "allow_noncritical_degrade": True,
            "max_noncritical_queue": 50,
            "overload_drop_noncritical_first": True,
        },
        "diagnostics": {
            "enabled": True,
            "publish_interval_s": 1.0,
            "topic": "/adaptive_bridge/diagnostics",
            "verbosity": "info",
        },
        "security": {
            "trust_mode": "off",
            "allow_legacy_node_name_overrides": False,
            "enable_probe_hmac": False,
            "max_probe_rate_hz": 20.0,
            "hmac_secret": "none",
            "replay_window_ms": 30000,
        },
    }
    if overrides:
        config = _deep_merge(config, overrides)
    return config


def sample_probe_stats() -> dict:
    """Return a realistic ProbeClient.get_stats() output dict."""
    return {
        "sender_id": "test_probe",
        "protocol_version": 1,
        "window_size": 10,
        "sent_total": 100,
        "recv_total": 95,
        "loss_rate": 0.05,
        "rtt": {"count": 10, "mean_ms": 15.3, "p95_ms": 25.1},
        "jitter": {"count": 9, "mean_ms": 3.2, "p95_ms": 7.8},
        "errors": {},
        "outstanding_count": 2,
        "last_seq": 200,
    }


def _deep_merge(base: dict, update: dict) -> dict:
    """Recursively merge *update* into a copy of *base*."""
    result = base.copy()
    for key, val in update.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result
