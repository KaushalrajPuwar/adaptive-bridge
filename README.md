# adaptive-bridge

A ROS 2 package for dynamically bridging critical and non-critical subscribers in wireless and local systems, addressing the slow subscriber problem with adaptive QoS.

## Overview

`adaptive-bridge` mitigates the slow subscriber problem, where slow subscribers (e.g., remote nodes over wireless networks or resource-constrained local nodes) cause publisher choking or message loss. It dynamically classifies subscribers as critical (e.g., low-latency navigation nodes) or non-critical (e.g., high-latency visualization nodes) based on callback latency, reassigns non-critical subscribers to separate topics, and applies adaptive QoS settings (e.g., `RELIABLE` for critical, `BEST_EFFORT` with downsampling for non-critical). The package supports navigation and image streaming scenarios and is compatible with Cyclone DDS and Fast DDS.

This package is under development for ROS 2 Jazzy, targeting robotic applications requiring reliable communication. It provides an automated, user-friendly solution configurable via YAML.

## Planned Features

- **Dynamic Subscriber Classification**: Runtime classification using callback latency (e.g., <100 ms = critical, >100 ms = non-critical).
- **Adaptive QoS**: Scenario-specific QoS (e.g., `RELIABLE` for navigation, downsampled `BEST_EFFORT` for images).
- **Topic Decoupling**: Routes messages to critical (original) and non-critical (`/external/*`) topics via a proxy node.
- **User Configuration**: YAML-based setup for critical topics and QoS overrides.
- **DDS Compatibility**: Supports Cyclone DDS and Fast DDS.

## Installation

This package is under development and not yet available. Source installation instructions will be provided upon release via the GitHub repository.

## Usage

Usage instructions, including YAML configuration and launch files, will be added post-development. The package will support:
- Navigation (e.g., `/turtle1/cmd_vel`).
- Image streaming (e.g., `/camera/image_raw`).

## Development Status

- **Stage**: Pre-development (planning phase).
- **Timeline**: Targeting completion in 12 weeks for RA-L submission.
- **Testing**: Planned Gazebo simulations with simulated Wi-Fi (Planned: 50 ms latency, 5% packet loss. Mulitple scenarios might me tested in future as per need) for navigation and image streaming, using Cyclone DDS and Fast DDS.
- **Metrics**: Latency, message loss, throughput, CPU/network usage.

## License

Licensed under the BSD-3-Clause License. Check LICENSE file for full license.
