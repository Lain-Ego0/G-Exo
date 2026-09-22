# G-Exo

Physical AI 黑客松参赛作品 — Ghost-Exoskeleton

> 🏆 **香港首届 Physical AI Hackathon 2026 · alloop 赛道冠军**（2026-08-05 · 香港科学园）
>
> 🦾 消费级四自由度主动式下肢外骨骼 · 6S LiPo 锂电 · 户外徒步助力
>
> **把助力，交还给身体决定** — SENSE THE BODY · DECIDE THE ASSIST

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 赛果

| 项目 | 内容 |
|------|------|
| 赛事 | 香港首届 Physical AI Hackathon 2026（进迭时空 SpacemiT × Brizan Ventures × alloop.ai 发起） |
| 决赛 | 2026-08-05 · 香港科学园高锟会议中心，37 支队伍 / 160+ 开发者入围 |
| 成绩 | **alloop 赛道冠军** |
| 参赛作品 | G-Exo（Ghost-Exoskeleton）— 四自由度主动式下肢外骨骼 + Alloop Ring 生理状态闭环 |
| 团队 | AAA G-Exo批发专业团队（5 人：系统架构 / 运动控制 / SLAM / 强化学习 / 嵌入式 / 全栈） |

**赛题呼应**：alloop 赛道的命题是把戒指采集的睡眠、HRV、活动等数据真正转化为"人现在怎么样"的判断与主动支持，而不是停留在数据显示层面。G-Exo 的答案是——**戒指理解人的状态，外骨骼理解人的动作，Physical AI 把这两件事闭环到人的身体上**。

- 演示视频：[在 Physical AI 黑客松我们做了一个四自由度强化学习外骨骼！赛道冠军！](https://www.bilibili.com/video/BV1uuu36uEjx/)（B站）
- 赛事报道：[香港首届 Physical AI Hackathon 圆满落幕](https://www.elecfans.com/d/8207944.html)

---

## 项目状态

| 阶段 | 状态 | 日期 |
|------|------|------|
| 产品定位 Q&A | ✅ 5 轮收敛完成（见 [Q&A.md](Q&A.md)） | 2026-06-28 |
| BOM | ✅ [V2.2 RS02 准直驱方案](1.hardware/BOM.md)（~¥4,611） | 2026-07-30 |
| 关节模组采购 | ✅ RobStride RS02 ×5 已采购（学生 9 折） | 2026-07-30 |
| 机械设计 | ✅ G-exo 单一版本定版（SolidWorks 装配体 + URDF + STL） | 2026-08 |
| 样机组装 | ✅ 打印件加工完成、碳纤维件外发加工、整机装配跑通 | 2026-08 |
| IMU 驱动 | ✅ ROS2 + Mahony AHRS，4 路 G354 200Hz 调通 | 2026-07-23 |
| RL 训练框架 | ✅ Kinesis PPO + TCN 时序编码（训练期 160 维观测 / 4 维动作 / 1M transitions） | 2026-08-09 |
| 仿真助力验证 | ✅ MuJoCo + MyoSuite A/B 对照 Demo（零助力 vs 有助力，同种子） | 2026-07-27 |
| 实机部署 | ✅ K3 Pico-ITX / CoM260 上的 Web Agent、LLM、遥测链路实机核验 | 2026-08-02 |
| Alloop Ring 闭环 | ✅ 戒指 BLE → Android App（AlloopCore SDK）→ WebSocket 桥 → 系统，实机跑通 | 2026-08 |
| 产品官网 | ✅ 中英双语站点（`gexo_web_agent/website`） | 2026-08 |
| 实机控制指标对标 | 🚧 待补齐（见[已知缺口](#已知缺口与口径说明)） | — |

---

## 核心参数一览

- **自由度**：4 主动（髋屈伸×2 + 膝屈伸×2）+ 2 被动（冠状面外展/内收）
- **重量**：≤4kg（不含电池）
- **执行器**：RobStride RS02 准直驱 QDD ×4（7.75:1 低减速比，额定 6 Nm / 峰值 17 Nm，CAN + MIT 力矩模式，Φ58mm / 405g）
- **传感器**：4× Epson G354 车规级 IMU（大腿×2 + 小腿×2）+ 4× 14-bit 绝对值磁编码器
- **供电**：6S 5000mAh LiPo（22.2V 标称 / ≈111Wh）**单电池 + BMS**，整机功率 30–100W，待机功耗 ~10W（待机续航约 11h）
- **BOM**：~¥4,611（目标 ≤¥5,000）
- **计算平台**：进迭时空 K3（RISC-V）— NPU（TCN INT8 推理 <5ms）+ 多核 CPU + RT Linux
- **控制**：RL + TCN 时序编码器混合架构，任务无关（无需任务分类器 / 步态相位检测）
  - 理论框架参考 [Molinaro et al., Nature 2024](https://doi.org/10.1038/s41586-024-08157-7) 任务无关控制范式
  - 仿真训练：MyoSuite 80 肌肉人体 + MuJoCo 物理引擎 + PPO（Stable-Baselines3）
  - 实机部署：TCN INT8 → K3 NPU 推理 → RT Linux 50Hz 实时闭环 → CAN MIT 力矩指令
- **两种人机交互模式**
  - **Adaptive Assist 助力模式**：疲劳 / 长距离徒步 / 登山 / 慢跑时，髋膝协同输出辅助力矩；助力比例全局统一调节 30%–100%，步进 10%
  - **Damping 阻尼训练模式**：恢复良好、目标为训练时，电机转阻尼/保护状态提供阻力，让你主动发力（零额外控制模型成本）
- **场景**：户外徒步（主）+ 慢跑 / 爬山 / 上下楼梯

详细参数见 [Q&A.md](Q&A.md) 与 [BOM V2.2](1.hardware/BOM.md)。

---

## 系统架构

```
┌──────────────── 感知：两个时间尺度 ────────────────┐
│ Alloop Ring   HR / HRV / SpO2 / 活动量 + 14 天基线   │  → 你今天的身体状态怎么样
│ 戒指 BLE → Android App → WebSocket 桥（已实机跑通）  │
│                                                     │
│ G-Exo 本体    4×IMU + 4×编码器 @200Hz               │  → 你下一步想怎么动
│ 迈腿 / 蹬地 / 屈膝 时序判断                          │
└─────────────────────────┬───────────────────────────┘
                          ▼
              AI 决策：状态 × 意图 → 协同策略
        恢复不足 + 长距离徒步 → Adaptive Assist ↑助力
        恢复良好 + 力量训练   → Damping 转为训练伙伴
                          ▼
┌──────────────── 控制：任务无关 RL ─────────────────┐
│ 36 维/帧 × 200Hz 传感器时序                          │
│   → TCN 时序编码器（5 层膨胀卷积，NPU INT8 量化）     │
│   → 共享隐空间表征                                  │
│   → PPO 策略网络（MLP 128-64）→ 4 维归一化力矩 ∈[-1,1]│
│   → 力矩缩放 → 变化率限幅 → 一阶低通滤波 → CAN → RS02 │
│   控制周期 50Hz · TCN INT8 推理 <5ms                │
└─────────────────────────────────────────────────────┘
```

> 训练期（Kinesis）观测为 160 维 = 144 维传感器历史 + 16 维显式 TCN 预测；
> 部署期按上图的共享隐空间接口，见 [`RL/KINESIS_EXO_TRAINING.md`](RL/KINESIS_EXO_TRAINING.md) 与
> [`RL/TCN_PIPELINE.md`](RL/TCN_PIPELINE.md)。

**Sim-to-Real 训练管线**

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1 | TCN 监督预训练（动捕数据 + OpenSim 逆动力学标签），预测未来 100/200ms 髋膝角度、角速度、生物关节力矩 | ✅ 九条留出 episode 上 200ms TCN 优于均值/恒速基线 |
| Phase 2 | PPO 策略训练（MyoSuite 80 肌肉人体 + MuJoCo），奖励 = 同状态零助力对照的肌群激活下降 + 力矩负担单边约束 + 平衡/安全 gate | ✅ 1M transitions，8 并行环境，动作尺度 ±6 Nm |
| Phase 3 | K3 部署 → 实机调优 | ✅ K3 链路实机核验 |

评测口径与训练/评估命令见 [`RL/TCN_PIPELINE.md`](RL/TCN_PIPELINE.md)、[`RL/KINESIS_EXO_TRAINING.md`](RL/KINESIS_EXO_TRAINING.md)、[`RL/KINESIS_EXO_EVALUATION.md`](RL/KINESIS_EXO_EVALUATION.md)。

---

## LLM 对话式安全操作接口

穿着外骨骼低头操作手机不便，预设档位又感知不到实时状态——所以入口做成一句自然语言：

浏览器（React Cockpit）→ FastAPI（意图解析 + 安全校验）→ ROS2 Topic → 控制节点。

- LLM 只解析意图，**从不直接控制电机**；只开放 4 个意图：`query_status` / `set_mode` / `adjust_assist` / `document_qa`
- 本地推理：llama.cpp + Qwen3.5-0.8B（INT4），模型与对话数据不出设备，断网可用
- 安全设计（独立于提示词）：参数限幅 K∈[0.3, 1.0] 且单次步进 ±0.1 · 仅站立静止可切模式 · 急停最高优先级且独立于 LLM 链路 · 关键指令二次确认 · 超时即失败不自动重试 · 读写分离
- 附加：RAG 操作教程问答（jieba + FTS5 + BM25）、WebSocket 实时状态推送（状态失联 1s 判定）

架构细节见 [`2.software/gexo_web_agent/README.md`](2.software/gexo_web_agent/README.md)。

---

## 目录结构

```
G-Exo/
├── README.md                # 项目总览（本文件）
├── Q&A.md                   # 5 轮产品定位 Q&A 全记录
├── ppt.md                   # 决赛答辩稿（完整版 13 页 + 8 页精简版）
├── frontend_design.md       # Cockpit 前端设计
├── main_visual_optimization.md  # 主视觉优化说明
├── 1.hardware/              # 硬件设计
│   ├── BOM.md               # 物料清单 V2.2（~¥4,611）
│   ├── G-exo/               # 机械设计定版（SolidWorks 装配体 + 零件 + 标准件库）
│   └── G-exo_URDF/          # ROS URDF 仿真模型 + STL 网格
├── 2.software/              # 软件
│   ├── imu_driver/          # 4 路 G354 IMU + Mahony AHRS（ROS2，200Hz）
│   ├── gexo_web_agent/      # 板载 Web Agent（FastAPI + WebSocket + 本地 LLM + React Cockpit + 产品官网）
│   ├── voice_tools/         # 语音控制测试脚本
│   └── alloop/              # Alloop 套件使用范围说明（套件代码因受限许可未入库）
├── RL/                      # 强化学习训练框架（Kinesis PPO + TCN）
│   ├── env/                 # Kinesis / MyoSuite 环境、传感器、力矩执行器、奖励
│   ├── runners/             # 训练 / 评估 / 回放 / 标定入口
│   ├── assets/              # TCN 标定、MyoSuite 模型、数据集清单
│   └── output/              # 训练与演示产物（demo_7_27 等）
├── 3.paper/                 # 参考论文
├── 4.document/              # 硬件文档（K3 260com kit / RS02 手册）
└── deploy/k3/               # K3 板载部署说明（SpaceMIT 机器人 SDK 获取方式）
```

> `RL/` 的训练产物目录（`RL/outputs/`、`RL/papers/`）与 Alloop 套件、K3 SDK 均因体积或第三方许可**不随仓库分发**，见 [.gitignore](.gitignore)。

---

## 已知缺口与口径说明

本项目在 48 小时赛期内完成，仓库如实记录完成度，避免把仿真结论说成实机结论：

- **仿真 ≠ 实机生理结论**：`RL/output/` 中的助力验证是在 MuJoCo + MyoSuite 上、以 55% 肌力构造的可重复功能测试条件，尚未标定 URDF 零位与真实电机工作包络，**不构成对真实人体代谢消耗或医疗效果的结论**。
- **曾用的 oracle 助力控制器使用了仿真特权量**（直接读取上一步肌肉广义力矩），仅作为物理接口与上限基线，**不可部署**；部署路径为 TCN 估计 → PPO Actor。
- **电源方案以答辩稿为准**：本文档与 `ppt.md` 采用**最终定版**的「6S 5000mAh 单电池 + BMS」；
  [`BOM.md`](1.hardware/BOM.md) 仍停留在较早的「6S 3000mAh ×2 热插拔」，尚未回改。
- **实机控制指标待补齐**：额定力矩 6 Nm 的超越比例、省力比例等实机对标数据尚未归档到仓库。
- **`2.software/imu_driver/` 下的两个驱动目录是游离 submodule 引用**（`ess_imu_driver2`、`G354_Attitude-algorithm` 在 git 中记为 commit 对象，但仓库无 `.gitmodules`），全新 clone 无法直接检出。

---

## 许可证

- 项目代码（自有部分）以 [MIT License](LICENSE) 发布。
- 仓库内第三方组件、厂商资料与论文的版权归属见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
- Alloop 套件代码因第三方受限许可**未包含在公开仓库中**（本地保留）；其使用范围
  （仅授权黑客松参赛者在本次赛事期间及参赛作品范围内使用，未经书面许可不得再分发）
  见 [2.software/alloop/README.md](2.software/alloop/README.md)。
