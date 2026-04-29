import pytest
import os
import tempfile
import yaml
from rclpy.qos import QoSHistoryPolicy, QoSReliabilityPolicy, QoSDurabilityPolicy

from adaptive_bridge.qos_manager import QoSManager

@pytest.fixture
def temp_qos_yaml():
    data = {
        "test_reliable": {
            "reliability": "RELIABLE",
            "history": "KEEP_LAST",
            "depth": 20,
            "durability": "TRANSIENT_LOCAL"
        },
        "test_besteffort_life": {
            "reliability": "BEST_EFFORT",
            "history": "KEEP_LAST",
            "depth": 3,
            "durability": "VOLATILE",
            "lifespan_ms": 1000
        }
    }
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml') as f:
        yaml.dump(data, f)
        path = f.name
    yield path
    os.remove(path)

def test_qos_manager_load_from_dict():
    profiles = {
        "prof1": {"reliability": "RELIABLE", "depth": 5}
    }
    qm = QoSManager(qos_profiles=profiles)
    prof = qm.resolve("t1", "critical") # fallback to global due to missing topic map
    assert prof.depth == 10 # global fallback critical depth
    
    # Map it
    qm = QoSManager(qos_profiles=profiles, topic_qos_profiles={"t1": {"critical": "prof1"}})
    prof = qm.resolve("t1", "critical")
    assert prof.depth == 5
    assert prof.reliability == QoSReliabilityPolicy.RELIABLE

def test_qos_manager_load_profiles(temp_qos_yaml):
    qm = QoSManager()
    qm.load_profiles(temp_qos_yaml)
    
    # Overwrite topic map
    qm._topic_qos_profiles = {"t1": {"critical": "test_reliable", "noncritical": "test_besteffort_life"}}
    
    prof_c = qm.resolve("t1", "critical")
    assert prof_c.depth == 20
    assert prof_c.durability == QoSDurabilityPolicy.TRANSIENT_LOCAL
    
    prof_nc = qm.resolve("t1", "noncritical")
    assert prof_nc.depth == 3
    assert prof_nc.reliability == QoSReliabilityPolicy.BEST_EFFORT

def test_qos_manager_describe(temp_qos_yaml):
    qm = QoSManager()
    qm.load_profiles(temp_qos_yaml)
    qm._topic_qos_profiles = {"t1": {"critical": "test_reliable", "noncritical": "test_besteffort_life"}}
    
    desc_c = qm.describe("t1", "critical")
    assert desc_c["profile_name"] == "test_reliable"
    assert desc_c["reason"] == "per-topic override"
    assert desc_c["lifespan_ms"] is None
    
    desc_nc = qm.describe("t1", "noncritical")
    assert desc_nc["profile_name"] == "test_besteffort_life"
    assert desc_nc["reason"] == "per-topic override"
    assert desc_nc["lifespan_ms"] == 1000

def test_global_fallback():
    qm = QoSManager(qos_profiles={})
    
    # topic not mapped -> role default -> missing in templates -> global fallback
    prof = qm.resolve("unmapped", "critical")
    assert prof.reliability == QoSReliabilityPolicy.RELIABLE
    assert prof.depth == 10
    
    desc = qm.describe("unmapped", "critical")
    assert desc["reason"] == "global fallback"
    assert desc["profile_name"] == "reliable_depth10"
    
def test_invalid_profile():
    with pytest.raises(ValueError):
        QoSManager(qos_profiles={"bad": {"depth": "abc"}})
