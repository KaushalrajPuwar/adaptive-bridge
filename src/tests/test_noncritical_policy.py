import pytest
from unittest.mock import MagicMock
from adaptive_bridge.noncritical_policy import NoncriticalPolicyEngine, DropStats
from adaptive_bridge.models import PolicyMode

@pytest.fixture
def mock_config():
    config = MagicMock()
    config.routing_policy.noncritical_enabled = True
    config.routing_policy.noncritical_max_rate_hz = 10.0
    config.safety.max_noncritical_queue = 5
    config.routing_policy.stale_threshold_ms = 500
    return config

@pytest.fixture
def mock_qos():
    qos = MagicMock()
    # Mock desc behavior: assume lifespan_ms comes from config
    qos.describe.return_value = {}
    return qos

def test_engine_initializes_and_allows_publish(mock_config, mock_qos):
    engine = NoncriticalPolicyEngine(mock_config, mock_qos)
    now = 1000 * 1_000_000 # 1 sec
    allowed, reason = engine.allow_publish("topic1", msg_ts_ns=now, now_ns=now)
    assert allowed is True
    assert reason is None

def test_engine_rate_limits(mock_config, mock_qos):
    engine = NoncriticalPolicyEngine(mock_config, mock_qos)
    now = 1000 * 1_000_000 # 1 sec
    
    # Burst allowed up to max_queue (5)
    for _ in range(5):
        allowed, reason = engine.allow_publish("topic1", msg_ts_ns=now, now_ns=now)
        assert allowed is True
        
    # The 6th should be rejected
    allowed, reason = engine.allow_publish("topic1", msg_ts_ns=now, now_ns=now)
    assert allowed is False
    assert reason == "rate_limit"

def test_engine_stale_drop(mock_config, mock_qos):
    engine = NoncriticalPolicyEngine(mock_config, mock_qos)
    
    msg_ts = 1000 * 1_000_000
    now = msg_ts + (600 * 1_000_000) # 600ms older
    
    allowed, reason = engine.allow_publish("topic1", msg_ts_ns=msg_ts, now_ns=now)
    assert allowed is False
    assert reason == "stale"

def test_engine_mode_disabled(mock_config, mock_qos):
    engine = NoncriticalPolicyEngine(mock_config, mock_qos)
    engine.on_mode_change("topic1", PolicyMode.DISABLED)
    now = 1000 * 1_000_000
    allowed, reason = engine.allow_publish("topic1", msg_ts_ns=now, now_ns=now)
    assert allowed is False
    assert reason == "disabled"

def test_engine_record_drops_and_stats(mock_config, mock_qos):
    engine = NoncriticalPolicyEngine(mock_config, mock_qos)
    engine.record_drop("topic1", "rate_limit")
    engine.record_drop("topic1", "rate_limit")
    engine.record_drop("topic1", "queue_overflow")
    
    stats = engine.get_stats("topic1")
    assert stats.rate_limit == 2
    assert stats.queue_overflow == 1
    assert stats.stale == 0
    assert stats.disabled == 0
