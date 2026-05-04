# scripts/tests/test_scenario_parsing.py
"""Validate scenarios.yaml structure and values."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml


def test_all_scenarios_present():
    path = os.path.join(os.path.dirname(__file__), "..", "..", "scenarios.yaml")
    with open(path) as f:
        data = yaml.safe_load(f)
    scenarios = data["scenarios"]
    assert len(scenarios) == 10, f"Expected 10 scenarios, got {len(scenarios)}"

    required_keys = {"name", "mode", "compose_file", "duration_s", "impairment", "toggle", "classifier_enabled", "description"}
    for s in scenarios:
        missing = required_keys - set(s.keys())
        assert not missing, f"Scenario '{s.get('name','?')}' missing keys: {missing}"

    names = [s["name"] for s in scenarios]
    assert len(names) == len(set(names)), f"Duplicate scenario names: {names}"

    valid_modes = {"baseline", "adaptive"}
    for s in scenarios:
        assert s["mode"] in valid_modes, f"{s['name']}: invalid mode '{s['mode']}'"


def test_impairment_ge_parameters():
    """Verify all impairment scenarios have valid GE model + bandwidth parameters."""
    path = os.path.join(os.path.dirname(__file__), "..", "..", "scenarios.yaml")
    with open(path) as f:
        data = yaml.safe_load(f)

    for s in data["scenarios"]:
        imp = s.get("impairment", {})
        if not imp.get("enabled", False):
            continue
        assert imp.get("loss_model") == "gemodel", f"{s['name']}: must use gemodel"
        # Check bandwidth_kbit is present and in a reasonable range
        assert "bandwidth_kbit" in imp, f"{s['name']}: missing bandwidth_kbit"
        assert 0 <= imp["bandwidth_kbit"] <= 100000, f"{s['name']}: bandwidth_kbit={imp['bandwidth_kbit']} out of range"
        for key in ["loss_p", "loss_r", "loss_good_pct", "loss_bad_pct"]:
            assert key in imp, f"{s['name']}: missing {key}"
            val = imp[key]
            assert isinstance(val, (int, float)), f"{s['name']}.{key} must be numeric"
            if key == "loss_p" or key == "loss_r":
                assert 0 <= val <= 100, f"{s['name']}.{key}={val} out of range [0,100]"
            elif key == "loss_good_pct":
                assert 0 <= float(val) <= 100, f"{s['name']}.{key}={val} out of range"
            elif key == "loss_bad_pct":
                assert 0 <= val <= 100, f"{s['name']}.{key}={val} out of range [0,100]"


def test_compose_files_exist():
    """Verify referenced compose files exist."""
    ws2_dir = os.path.join(os.path.dirname(__file__), "..", "..")
    path = os.path.join(ws2_dir, "scenarios.yaml")
    with open(path) as f:
        data = yaml.safe_load(f)
    for s in data["scenarios"]:
        comp = os.path.join(ws2_dir, s["compose_file"])
        assert os.path.exists(comp), f"Compose file not found: {comp}"


def test_baseline_scenarios_range():
    """Verify there are baseline and bridge scenarios."""
    path = os.path.join(os.path.dirname(__file__), "..", "..", "scenarios.yaml")
    with open(path) as f:
        data = yaml.safe_load(f)
    names = [s["name"] for s in data["scenarios"]]
    for prefix in ["baseline_clean", "baseline_mild", "bridge_clean", "bridge_mild", "bridge_toggle", "ablation_no_classifier"]:
        assert prefix in names, f"Missing required scenario: {prefix}"
