from pathlib import Path

import pytest
import yaml

from adaptive_bridge.config_manager import ConfigManager
from adaptive_bridge.config_types import ProbeConfig, TopicConfig
from adaptive_bridge.topic_registry import TopicRegistry


def _write_yaml(tmp_path: Path, name: str, payload: dict) -> str:
    file_path = tmp_path / name
    file_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return str(file_path)


def test_config_manager_default_schema_loads_typed_objects() -> None:
    cfg = ConfigManager()
    topics = cfg.get_topics()
    assert len(topics) >= 1
    assert isinstance(topics[0], TopicConfig)
    assert isinstance(cfg.get_probe_config(), ProbeConfig)
    qos = cfg.get_qos_policy("critical", topics[0].id)
    assert qos.reliability == "RELIABLE"


def test_missing_required_section_fails(tmp_path: Path) -> None:
    bad = {
        "topics": [{"id": "scan_main", "input_topic": "/scan", "critical_output": "/c/scan", "noncritical_output": "/n/scan"}],
        "qos_profiles": {},
    }
    cfg_file = _write_yaml(tmp_path, "missing_sections.yaml", bad)
    with pytest.raises(ValueError, match="topic_qos_profiles"):
        ConfigManager(cfg_file)


def test_unknown_qos_profile_fails(tmp_path: Path) -> None:
    bad = {
        "topics": [{"id": "scan_main", "input_topic": "/scan", "critical_output": "/c/scan", "noncritical_output": "/n/scan"}],
        "qos_profiles": {
            "reliable_depth10": {"reliability": "RELIABLE", "history": "KEEP_LAST", "depth": 10, "durability": "VOLATILE"}
        },
        "topic_qos_profiles": {"scan_main": {"critical": "missing_profile", "noncritical": "reliable_depth10"}},
        "classifier": {
            "enabled": True, "evaluate_rate_hz": 1.0, "demote_loss_threshold": 0.1, "promote_loss_threshold": 0.03,
            "demote_rtt_ms": 100.0, "promote_rtt_ms": 50.0, "hysteresis_count": 3, "allow_unknown_state": True
        },
        "probes": {
            "enabled": True, "rate_hz": 5.0, "rtt_threshold_ms": 100.0, "loss_threshold": 0.05,
            "jitter_threshold_ms": 20.0, "window_size": 10, "hysteresis_count": 3,
            "request_topic": "/adaptive_bridge/probe_req", "response_topic": "/adaptive_bridge/probe_resp"
        },
        "routing_policy": {
            "critical_always_forward": True, "noncritical_enabled": True, "noncritical_max_rate_hz": 5.0,
            "noncritical_drop_policy": "drop_oldest", "stale_threshold_ms": 500
        },
        "safety": {
            "preserve_critical_path": True, "allow_noncritical_degrade": True, "max_noncritical_queue": 10,
            "overload_drop_noncritical_first": True
        },
        "security": {
            "trust_mode": "default_deny", "allow_legacy_node_name_overrides": True, "enable_probe_hmac": False,
            "max_probe_rate_hz": 10.0
        },
        "diagnostics": {"enabled": True, "publish_interval_s": 1.0, "topic": "/adaptive_bridge/diagnostics", "verbosity": "info"},
        "overrides": {},
    }
    cfg_file = _write_yaml(tmp_path, "bad_qos_ref.yaml", bad)
    with pytest.raises(ValueError, match="unknown QoS profile"):
        ConfigManager(cfg_file)


def test_invalid_threshold_fails(tmp_path: Path) -> None:
    bad = {
        "topics": [{"id": "scan_main", "input_topic": "/scan", "critical_output": "/c/scan", "noncritical_output": "/n/scan"}],
        "qos_profiles": {
            "reliable_depth10": {"reliability": "RELIABLE", "history": "KEEP_LAST", "depth": 10, "durability": "VOLATILE"}
        },
        "topic_qos_profiles": {"scan_main": {"critical": "reliable_depth10", "noncritical": "reliable_depth10"}},
        "classifier": {
            "enabled": True, "evaluate_rate_hz": 1.0, "demote_loss_threshold": 1.5, "promote_loss_threshold": 0.03,
            "demote_rtt_ms": 100.0, "promote_rtt_ms": 50.0, "hysteresis_count": 3, "allow_unknown_state": True
        },
        "probes": {
            "enabled": True, "rate_hz": 5.0, "rtt_threshold_ms": 100.0, "loss_threshold": 0.05,
            "jitter_threshold_ms": 20.0, "window_size": 10, "hysteresis_count": 3,
            "request_topic": "/adaptive_bridge/probe_req", "response_topic": "/adaptive_bridge/probe_resp"
        },
        "routing_policy": {
            "critical_always_forward": True, "noncritical_enabled": True, "noncritical_max_rate_hz": 5.0,
            "noncritical_drop_policy": "drop_oldest", "stale_threshold_ms": 500
        },
        "safety": {
            "preserve_critical_path": True, "allow_noncritical_degrade": True, "max_noncritical_queue": 10,
            "overload_drop_noncritical_first": True
        },
        "security": {
            "trust_mode": "default_deny", "allow_legacy_node_name_overrides": True, "enable_probe_hmac": False,
            "max_probe_rate_hz": 10.0
        },
        "diagnostics": {"enabled": True, "publish_interval_s": 1.0, "topic": "/adaptive_bridge/diagnostics", "verbosity": "info"},
        "overrides": {},
    }
    cfg_file = _write_yaml(tmp_path, "bad_threshold.yaml", bad)
    with pytest.raises(ValueError, match="demote_loss_threshold"):
        ConfigManager(cfg_file)


def test_duplicate_topic_ids_fail(tmp_path: Path) -> None:
    cfg = {
        "topics": [
            {"id": "dup", "input_topic": "/scan", "critical_output": "/c/scan", "noncritical_output": "/n/scan"},
            {"id": "dup", "input_topic": "/scan2", "critical_output": "/c/scan2", "noncritical_output": "/n/scan2"},
        ],
        "qos_profiles": {
            "reliable_depth10": {"reliability": "RELIABLE", "history": "KEEP_LAST", "depth": 10, "durability": "VOLATILE"}
        },
        "topic_qos_profiles": {"dup": {"critical": "reliable_depth10", "noncritical": "reliable_depth10"}},
        "classifier": {
            "enabled": True, "evaluate_rate_hz": 1.0, "demote_loss_threshold": 0.1, "promote_loss_threshold": 0.03,
            "demote_rtt_ms": 100.0, "promote_rtt_ms": 50.0, "hysteresis_count": 3, "allow_unknown_state": True
        },
        "probes": {
            "enabled": True, "rate_hz": 5.0, "rtt_threshold_ms": 100.0, "loss_threshold": 0.05,
            "jitter_threshold_ms": 20.0, "window_size": 10, "hysteresis_count": 3,
            "request_topic": "/adaptive_bridge/probe_req", "response_topic": "/adaptive_bridge/probe_resp"
        },
        "routing_policy": {
            "critical_always_forward": True, "noncritical_enabled": True, "noncritical_max_rate_hz": 5.0,
            "noncritical_drop_policy": "drop_oldest", "stale_threshold_ms": 500
        },
        "safety": {
            "preserve_critical_path": True, "allow_noncritical_degrade": True, "max_noncritical_queue": 10,
            "overload_drop_noncritical_first": True
        },
        "security": {
            "trust_mode": "default_deny", "allow_legacy_node_name_overrides": True, "enable_probe_hmac": False,
            "max_probe_rate_hz": 10.0
        },
        "diagnostics": {"enabled": True, "publish_interval_s": 1.0, "topic": "/adaptive_bridge/diagnostics", "verbosity": "info"},
        "overrides": {},
    }
    cfg_file = _write_yaml(tmp_path, "duplicate_topics.yaml", cfg)
    with pytest.raises(ValueError, match="duplicate topic ids"):
        ConfigManager(cfg_file)


def test_legacy_config_compatibility_emits_deprecation(tmp_path: Path) -> None:
    legacy = {
        "input_topic": "/scan",
        "critical_topic_prefix": "/adaptive_bridge/critical",
        "noncritical_topic_prefix": "/adaptive_bridge/noncritical",
        "qos_profiles": {"critical": "reliable_depth10", "noncritical": "besteffort_depth5_lifespan500ms"},
        "probe": {"enabled": True, "rate_hz": 5, "rtt_threshold_ms": 100, "loss_threshold": 0.05, "hysteresis_count": 3},
        "overrides": {"known_node": {"critical": True}},
    }
    cfg_file = _write_yaml(tmp_path, "legacy.yaml", legacy)
    with pytest.deprecated_call(match="Legacy config format detected"):
        cfg = ConfigManager(cfg_file)
    assert cfg.get_topics()[0].input_topic == "/scan"
    assert cfg.is_node_forced_critical("known_node") is True


def test_topics_are_consumable_by_topic_registry() -> None:
    cfg = ConfigManager()
    registry = TopicRegistry()
    routes = registry.build_routes(cfg.get_topics())
    assert "scan_main" in routes
