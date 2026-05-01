# src/adaptive_bridge/launch/adaptive_bridge.launch.py
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    default_config = os.path.join(
        get_package_share_directory("adaptive_bridge"),
        "config", "default.yaml",
    )
    config_path_arg = DeclareLaunchArgument(
        "config_path",
        default_value=default_config,
        description="Absolute path to Adaptive Bridge YAML config.",
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
            ),
        ]
    )
