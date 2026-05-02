#!/usr/bin/env python3
"""Slow subscriber — optional callback delay to simulate CPU-bound consumer."""
import os
import rclpy
from base_subscriber import BaseSubscriber


def main():
    rclpy.init()
    # Use TARGET_NODE env to label latency CSV correctly
    os.environ.setdefault("TARGET_NODE", "slow_subscriber")
    node = BaseSubscriber("eval_slow_subscriber")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
