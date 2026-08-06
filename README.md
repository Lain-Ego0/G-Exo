# G-Exo

Physical AI 黑客松作品预研发仓库 — Ghost-Exoskeleton

> 🦾 消费级四自由度主动式下肢外骨骼 · 6S LiPo 双电热插拔 · 户外徒步助力

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 项目状态

| 阶段 | 状态 | 日期 |
|------|------|------|
| 产品定位 Q&A | ✅ 5 轮收敛完成 | 2026-06-28 |
| 关键参数草表 | ✅ 已收敛（见 [Q&A Round 5](Q&A.md#round-5--最终收敛-)） | 2026-06-28 |
| BOM | ✅ [V2.0 RS02 准直驱方案](1.hardware/BOM.md) | 2026-07-23 |
| 机械设计 | ✅ V2 完成（SolidWorks 装配体 + URDF） | 2026-07-27 |
| IMU 驱动 | ✅ ROS2 + Mahony AHRS 200Hz 调通 | 2026-07-23 |
| RL 训练框架 | ✅ MyoSuite + MuJoCo + PPO 已搭建 | 2026-07-27 |
| 关节模组采购 | 🔧 待采购 RS02 ×4 | — |
| 样机组装 | 🚧 待采购后启动 | — |

---

## 核心参数一览

- **自由度**：4 主动（髋屈伸×2 + 膝屈伸×2）+ 2 被动（冠状面外展/内收）
- **重量**：≤4kg（不含电池）
- **供电**：6S LiPo（22.2V 标称，25.2V 满电），双电池热插拔轮换
- **续航**：步行 ~1.3h / 双电，跑步 ~50min
- **BOM**：~¥4,611
- **控制**：RL + TCN 时序编码器混合架构（PPO 策略 → 四关节力矩 → CAN → RS02）
  - 理论框架参考 Nature 2024 任务无关控制范式
  - 仿真训练：MyoSuite 80 肌肉人体 + MuJoCo 物理引擎
  - 实机部署：K3 NPU 推理 + RT Linux 实时控制
- **场景**：户外徒步（主）+ 慢跑/爬山

详细参数见 [Q&A Round 5 最终收敛](Q&A.md#round-5--最终收敛-) 和 [BOM V2.0](1.hardware/BOM.md)。

---

## 目录结构

```
G-Exo/
├── README.md                # 项目总览
├── Q&A.md                   # 5 轮产品定位 Q&A 全记录
├── 1.hardware/              # 硬件设计
│   ├── BOM.md               # 物料清单 V2.0
│   ├── G-Exo V1 ~ V4/       # 机械设计迭代（SolidWorks / STEP）
│   ├── G-exo_URDF/          # ROS URDF 仿真模型 + STL 网格
│   └── vector/              # 参考 CAD 文件
├── 2.software/              # 软件
│   ├── imu_driver/          # ROS2 IMU 驱动 + Mahony AHRS（G354 + ess_imu_driver2）
│   ├── gexo_web_agent/      # 板载 Web Agent（FastAPI + WebSocket + LLM + React Cockpit）
│   └── voice_tools/         # 语音控制测试脚本
├── 3.paper/                 # 参考论文
├── 4.document/              # 硬件文档与数据手册
│   ├── RS02/  RS06/         # 执行器数据手册
│   ├── DM-J4340-2EC/        # 原候选电机（已放弃）
│   └── K3 260com kit/  K3 Pico-ITX/   # K3 计算平台文档
└── deploy/k3/               # K3 板载部署说明（SDK 获取方式）
```

## 许可证

- 项目代码（自有部分）以 [MIT License](LICENSE) 发布。
- 仓库内第三方组件、厂商资料与论文的版权归属见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
- Alloop 套件因第三方受限许可未包含在公开仓库中。
