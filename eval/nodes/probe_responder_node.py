#!/usr/bin/env python3
"""
Probe responder node — responds to classifier probe requests.

Uses WS1's ProbeResponder from adaptive_bridge.utils.probes.
WS1 install must be sourced at runtime (mounted as /opt/ws1_install).
"""
import rclpy
from adaptive_bridge.utils.probes import ProbeResponder


def main():
    rclpy.init()
    node = ProbeResponder(node_name="eval_probe_responder")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
