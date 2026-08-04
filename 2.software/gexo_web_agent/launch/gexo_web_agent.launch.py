"""Launch the web agent, optionally with the mock controller node.

    ros2 launch gexo_web_agent gexo_web_agent.launch.py
    ros2 launch gexo_web_agent gexo_web_agent.launch.py use_mock_controller:=true
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            DeclareLaunchArgument("transport", default_value="ros2"),
            DeclareLaunchArgument("topic", default_value="/g_exo/bridge"),
            DeclareLaunchArgument("port", default_value="8000"),
            DeclareLaunchArgument("use_mock_controller", default_value="false"),
            Node(
                package="gexo_web_agent",
                executable="gexo-web-agent",
                name="gexo_web_agent",
                output="screen",
                arguments=[
                    "--transport", LaunchConfiguration("transport"),
                    "--port", LaunchConfiguration("port"),
                ],
                additional_env={"GEXO_BRIDGE__TOPIC": LaunchConfiguration("topic")},
            ),
            Node(
                package="gexo_web_agent",
                executable="gexo-mock-controller",
                name="gexo_mock_controller",
                output="screen",
                condition=IfCondition(LaunchConfiguration("use_mock_controller")),
                arguments=["--topic", LaunchConfiguration("topic")],
            ),
        ]
    )
