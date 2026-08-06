"""Launch the read-only G-Exo IMU telemetry web application."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            DeclareLaunchArgument("port", default_value="8000"),
            Node(
                package="gexo_web_agent",
                executable="gexo-web-agent",
                name="gexo_web_agent",
                output="screen",
                arguments=["--port", LaunchConfiguration("port")],
                additional_env={"GEXO_TELEMETRY__ENABLED": "true"},
            ),
        ]
    )
