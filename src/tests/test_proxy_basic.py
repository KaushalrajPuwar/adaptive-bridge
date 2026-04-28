import importlib

import pytest

from adaptive_bridge.config_manager import ConfigManager
from adaptive_bridge.config_types import TopicConfig
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


def test_registry_build_routes_for_three_topics() -> None:
    topics = [
        TopicConfig("t1", "/scan", "/adaptive_bridge/critical/scan", "/adaptive_bridge/noncritical/scan"),
        TopicConfig("t2", "/imu", "/adaptive_bridge/critical/imu", "/adaptive_bridge/noncritical/imu"),
        TopicConfig("t3", "/odom", "/adaptive_bridge/critical/odom", "/adaptive_bridge/noncritical/odom"),
    ]
    registry = TopicRegistry()
    routes = registry.build_routes(topics)
    assert list(routes.keys()) == ["t1", "t2", "t3"]
    assert routes["t2"].input_topic == "/imu"


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


def test_proxy_callback_updates_only_target_topic() -> None:
    pytest.importorskip("rclpy")
    proxy_module = importlib.import_module("adaptive_bridge.proxy_node")
    ProxyNode = proxy_module.ProxyNode

    class _FakePub:
        def __init__(self) -> None:
            self.calls = 0

        def publish(self, _msg) -> None:
            self.calls += 1

    class _Logger:
        def info(self, _msg) -> None:
            pass

        def error(self, _msg) -> None:
            pass

    node = ProxyNode.__new__(ProxyNode)
    node._routes = {"a": object(), "b": object()}
    node._counters_by_topic = {"a": TopicCounters(), "b": TopicCounters()}
    node._publishers_critical = {"a": _FakePub(), "b": _FakePub()}
    node._publishers_noncritical = {"a": _FakePub(), "b": _FakePub()}
    node._last_log = 10**9
    node.get_logger = lambda: _Logger()

    cb = node._make_topic_callback("a")
    cb(object())

    assert node._counters_by_topic["a"].total_received == 1
    assert node._counters_by_topic["a"].total_forwarded_critical == 1
    assert node._counters_by_topic["a"].total_forwarded_noncritical == 1
    assert node._counters_by_topic["b"].total_received == 0
    assert node._publishers_critical["a"].calls == 1
    assert node._publishers_critical["b"].calls == 0
    assert node._publishers_noncritical["a"].calls == 1
    assert node._publishers_noncritical["b"].calls == 0


def test_proxy_shutdown_clears_all_entities() -> None:
    pytest.importorskip("rclpy")
    proxy_module = importlib.import_module("adaptive_bridge.proxy_node")
    ProxyNode = proxy_module.ProxyNode

    node = ProxyNode.__new__(ProxyNode)
    destroyed_subscribers = []
    destroyed_publishers = []
    node._subscribers = {"a": object(), "b": object(), "c": object()}
    node._publishers_critical = {"a": object(), "b": object(), "c": object()}
    node._publishers_noncritical = {"a": object(), "b": object(), "c": object()}
    node.destroy_subscription = lambda sub: destroyed_subscribers.append(sub)
    node.destroy_publisher = lambda pub: destroyed_publishers.append(pub)

    node._shutdown_entities()

    assert len(destroyed_subscribers) == 3
    assert len(destroyed_publishers) == 6
    assert node._subscribers == {}
    assert node._publishers_critical == {}
    assert node._publishers_noncritical == {}
