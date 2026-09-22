# G-Exo 软件栈

> 项目总览（英文）：[../README.md](../README.md) · 中文说明：[../README_zh.md](../README_zh.md)
>
> 本目录为软件入口。RL 训练框架已在主分支（[`RL/`](../RL/)），
> IMU 驱动与实机部署代码分布在各远端分支。

---

## 软件架构概览

```
┌─────────────────────────────────────────────┐
│         仿真与训练（主分支 RL/）               │
│  RL/                                        │
│  ├─ env/          Kinesis / MyoSuite 环境    │
│  ├─ runners/      训练/评估/回放/标定         │
│  ├─ assets/       TCN 标定/模型/数据清单      │
│  └─ output/       训练与演示产物              │
├─────────────────────────────────────────────┤
│        传感器驱动（ROS2_IMU_WJH 分支）         │
│  imu_driver/                                │
│  ├─ ess_imu_driver2/      Epson G354 驱动    │
│  └─ G354_Attitude-algorithm/  Mahony AHRS    │
│       ├─ IMU UART 底层驱动 (200Hz)            │
│       └─ 姿态解算（四元数 + 陀螺零偏标定）      │
├─────────────────────────────────────────────┤
│     板载应用（主分支 2.software/gexo_web_agent）│
│  ├─ FastAPI + WebSocket + 本地 LLM           │
│  ├─ React Cockpit（SENSE / REASON / ACT）     │
│  └─ 安全校验层（独立于提示词）                 │
├─────────────────────────────────────────────┤
│        实机部署（integrate/local-workspace）   │
│  ├─ control/      控制主循环 + 电机 MIT 协议   │
│  └─ RL/deploy/    K3 板载部署与 TCN PD 链路    │
└─────────────────────────────────────────────┘
```

---

## 主分支内容

### `RL/` — 强化学习训练框架

完整训练流水线，覆盖 TCN 时序编码 + PPO 策略 + MuJoCo/MyoSuite 物理验证：

| 模块 | 路径 | 功能 |
|------|------|------|
| 环境 | `RL/env/kinesis/` | Kinesis 外骨骼环境，4 关节力矩动作空间 |
| 人体模型 | `RL/env/myoassist/`、`RL/env/myosuite/` | MyoSuite 80 肌肉人体 + 肌肉协同控制器 |
| 传感器 | `RL/env/sensors.py` | 虚拟 IMU + 编码器，含噪声/偏置/延迟仿真 |
| 力矩执行器 | `RL/env/torque.py` | 归一化动作 → 物理力矩（限幅/速率限制/低通滤波） |
| TCN 预测器 | `RL/runners/predictors/` | 因果 TCN，预测未来 100/200ms 角度、角速度、生物关节力矩 |
| 训练 | `RL/runners/train_kinesis_exo.py` | PPO（Stable-Baselines3），8 并行环境 |
| 评估 | `RL/runners/evaluate_kinesis_exo.py` | 同状态零助力/有助力配对评估 |

**训练数据流**：
```
MyoSuite 人体动力学 (1ms)
  → 轻量肌肉协同控制层 (100Hz)
  → 虚拟传感器 (IMU+编码器, 200Hz)
  → 观测历史窗口 (50 帧 / 1s)
  → 显式 TCN 预测 (16 维) → 160 维观测
  → PPO 策略网络 (50Hz) → 4 维归一化动作
  → 力矩限速/限幅 → qfrc_applied → 同状态零助力配对
  → Reward / TensorBoard / checkpoint
```

**PPO 参数（当前生效值）**：学习率 1e-4 · Actor/Critic MLP [128, 64] · rollout 512/env ·
8 并行环境 · batch 256 · epochs 5 · gamma 0.99 · GAE 0.95 · clip 0.2 · log_std_init −2.0 ·
动作尺度 ±6 Nm · 1M transitions。

详细命令见 [`RL/KINESIS_EXO_TRAINING.md`](../RL/KINESIS_EXO_TRAINING.md) 与
[`RL/KINESIS_EXO_EVALUATION.md`](../RL/KINESIS_EXO_EVALUATION.md)。

### `gexo_web_agent/` — 板载 Web Agent

当前生产入口是**只读 IMU 遥测**（直接订阅四路 `/A*_ahrs`、`/B*_ahrs`，不依赖控制桥、
不用 mock 值填充关节/扭矩/温度/电池/CAN 状态）。另含非生产默认的旧控制桥（LLM 意图
解析 + 安全校验 + ROS 2 Topic），以及中英双语产品官网 `website/`。

详见 [`gexo_web_agent/README.md`](gexo_web_agent/README.md)。

### `voice_tools/` — 语音控制测试脚本

`omni_agent_启动流程.md`、`voice_control.sh`、`speed_controller.py`、`cmd_vel_monitor.py`
等，用于语音链路联调。

### `alloop/` — Alloop 套件使用范围说明

套件的 Dart 源码与 AAR 二进制因第三方受限许可**未随仓库分发**，本目录只提供许可范围
说明。详见 [`alloop/README.md`](alloop/README.md)。

---

## 远端分支内容

### `origin/integrate/local-workspace` — 实机控制与部署

| 路径 | 内容 |
|------|------|
| `control/deploy/`、`control/motor/` | 实机控制主循环、CAN 通信（SocketCAN + MIT 协议） |
| `RL/deploy/`、`RL/deploy_tcn_pd/` | K3 板载部署、TCN + PD 控制链路 |
| `RL/evidence/` | 实机验证证据与记录 |

> 该分支同时包含 `2.software/gexo_web_agent` 与 `RL/` 的完整快照，以及合并前的旧版
> 机械设计目录（`1.hardware/G-Exo V1~V4`）。机械设计以主分支 [`1.hardware/G-exo/`](../1.hardware/G-exo/) 为准。

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

启动流程见主分支 [`imu_driver/启动流程.md`](imu_driver/启动流程.md) 与
[`imu_driver/四IMU多设备启动指南.md`](imu_driver/四IMU多设备启动指南.md)。

> ⚠️ `imu_driver/ess_imu_driver2` 与 `imu_driver/G354_Attitude-algorithm` 在 git 中记为
> commit 对象（submodule 引用），但仓库内没有 `.gitmodules`，全新 clone 无法直接检出
> 这两个目录。

---

## 参考链接

- [ess_imu_driver2 (ROS2)](https://github.com/cubicleguy/ess_imu_driver2)
- [Epson IMU Linux C Driver](https://github.com/cubicleguy/imu_linux_example)
- [MyoSuite](https://github.com/facebookresearch/myosuite)
- [Stable-Baselines3](https://github.com/DLR-RM/stable-baselines3)
- [Molinaro et al., Nature 2024](https://doi.org/10.1038/s41586-024-08157-7)
