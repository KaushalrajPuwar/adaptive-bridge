# adaptive-bridge

A ROS 2 package for dynamically bridging critical and non-critical subscribers in wireless and local systems, addressing the slow subscriber problem with adaptive QoS.

## Overview

`adaptive-bridge` mitigates the slow subscriber problem, where slow subscribers (e.g., remote nodes over wireless networks or resource-constrained local nodes) cause publisher choking or message loss. It dynamically classifies subscribers as critical (e.g., low-latency navigation nodes) or non-critical (e.g., high-latency visualization nodes) based on callback latency, reassigns non-critical subscribers to separate topics, and applies adaptive QoS settings (e.g., `RELIABLE` for critical, `BEST_EFFORT` with downsampling for non-critical). The package supports navigation and image streaming scenarios and is compatible with Cyclone DDS and Fast DDS.

This package has a working prototype that runs today, with production hardening in progress (see `docs/14_PRODUCTION_DEVELOPMENT_ROADMAP.md`).

## Planned Features

- **Dynamic Subscriber Classification**: Runtime classification using callback latency (e.g., <100 ms = critical, >100 ms = non-critical).
- **Adaptive QoS**: Scenario-specific QoS (e.g., `RELIABLE` for navigation, downsampled `BEST_EFFORT` for images).
- **Topic Decoupling**: Routes messages to critical (original) and non-critical (`/external/*`) topics via a proxy node.
- **User Configuration**: YAML-based setup for critical topics and QoS overrides.
- **DDS Compatibility**: Supports Cyclone DDS and Fast DDS.

## Installation (Development Available Now)

```bash
cd /path/to/adaptive_bridge_ws
rm -rf build install log
colcon build --packages-select adaptive_bridge
source install/setup.bash
```

**Note:** Production release packaging is pending completion of roadmap Steps 1-20.

## Usage

### Available now (prototype baseline)

- Build package in development workspace.
- Run `proxy_node` and forward `/scan` (`sensor_msgs/LaserScan`) to:
  - `/adaptive_bridge/critical/scan`
  - `/adaptive_bridge/noncritical/scan`
- Validate forwarding using `ros2 topic echo`.

### Planned in roadmap (production hardening)

- Classifier node with hysteresis and probe-driven decisions.
- Security controls for control-plane messages.
- Full evaluation harness and repeatable experiment automation in eval workspace.
- Production-grade multi-topic policy engine and test pyramid.

## Development Status (Step 1 Snapshot — 2026-04-28)

- **Stage**: Prototype implementation exists and runs; production system is in progress.
- **Roadmap Position**: Step 1 completed; Step 2 next (`docs/14_PRODUCTION_DEVELOPMENT_ROADMAP.md`).
- **Testing Direction**: Evaluation will include controlled impairment experiments and multi-RMW validation (FastDDS/CycloneDDS).
- **Metrics**: Latency, message loss, throughput, CPU/network usage.

## Governance

- Architecture changes must follow `docs/11_DECISIONS_LOG.md` change-control rules before implementation.
- Execution order and delivery gates are defined in `docs/14_PRODUCTION_DEVELOPMENT_ROADMAP.md`.

## Current Implementation Status (as of 2026-04-28)

**Implemented:**
- `proxy_node.py`: Single-topic LaserScan forwarding with dual critical/noncritical outputs
- `config_manager.py`: YAML configuration loading with QoS profile mapping
- `qos_manager.py`: Named QoS profile resolution
- `diagnostics.py`: Standalone diagnostics node
- `utils/probes.py`: Probe client/responder utilities for RTT measurement

**In Progress (Steps 1-20):**
- Multi-topic proxy support
- Classifier node with hysteresis
- Security controls
- Production test suite
- Evaluation harness

See `docs/14_PRODUCTION_DEVELOPMENT_ROADMAP.md` for detailed step breakdown.

## Development Validation Commands

```bash
cd /path/to/adaptive_bridge_ws
rm -rf build install log
colcon build --packages-select adaptive_bridge
source install/setup.bash
colcon test --packages-select adaptive_bridge
colcon test-result --verbose
```
## License

Licensed under the Apache License 2.0. Check LICENSE file for the full license.

## Contributing

Contributions are welcome post-development. Guidelines for issues and pull requests will be provided in the CONTRIBUTING file on GitHub repository.
