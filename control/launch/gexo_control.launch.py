"""Launch the G-Exo control node in conservative zero-output mode."""

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node
import os


def generate_launch_description():
    package_share = get_package_share_directory("gexo_control")
    config = os.path.join(package_share, "config", "gexo_control.yaml")
    return LaunchDescription(
        [
            Node(
                package="gexo_control",
                executable="gexo_control_node",
                name="gexo_control_node",
                output="screen",
                parameters=[config],
            )
        ]
    )
