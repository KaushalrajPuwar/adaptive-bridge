# adaptive-bridge

A ROS 2 package for dynamically bridging critical and non-critical subscribers in wireless and local systems, addressing the slow subscriber problem with adaptive QoS.

## Quickstart

```bash
cd /home/kaushalraj/adaptive_bridge_ws
source install/setup.bash
ros2 launch adaptive_bridge test_bridge.launch.py
```

This launches the proxy + classifier on the default config. Validate with:

```bash
ros2 topic echo /adaptive_bridge/classifier/state | head -5
```

## Overview

`adaptive-bridge` mitigates the slow subscriber problem, where slow subscribers (e.g., remote nodes over wireless networks or resource-constrained local nodes) cause publisher choking or message loss. It dynamically classifies subscribers as critical (e.g., low-latency navigation nodes) or non-critical (e.g., high-latency visualization nodes) based on callback latency, reassigns non-critical subscribers to separate topics, and applies adaptive QoS settings (e.g., `RELIABLE` for critical, `BEST_EFFORT` with downsampling for non-critical). The package supports navigation and image streaming scenarios and is compatible with Cyclone DDS and Fast DDS.

## Installation

```bash
cd /home/kaushalraj/adaptive_bridge_ws
rm -rf build install log
colcon build --packages-select adaptive_bridge
source install/setup.bash
```

## Usage

### Launch Profiles

| Profile | Command | Components |
|---------|---------|-----------|
| Proxy only | `ros2 launch adaptive_bridge adaptive_bridge.launch.py` | proxy_node |
| Quick test | `ros2 launch adaptive_bridge test_bridge.launch.py` | proxy_node + classifier_node |
| Full stack | `ros2 launch adaptive_bridge adaptive_bridge_full.launch.py` | proxy_node + classifier_node + diagnostics_node |

All profiles accept an optional `config_path` override:

```bash
ros2 launch adaptive_bridge adaptive_bridge.launch.py config_path:=/home/kaushalraj/adaptive_bridge_ws/install/adaptive_bridge/share/adaptive_bridge/config/stress.yaml
```

The default config path for each profile is automatically resolved from the installed package share directory.

### Run Individual Nodes

```bash
ros2 run adaptive_bridge proxy_node --ros-args \
  -p config_path:=/home/kaushalraj/adaptive_bridge_ws/install/adaptive_bridge/share/adaptive_bridge/config/default.yaml

ros2 run adaptive_bridge classifier_node --ros-args \
  -p config_path:=/home/kaushalraj/adaptive_bridge_ws/install/adaptive_bridge/share/adaptive_bridge/config/default.yaml
```

## Components

| Component | Description |
|-----------|-------------|
| `proxy_node` | Core bridge: subscribes to input topics, publishes dual critical/noncritical streams with per-topic QoS, rate limiting, and diagnostics |
| `classifier_node` | ROS wrapper around the classifier state machine: probes subscriber health and drives policy mode |
| `diagnostics_node` | Standalone diagnostics publisher for observability |
| `probe_responder` | Probe responder for testing (echoes probe messages back) |

## Key Modules

- **config_types.py** — Typed configuration model (BridgeConfig, ClassifierConfig, ProbeConfig, etc.) with schema validation.
- **config_manager.py** — YAML loading with typed getters and legacy compatibility mode.
- **qos_manager.py** — Named QoS profile resolution with three-tier fallback.
- **topic_registry.py** — Deterministic topic route builder with uniqueness enforcement.
- **noncritical_policy.py** — Token-bucket rate limiter, staleness drops, mode-disabled drops.
- **policy_engine.py** — Subscriber-to-policy mode mapper with transition damping and forced-critical override.
- **safety_supervisor.py** — Global mode machine (NORMAL/DEGRADED/EMERGENCY/FAILURE) with hysteresis window transitions.
- **diagnostics.py + diagnostics_schema.py** — Schema-versioned diagnostics payload with pure-Python collector and ROS publisher.
- **utils/probes.py** — Hardened probe client/responder (protocol v1, bounded storage, windowed metrics, jitter, timeout).
- **utils/security.py** — HMAC signing and replay protection for control-plane classifier signals.
- **classifier_core.py + classifier_types.py** — Pure-Python classifier state machine (UNKNOWN/CRITICAL/NONCRITICAL, hysteresis, forced overrides).

## Development Validation

```bash
cd /home/kaushalraj/adaptive_bridge_ws
rm -rf build install log
colcon build --packages-select adaptive_bridge
source install/setup.bash
colcon test --packages-select adaptive_bridge
colcon test-result --verbose
```

The test suite includes unit, integration, and ROS2 live-graph tests for all components (183+ tests, 0 failures expected).

## License

Licensed under the Apache License 2.0. Check LICENSE file for the full license.

## Contributing

Contributions are welcome post-development. Guidelines for issues and pull requests will be provided in the CONTRIBUTING file on GitHub repository.
