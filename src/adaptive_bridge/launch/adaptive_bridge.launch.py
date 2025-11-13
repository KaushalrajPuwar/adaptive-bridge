# src/adaptive_bridge/launch/adaptive_bridge.launch.py
from launch import LaunchDescription
from launch_ros.actions import Node
import os


def generate_launch_description():
    pkg_share = os.path.join(os.path.dirname(__file__), "..", "..")
    config_path_param = os.path.join(pkg_share, "config.yaml")  # optional
    return LaunchDescription(
        [
            Node(
                package="adaptive_bridge",
                executable="proxy_node",
                name="adaptive_bridge_proxy",
                output="screen",
                parameters=[{"config_path": ""}],  # override with an absolute path if desired
            )
        ]
    )
