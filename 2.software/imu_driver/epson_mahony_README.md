# G-Exo ROS2 工作区 — Epson G354 IMU + Mahony AHRS 姿态解算

echo "=== USB devices ===" && ls -la /dev/ttyUSB* 2>&1 && echo "" && echo "=== dmesg USB (last 20 lines) ===" && sudo dmesg | grep -i -E "ttyUSB|usb|ch34|cp210|ftdi|disconnect" | tail -20 && echo "" && echo "=== ch341 module info ===" && lsmod | grep -E "ch34|cp210" && echo "" && echo "=== udev info for ttyUSB0 ===" && udevadm info -a -n /dev/ttyUSB0 2>&1 | head -30

> 本工作区基于 [ess_imu_driver2](https://github.com/cubicleguy/ess_imu_driver2.git) 封装，集成 Mahony AHRS 姿态估计算法，用于 G-Exo 外骨骼项目的 IMU 数据采集与姿态解算。

---

## 目录

- [硬件要求](#硬件要求)
- [软件环境](#软件环境)
- [快速开始](#快速开始)
- [启动模式说明](#启动模式说明)
- [ROS2 Topic 说明](#ros2-topic-说明)
- [Mahony AHRS 工作流程](#mahony-ahrs-工作流程)
- [可配置参数](#可配置参数)
- [串口权限配置](#串口权限配置)
- [常见问题](#常见问题)

---

## 硬件要求

| 组件 | 型号 | 说明 |
|------|------|------|
| IMU | **Epson G354PDH0** | 6 轴惯性测量单元 |
| USB 转串口 | **CH340** | USB-UART 桥接芯片 |
| 串口路径 | `/dev/ttyUSB0` | 系统自动识别 |

---

## 软件环境

| 软件 | 版本 |
|------|------|
| 操作系统 | Ubuntu 22.04 LTS |
| ROS2 | Humble Hawksbill |
| 编译器 | GCC (C99/C++14) |
| 构建工具 | colcon |

---

## 快速开始

### 1. 安装依赖

```bash
cd ~/G-Exo/ros2_ws
source /opt/ros/humble/setup.bash
rosdep install -i --from-path src --rosdistro humble -y
```

### 2. 构建工作区

```bash
cd ~/G-Exo/ros2_ws
source /opt/ros/humble/setup.bash
colcon build --packages-select ess_imu_driver2 --symlink-install
```

### 3. 配置串口权限（首次使用）

```bash
# 将用户加入 dialout 组（永久生效，重新登录后激活）
sudo usermod -a -G dialout $USER

# 或者创建 udev 规则（立即生效，推荐）
sudo tee /etc/udev/rules.d/99-ch340-ttyusb.rules << 'EOF'
SUBSYSTEM=="tty", ENV{ID_VENDOR_ID}=="1a86", ENV{ID_MODEL_ID}=="7523", MODE="0666"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### 4. 启动 IMU + Mahony AHRS

```bash
cd ~/G-Exo/ros2_ws
source /opt/ros/humble/setup.bash
source install/setup.bash

# 启动 Mahony AHRS 完整链路（IMU 原始驱动 + Mahony 姿态解算）
ros2 launch ess_imu_driver2 mahony_launch.py serial_port:=/dev/ttyUSB0
```

### 5. 验证运行状态

```bash
# 查看原始 IMU 数据
ros2 topic echo /epson_imu/data_raw

# 查看 Mahony AHRS 姿态数据（含四元数）
ros2 topic echo /epson_imu/ahrs
```

---

## 启动模式说明

本工作区提供 **4 种启动模式**：

| 启动文件 | 功能 | 输出 Topic |
|----------|------|------------|
| `mahony_launch.py` | **IMU 原始驱动 + Mahony AHRS 姿态解算** ⭐推荐 | `/epson_imu/data_raw` + `/epson_imu/ahrs` |
| `launch.py` | IMU 驱动（含内部四元数+AHRS） | `/imu/data` (remapped) |
| `raw_launch.py` | IMU 驱动（纯原始数据） | `/imu/data_raw` (remapped) |
| `tc_launch.py` | IMU 驱动（含时间戳校正） | `/imu/data` (remapped) |

```bash
# 纯原始数据模式
ros2 launch ess_imu_driver2 raw_launch.py serial_port:=/dev/ttyUSB0

# 仅运行 Mahony AHRS 节点（需已有 /epson_imu/data_raw 源）
ros2 run ess_imu_driver2 mahony_ahrs_node
```

---

## ROS2 Topic 说明

### 输入 Topic（Mahony 订阅）

| Topic | 类型 | 频率 | 说明 |
|-------|------|------|------|
| `/epson_imu/data_raw` | `sensor_msgs/Imu` | 200 Hz | 原始 IMU 数据（陀螺仪 + 加速度计） |

### 输出 Topic（Mahony 发布）

| Topic | 类型 | 频率 | 说明 |
|-------|------|------|------|
| `/epson_imu/ahrs` | `sensor_msgs/Imu` | 200 Hz | Mahony 解算姿态（四元数 + 校准后角速度/加速度） |

### /epson_imu/ahrs 消息内容

| 字段 | 含义 | 单位 |
|------|------|------|
| `orientation` | 姿态四元数 `[w, x, y, z]` | — |
| `angular_velocity` | 校准后角速度 | rad/s |
| `linear_acceleration` | 校准后加速度 | m/s² |

---

## Mahony AHRS 工作流程

```
┌──────────────────────────────────────────────────────────────┐
│                    Mahony AHRS 状态机                         │
├───────────┬──────────┬──────────┬────────────────────────────┤
│ CALIBRATING│ INIT_ACC │  WARMUP  │          RUNNING            │
│ (500样本)  │ (200样本) │ (300样本) │     (正常发布姿态数据)        │
├───────────┼──────────┼──────────┼────────────────────────────┤
│ 采集陀螺仪│ 采集加速度│ 预热滤波器│  实时发布四元数 + 欧拉角日志    │
│ 零偏平均值│ 计算初始  │ 稳定收敛  │                            │
│           │ roll/pitch│          │                            │
└───────────┴──────────┴──────────┴────────────────────────────┘
```

示例运行日志：
```
[INFO] Gyro bias [deg/s]: -0.4163, 0.0513, -0.2826  (n=500)
[INFO] Acc init mean [mg]: 101.2, 161.3, -989.1  (norm=1.007 g)
[INFO] Initial attitude: roll=-9.26  pitch=5.77  yaw=0.00 deg
[INFO] Warmup complete. Attitude: roll=-9.26  pitch=5.78  yaw=0.01 deg
[INFO] roll=-9.25 pitch=5.77 yaw=0.03 | acc_norm=1.007g used=1
```

---

## 可配置参数

### IMU 驱动参数（mahony_launch.py）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `serial_port` | `/dev/ttyUSB0` | 串口设备路径 |
| `baud_rate` | `460800` | 波特率（可选：230400, 921600） |
| `frame_id` | `imu_link` | TF 坐标系 ID |
| `imu_dout_rate` | `9` | 输出频率（9=200Hz, 8=400Hz, 4=125Hz） |
| `imu_filter_sel` | `2` | 滤波器设置（2=TAP4 移动平均） |

### Mahony AHRS 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `mahony_kp` | `1.0` | Mahony 比例增益（越大收敛越快，越容易震荡） |
| `mahony_ki` | `0.005` | Mahony 积分增益（消除陀螺仪长期漂移） |
| `acc_norm_min_g` | `0.85` | 加速度修正最小阈值 [g] |
| `acc_norm_max_g` | `1.15` | 加速度修正最大阈值 [g] |
| `calib_samples` | `500` | 陀螺仪零偏标定样本数 |
| `init_samples` | `200` | 初始加速度平均样本数 |
| `warmup_samples` | `300` | 滤波器预热样本数 |

### 自定义参数启动示例

```bash
ros2 launch ess_imu_driver2 mahony_launch.py \
  serial_port:=/dev/ttyUSB0 \
  mahony_kp:=2.0 \
  mahony_ki:=0.01 \
  imu_dout_rate:=8 \
  calib_samples:=1000
```

---

## 串口权限配置

### 检查 USB 串口设备

```bash
ls -la /dev/ttyUSB*
lsusb | grep -i serial
dmesg | grep -i tty
```

### 永久权限方案

已创建 `/etc/udev/rules.d/99-ch340-ttyusb.rules`，所有 CH340 设备插入后自动设为 `0666`（所有用户可读写），无需手动配置。

---

## 常见问题

### Q: 启动报 `resource temporarily unavailable`？
**A:** 串口已被其他进程占用。检查：
```bash
sudo lsof /dev/ttyUSB0
sudo fuser -k /dev/ttyUSB0
```

### Q: 启动报 `parameter has invalid type`？
**A:** ROS2 Humble 对参数类型严格校验。已修正 `mahony_launch.py` 中的 bool/int 类型匹配。如报其他 launch 文件，手动将 `quaternion_output_en` 设为 `0`（int），`output_32bit_en` 设为 `True`（bool）。

### Q: Mahony 节点一直卡在 CALIBRATING？
**A:** 没有收到 `/epson_imu/data_raw` 数据。检查 IMU 驱动节点是否正常发布数据。

### Q: 如何降低 USB 串口延迟？
**A:** 
```bash
# 检查当前延迟
cat /sys/bus/usb-serial/devices/ttyUSB0/latency_timer

# 设为最低延迟（1ms）
echo 1 | sudo tee /sys/bus/usb-serial/devices/ttyUSB0/latency_timer
```

---

## 项目结构

```
ros2_ws/
├── README.md                          # ← 本文件
├── src/
│   ├── ess_imu_driver2/               # Epson IMU ROS2 驱动包
│   │   ├── CMakeLists.txt
│   │   ├── package.xml
│   │   ├── launch/
│   │   │   ├── mahony_launch.py       # IMU + Mahony AHRS (推荐)
│   │   │   ├── launch.py              # 标准 IMU 驱动
│   │   │   ├── raw_launch.py          # 纯原始数据
│   │   │   └── tc_launch.py           # 带时间戳校正
│   │   └── src/
│   │       ├── mahony_ahrs_node.cpp   # Mahony AHRS ROS2 节点
│   │       ├── mahony.cpp/mahony.h    # Mahony 算法核心实现
│   │       ├── epson_imu_uart_ros2_node.cpp  # IMU UART 驱动节点
│   │       └── ...                    # 底层 C 驱动库
│   └── G354_Attitude-algorithm/       # 参考实现（独立 C++/Python）
└── install/                           # 构建产物
```

## 参考

- [Epson IMU ROS2 Driver](https://github.com/cubicleguy/ess_imu_driver2)
- [Epson IMU Linux C Driver](https://github.com/cubicleguy/imu_linux_example)
- [ROS2 Humble Documentation](https://docs.ros.org/en/humble/)
- Mahony, R., et al. "Nonlinear Complementary Filters on SO(3)." 2005.
