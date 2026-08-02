#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cmd_vel 模拟订阅节点（验证用）
订阅 /cmd_vel 并打印当前速度状态。
后续接入真实底盘时无需改动本节点，直接由底盘节点订阅即可。

用法:
    source /opt/ros/humble/setup.bash
    source ~/G-Exo/ros2_ws/install/setup.bash
    python3 cmd_vel_monitor.py
"""
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist


class CmdVelMonitor(Node):
    def __init__(self):
        super().__init__('cmd_vel_monitor')
        self.sub = self.create_subscription(Twist, '/cmd_vel', self.on_cmd_vel, 10)
        self.linear_x = 0.0
        self.angular_z = 0.0
        self.get_logger().info('cmd_vel_monitor 已启动，订阅 /cmd_vel')

    def on_cmd_vel(self, msg: Twist):
        self.linear_x = msg.linear.x
        self.angular_z = msg.angular.z
        self.get_logger().info(
            '📢 /cmd_vel -> linear.x=%.2f  angular.z=%.2f  (当前速度: %.2f m/s)'
            % (self.linear_x, self.angular_z, self.linear_x))


def main(args=None):
    rclpy.init(args=args)
    node = CmdVelMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
