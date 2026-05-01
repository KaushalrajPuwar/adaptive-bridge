# src/adaptive_bridge/launch/adaptive_bridge_full.launch.py
"""Full-stack launch: proxy + classifier + diagnostics for production."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    pkg_share = get_package_share_directory("adaptive_bridge")
    default_config = os.path.join(pkg_share, "config", "stress.yaml")
    config_arg = DeclareLaunchArgument(
        "config_path", default_value=default_config,
        description="Absolute path to Adaptive Bridge YAML config.",
    )
    return LaunchDescription([
        config_arg,
        Node(
            package="adaptive_bridge", executable="proxy_node",
            name="adaptive_bridge_proxy", output="screen",
            parameters=[{"config_path": LaunchConfiguration("config_path")}],
        ),
        Node(
            package="adaptive_bridge", executable="classifier_node",
            name="adaptive_bridge_classifier", output="screen",
            parameters=[{"config_path": LaunchConfiguration("config_path")}],
        ),
        Node(
            package="adaptive_bridge", executable="diagnostics_node",
            name="adaptive_bridge_diagnostics", output="screen",
            parameters=[{"config_path": LaunchConfiguration("config_path")}],
        ),
    ])
