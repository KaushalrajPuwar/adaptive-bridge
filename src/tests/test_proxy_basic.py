import importlib

import pytest

from adaptive_bridge.config_manager import ConfigManager
from adaptive_bridge.models import ClassifierSnapshot, PolicyMode, TopicCounters, TopicRuntimeState
from adaptive_bridge.topic_registry import TopicRegistry, sanitize_topic_name


def test_sanitize_topic_name_cases() -> None:
    assert sanitize_topic_name("/scan") == "scan"
    assert sanitize_topic_name("/foo/bar") == "foo_bar"
    assert sanitize_topic_name("///") == "topic"
    assert sanitize_topic_name("/foo/bar/") == "foo_bar"


def test_registry_build_routes_from_config_topics() -> None:
    cfg = ConfigManager()
    registry = TopicRegistry()
    routes = registry.build_routes(cfg.get_topics())
    assert routes
    assert "scan_main" in routes
    assert routes["scan_main"].input_topic == "/scan"


def test_registry_rejects_duplicate_topic_id() -> None:
    cfg = ConfigManager()
    topics = cfg.get_topics()
    duplicate = [topics[0], topics[0]]
    registry = TopicRegistry()
    with pytest.raises(ValueError, match="duplicate topic_id"):
        registry.build_routes(duplicate)


def test_registry_rejects_duplicate_output_topics() -> None:
    cfg = ConfigManager()
    topics = cfg.get_topics()
    a = topics[0]
    b = type(a)(
        id="scan_main_2",
        input_topic="/scan_secondary",
        critical_output=a.critical_output,
        noncritical_output="/adaptive_bridge/noncritical/scan_secondary",
        qos_overrides={},
    )
    registry = TopicRegistry()
    with pytest.raises(ValueError, match="duplicate critical_output"):
        registry.build_routes([a, b])


def test_registry_get_unknown_topic_raises() -> None:
    registry = TopicRegistry()
    with pytest.raises(ValueError, match="unknown topic_id"):
        registry.get_route("missing")


def test_registry_list_routes_is_deterministic() -> None:
    cfg = ConfigManager()
    registry = TopicRegistry()
    registry.build_routes(cfg.get_topics())
    listed = registry.list_routes()
    assert [route.topic_id for route in listed] == ["scan_main"]


def test_models_serialize_for_diagnostics() -> None:
    registry = TopicRegistry()
    registry.build_routes(ConfigManager().get_topics())
    route = registry.get_route("scan_main")
    counters = TopicCounters(total_received=5, total_forwarded_critical=5, total_forwarded_noncritical=4)
    state = TopicRuntimeState(route=route, counters=counters, noncritical_mode=PolicyMode.DEGRADED)
    state.latest_classifier_snapshot["sub1"] = ClassifierSnapshot(
        subscriber_id="sub1",
        classification="NONCRITICAL",
        reason_flags=("loss",),
        avg_rtt_ms=120.0,
        loss=0.12,
    )
    payload = state.to_dict()
    assert payload["noncritical_mode"] == "DEGRADED"
    assert payload["counters"]["total_received"] == 5
    assert payload["latest_classifier_snapshot"]["sub1"]["classification"] == "NONCRITICAL"


def test_proxy_module_imports_when_rclpy_available() -> None:
    pytest.importorskip("rclpy")
    module = importlib.import_module("adaptive_bridge.proxy_node")
    assert module.ProxyNode is not None
    assert callable(module.main)
