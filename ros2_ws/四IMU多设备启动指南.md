# 四个 IMU 同时启动指南 (CH343 USB 转串口)

## 背景

四个 Epson IMU 都通过 CH343 USB 转串口接入同一台电脑。默认情况下 Linux 会
按插入顺序分配 `/dev/ttyUSB0 ~ /dev/ttyUSB3`，**插拔或重启后顺序可能变化**，
导致 IMU 与设备节点对应关系漂移。

本方案解决两个问题:
1. **固定设备名**: udev 规则把每个 USB 端口绑定为 `/dev/imu0 ~ /dev/imu3`
2. **独立话题与设备名**: 一个 launch 同时启动 4 个节点，话题/设备名各自独立

## 一、固定设备名 (udev 规则)

```bash
cd ~/G-Exo/ros2_ws/src/ess_imu_driver2/tools
sudo bash setup_imu_udev.sh
```

> ⚠️ **前提**: 先把四个 IMU 全部插入电脑(顺序任意)

脚本会:
1. 扫描所有 CH343 设备 (`/dev/ttyUSB*`)
2. 按 **USB 物理端口路径** 排序，生成 `/etc/udev/rules.d/99-imu.rules`
3. 打印对应关系: `/dev/imuX <-> USB端口`
4. 自动重新加载规则

**请核对打印的对应关系**，确认哪个物理 USB 口对应 `/dev/imu0`。
如果想调整顺序，直接编辑 `/etc/udev/rules.d/99-imu.rules` 后执行:

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

验证:

```bash
ls -l /dev/imu*
```

## 二、启动四个 IMU

```bash
cd ~/G-Exo/ros2_ws
source install/setup.bash
ros2 launch ess_imu_driver2 imu4_launch.py
```

### 话题与设备名对照

| 设备节点 | 节点名 | 话题 | frame_id |
|----------|--------|------|----------|
| /dev/imu0 | imu0_node | /imu0/data, /imu0/data_raw, /imu0/tempc | imu0_link |
| /dev/imu1 | imu1_node | /imu1/data, /imu1/data_raw, /imu1/tempc | imu1_link |
| /dev/imu2 | imu2_node | /imu2/data, /imu2/data_raw, /imu2/tempc | imu2_link |
| /dev/imu3 | imu3_node | /imu3/data, /imu3/data_raw, /imu3/tempc | imu3_link |

### 自定义设备名 (按物理位置命名)

```bash
ros2 launch ess_imu_driver2 imu4_launch.py \
    imu0_name:=imu_front imu1_name:=imu_rear \
    imu2_name:=imu_left imu3_name:=imu_right
```

话题变为 `/imu_front/data`、`/imu_rear/data` ...，frame_id 变为
`imu_front_link` 等。也可用 `imu0_port:=/dev/ttyUSB0` 临时指定串口
(不配 udev 时用)。

### 四 IMU + Mahony 姿态解算

```bash
ros2 launch ess_imu_driver2 imu4_mahony_launch.py
```

每个 IMU 增加一个 mahony 节点，发布 `/imuX/ahrs` 姿态话题。

## 三、验证

```bash
# 查看所有话题
ros2 topic list | grep imu

# 查看某个 IMU 数据 (有输出即正常)
ros2 topic echo /imu0/data_raw --once
ros2 topic echo /imu1/data_raw --once
ros2 topic echo /imu2/data_raw --once
ros2 topic echo /imu3/data_raw --once

# 查看节点
ros2 node list
```

## 四、常见问题

| 问题 | 原因 / 解决 |
|------|-------------|
| 启动报错 `Failed to open serial port` | `/dev/imuX` 不存在，先运行 setup_imu_udev.sh |
| 权限不足 `Permission denied` | 规则中已含 `MODE="0666"`，重新插拔设备 |
| 四个设备只有部分有数据 | 确认每个 IMU 供电正常、波特率一致 |
| 想换 USB 口 | 重新运行 setup_imu_udev.sh 或在规则文件中调整 |

## 五、自动检测模式 (推荐)

不需要手动指定数量, 插入几个 IMU 就自动启动几个节点、生成几个话题:

```bash
ros2 launch ess_imu_driver2 imu_auto_launch.py
```

- 每 1 秒扫描 `/dev/ttyUSB*`, 按路径排序编号: `imu0, imu1, imu2 ...`
- 插入新 IMU → 自动启动驱动节点 + 生成 `/imuN/data_raw` 等话题
- 拔出 IMU → 自动停止对应节点
- 驱动进程异常退出 → 自动重启
- 只识别 CH343 (VID=1a86) 防止误认其他串口设备:

```bash
ros2 launch ess_imu_driver2 imu_auto_launch.py filter_vid:=1a86
```

日志示例:
```
[imu_auto_detect] + 检测到 /dev/ttyUSB0 -> 节点 imu0_node, 话题 /imu0/data_raw 等, frame imu0_link
[imu_auto_detect] 当前 2 个 IMU 在线 | 话题: /imu0/data_raw /imu1/data_raw
[imu_auto_detect] - 移除 /dev/ttyUSB0 (节点 imu0_node)
```

> 提示: 自动模式直接使用 `/dev/ttyUSB*` 编号, 如果想固定"哪个物理 USB 口 = 哪个 imu", 
> 仍建议先运行 `setup_imu_udev.sh` 生成 udev 规则, 然后:
> `ros2 launch ess_imu_driver2 imu_auto_launch.py device_glob:='/dev/imu*'`
