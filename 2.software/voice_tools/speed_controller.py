#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
速度控制器：维护当前速度状态，接收 agent 指令，发布 /cmd_vel

用法:
    source /opt/ros/humble/setup.bash
    source ~/G-Exo/ros2_ws/install/setup.bash
    python3 speed_controller.py          # 启动控制器
    python3 speed_controller.py status   # 查看当前速度
    python3 speed_controller.py speed_up     # 加速 +0.1
    python3 speed_controller.py slow_down    # 减速 -0.1
    python3 speed_controller.py stop         # 停止
    python3 speed_controller.py set 0.5      # 直接设置速度
"""
import sys
import os
import time
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist

STATE_FILE = os.path.expanduser('~/.cache/omni_agent/speed_state.txt')
STEP = 0.1      # 每次加速/减速的步长 (m/s)
MAX_SPEED = 1.0 # 最大限速 (m/s)
DISCOVERY_WAIT = 2.0  # 等待 DDS 发现完成 (秒)
PUBLISH_COUNT = 8     # 发布次数（确保接收端收到）


def load_state():
    """读取当前速度状态"""
    try:
        with open(STATE_FILE) as f:
            return float(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0.0


def save_state(speed):
    """保存速度状态"""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        f.write('%.2f' % speed)


class SpeedController(Node):
    def __init__(self):
        super().__init__('speed_controller')
        self.pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.get_logger().info('speed_controller 已启动，发布 /cmd_vel')

    def publish(self, linear_x, angular_z=0.0):
        """等待 DDS 发现完成后，间隔发布多次确保接收方收到"""
        self.get_logger().info('等待 %.1fs 让 DDS 发现订阅端...' % DISCOVERY_WAIT)
        time.sleep(DISCOVERY_WAIT)
        msg = Twist()
        msg.linear.x = float(linear_x)
        msg.angular.z = float(angular_z)
        for i in range(PUBLISH_COUNT):
            self.pub.publish(msg)
            time.sleep(0.15)  # 间隔发布，给订阅端处理时间
        self.get_logger().info('🚀 已发布 %d 次 /cmd_vel: linear.x=%.2f angular.z=%.2f' % (PUBLISH_COUNT, linear_x, angular_z))
        return linear_x


def main(args=None):
    rclpy.init(args=args)

    # 命令行操作模式（无需常驻）
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        node = SpeedController()
        if cmd == 'status':
            print('当前速度: %.2f m/s' % load_state())
        elif cmd == 'speed_up':
            new = min(load_state() + STEP, MAX_SPEED)
            node.publish(new)
            save_state(new)
            print('✅ 已加速到 %.2f m/s' % new)
        elif cmd == 'slow_down':
            new = max(load_state() - STEP, 0.0)
            node.publish(new)
            save_state(new)
            print('✅ 已减速到 %.2f m/s' % new)
        elif cmd == 'stop':
            node.publish(0.0)
            save_state(0.0)
            print('🛑 已停止')
        elif cmd == 'set' and len(sys.argv) > 2:
            new = float(sys.argv[2])
            node.publish(new)
            save_state(new)
            print('✅ 已设置速度 %.2f m/s' % new)
        else:
            print('未知命令')
        node.destroy_node()
        rclpy.shutdown()
        return

    # 常驻模式（可选，供未来持续调速）
    node = SpeedController()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
