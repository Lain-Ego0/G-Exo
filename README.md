# G-Exo

Physical AI 黑客松作品预研发仓库 — Ghost-Exoskeleton

> 🦾 消费级四自由度主动式下肢外骨骼 · 6S LiPo 双电热插拔 · 户外徒步助力

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
│   ├── G-Exo V1/            # V1 机械设计（SolidWorks）
│   ├── G-Exo V2/            # V2 机械设计（碳纤维 + 3D 打印）
│   ├── G-exo_URDF/          # ROS URDF 仿真模型 + STL 网格
│   └── vector/              # 参考 CAD 文件
├── 2.software/              # 软件入口（IMU 驱动参考）
├── 3.paper/                 # 参考论文
│   ├── Task-agnostic exoskeleton control via biological joint moment estimation.pdf
│   ├── Task-agnostic exoskeleton control via biological joint moment estimation-中文翻译与注释.md
│   └── 基于运动预测的髋关节外骨骼实时助力控制.pdf
├── 4.document/              # 硬件文档与数据手册
│   ├── DM-J4340-2EC/        # 原候选电机（已放弃）
│   ├── RS02/                # 当前选型 RS02 手册
│   ├── RS06/                # 备选 RS06 手册
│   ├── K3 260com kit/       # K3 COM 套件文档
│   └── K3 Pico-ITX/         # K3 Pico-ITX 文档
└── specs/                   # 项目规划文档
    ├── 论文复现方案-Nature2024.md
    └── 进迭时空赞助申请-项目策划书.md
```

> 远端分支 `origin/sanholy` 包含 RL 训练框架（MyoSuite + MuJoCo + PPO）和 V2 硬件完整设计。
> 远端分支 `origin/ROS2_IMU_WJH` 包含 ROS2 IMU 驱动 + Mahony AHRS 姿态解算。
