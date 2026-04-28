# src/adaptive_bridge/launch/adaptive_bridge.launch.py
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    config_path_arg = DeclareLaunchArgument(
        "config_path",
        default_value="",
        description="Absolute path to Adaptive Bridge YAML config (optional).",
    )
    return LaunchDescription(
        [
            config_path_arg,
            Node(
                package="adaptive_bridge",
                executable="proxy_node",
                name="adaptive_bridge_proxy",
                output="screen",
                parameters=[{"config_path": LaunchConfiguration("config_path")}],
            )
        ]
    )
