# G-Exo 软件栈

> 本目录为软件入口。实际代码分布在各远端分支中。

---

## 软件架构概览

```
┌─────────────────────────────────────────────┐
│              仿真与训练（sanholy 分支）        │
│  RL/                                        │
│  ├─ env/          Gymnasium 环境            │
│  ├─ runners/      训练/评估/回放             │
│  ├─ assets/       模型/数据集/映射           │
│  └─ outputs/      训练产出                   │
├─────────────────────────────────────────────┤
│            传感器驱动（ROS2_IMU_WJH 分支）    │
│  ros2_ws/                                   │
│  └─ src/ess_imu_driver2/  Epson G354 驱动   │
│       ├─ IMU UART 底层驱动 (200Hz)           │
│       └─ Mahony AHRS 姿态解算                │
├─────────────────────────────────────────────┤
│          实机部署（主分支，开发中）            │
│  ├─ 控制主循环 (C++17, RT Linux, 50-200Hz)   │
│  ├─ CAN 通信 (SocketCAN + MIT 协议)          │
│  └─ NPU 推理 (TCN ONNX → RKNN)              │
└─────────────────────────────────────────────┘
```

---

## 远端分支内容

### `origin/sanholy` — RL 训练框架

包含完整的强化学习训练流水线：

| 模块 | 路径 | 功能 |
|------|------|------|
| 环境 | `RL/env/gexo_env.py` | Gymnasium 外骨骼环境，4 关节力矩动作空间 |
| 传感器 | `RL/env/sensors.py` | 虚拟 IMU + 编码器，含噪声/偏置/延迟仿真 |
| 力矩执行器 | `RL/env/torque.py` | 归一化动作 → 物理力矩（限幅/速率限制/低通滤波） |
| 奖励函数 | `RL/env/reward.py` | 运动跟踪 + 人体努力最小化 + 功率惩罚 + 平滑度 |
| 人体模型 | `RL/env/myosuite/` | MyoSuite 80 肌肉人体 + 轻量肌肉协同控制器 |
| 训练 | `RL/train.py` | PPO (Stable-Baselines3)，支持多进程向量化 |
| 设计文档 | `RL/frame.md` | 完整架构设计（数据流/接口/里程碑） |

**训练数据流**：
```
MyoSuite 人体动力学 (1ms)
  → 轻量肌肉协同控制层 (100Hz)
  → 虚拟传感器 (IMU+编码器, 200Hz)
  → 观测历史窗口 (4帧PPO基线 / 44-50帧TCN)
  → PPO策略网络 (50Hz)
  → 四关节力矩 → qfrc_applied
  → 奖励计算 → TensorBoard
```

**PPO 参数**：
- 学习率: 1e-4
- 网络: MLP [128, 64] (Actor/Critic 独立)
- n_steps: 1024, batch_size: 128, epochs: 10
- 总训练步数: 2,000,000

### `origin/ROS2_IMU_WJH` — IMU 驱动与姿态解算

| 组件 | 说明 |
|------|------|
| IMU 驱动 | Epson G354PDH0，通过 CH340 USB-UART，200Hz 原始数据 |
| Mahony AHRS | 互补滤波姿态解算，四元数输出，含陀螺仪零偏自动标定 |
| 启动模式 | 4 种（Mahony+原始 / 标准 / 纯原始 / 时间戳校正） |
| ROS2 接口 | `/epson_imu/data_raw` (sensor_msgs/Imu) → `/epson_imu/ahrs` |

**Mahony AHRS 状态机**：
```
CALIBRATING (500样本) → INIT_ACC (200样本) → WARMUP (300样本) → RUNNING
```

详细文档见远端分支 `ros2_ws/epson_mahony_README.md`。

---

## 参考链接

- [ess_imu_driver2 (ROS2)](https://github.com/cubicleguy/ess_imu_driver2)
- [Epson IMU Linux C Driver](https://github.com/cubicleguy/imu_linux_example)
- [MyoSuite](https://github.com/facebookresearch/myosuite)
- [Stable-Baselines3](https://github.com/DLR-RM/stable-baselines3)
- [Molinaro et al., Nature 2024](https://doi.org/10.1038/s41586-024-08157-7)
