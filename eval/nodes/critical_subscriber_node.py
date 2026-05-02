#!/usr/bin/env python3
"""Critical subscriber — lightweight subscriber representing a safety-critical consumer."""
import rclpy
from base_subscriber import BaseSubscriber


def main():
    rclpy.init()
    node = BaseSubscriber("eval_critical_subscriber")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
