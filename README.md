# adaptive-bridge

A ROS 2 package for dynamically bridging critical and non-critical subscribers in wireless and local systems, addressing the slow subscriber problem with adaptive QoS.

## Overview

`adaptive-bridge` mitigates the slow subscriber problem, where slow subscribers (e.g., remote nodes over wireless networks or resource-constrained local nodes) cause publisher choking or message loss. It dynamically classifies subscribers as critical (e.g., low-latency navigation nodes) or non-critical (e.g., high-latency visualization nodes) based on callback latency, reassigns non-critical subscribers to separate topics, and applies adaptive QoS settings (e.g., `RELIABLE` for critical, `BEST_EFFORT` with downsampling for non-critical). The package supports navigation and image streaming scenarios and is compatible with Cyclone DDS and Fast DDS.

## Installation

```bash
cd /path/to/adaptive_bridge_ws
rm -rf build install log
colcon build --packages-select adaptive_bridge
source install/setup.bash
```

## Usage

Run the proxy node to forward a topic through dual critical/noncritical output paths:

```bash
ros2 run adaptive_bridge proxy_node --ros-args \
  -p config_path:=/path/to/config/default.yaml
```

This subscribes to input topics defined in the config file (e.g., `/scan`) and republishes each message to:
- `/adaptive_bridge/critical/<topic>` (forwarded with source QoS setting)
- `/adaptive_bridge/noncritical/<topic>` (forwarded through rate-limiting and degradation policy)

Validate forwarding using `ros2 topic echo`.

## Components

| Component | Description |
|-----------|-------------|
| `proxy_node` | Core bridge: subscribes to input topics, publishes dual critical/noncritical streams with per-topic QoS, rate limiting, and diagnostics |
| `classifier_node` | ROS wrapper around the classifier state machine (probe subscription and decision publishing wiring in progress) |
| `diagnostics_node` | Standalone diagnostics publisher for observability |

## Key Modules

- **config_types.py** — Typed configuration model (BridgeConfig, ClassifierConfig, ProbeConfig, etc.) with schema validation.
- **config_manager.py** — YAML loading with typed getters and legacy compatibility mode.
- **qos_manager.py** — Named QoS profile resolution with three-tier fallback.
- **topic_registry.py** — Deterministic topic route builder with uniqueness enforcement.
- **noncritical_policy.py** — Token-bucket rate limiter, staleness drops, mode-disabled drops.
- **diagnostics.py + diagnostics_schema.py** — Schema-versioned diagnostics payload with pure-Python collector and ROS publisher.
- **utils/probes.py** — Hardened probe client/responder (protocol v1, bounded storage, windowed metrics, jitter, timeout).
- **classifier_core.py + classifier_types.py** — Pure-Python classifier state machine (UNKNOWN/CRITICAL/NONCRITICAL, hysteresis, forced overrides).

## Development Validation

```bash
cd /path/to/adaptive_bridge_ws
rm -rf build install log
colcon build --packages-select adaptive_bridge
source install/setup.bash
colcon test --packages-select adaptive_bridge
colcon test-result --verbose
```

The test suite includes unit tests for configuration validation, proxy routing, QoS resolution, noncritical policy, diagnostics payload structure, probe protocol, and classifier state machine logic (103+ tests, 0 failures expected).

## License

Licensed under the Apache License 2.0. Check LICENSE file for the full license.

## Contributing

Contributions are welcome post-development. Guidelines for issues and pull requests will be provided in the CONTRIBUTING file on GitHub repository.
