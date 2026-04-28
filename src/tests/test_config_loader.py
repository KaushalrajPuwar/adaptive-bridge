from adaptive_bridge.config_manager import ConfigManager


def test_config_manager_defaults_load() -> None:
    cfg = ConfigManager()
    assert cfg.get("input_topic") == "/scan"


def test_config_manager_topic_names_shape() -> None:
    cfg = ConfigManager()
    names = cfg.get_topic_names()
    assert "input_topic" in names
    assert "critical_prefix" in names
    assert "noncritical_prefix" in names


def test_config_manager_qos_mapping_has_paths() -> None:
    cfg = ConfigManager()
    mapping = cfg.get_qos_mapping()
    assert mapping.get("critical")
    assert mapping.get("noncritical")


def test_config_manager_probe_shape() -> None:
    cfg = ConfigManager()
    probe = cfg.get_probe_config()
    assert "enabled" in probe
    assert "rate_hz" in probe
    assert "rtt_threshold_ms" in probe
    assert "loss_threshold" in probe
    assert "hysteresis_count" in probe


def test_unknown_node_not_forced_critical() -> None:
    cfg = ConfigManager()
    assert cfg.is_node_forced_critical("unknown_node_name") is False
