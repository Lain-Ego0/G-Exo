# G-Exo MuJoCo 助力演示计划（2026-07-27）

## 1. 今日目标

在不训练新策略、不录制视频的前提下，交付一个能够直接启动 MuJoCo 窗口的 A/B 演示：

- 人体使用 MyoSuite `myoLegWalk-v0` 的肌肉骨骼模型；
- 人体运动由已下载的 depRL 教师策略驱动；
- 画面中显示 `1.hardware/G-exo_URDF` 提供的 G-Exo STL 外观；
- 使用同一个确定性随机种子分别运行“无助力”和“有助力”；
- 有助力模式通过左右髋、膝四个自由度施加受限辅助力矩；
- 仿真运行时持续打印关键数据，并在结束后保存 CSV 和 JSON；
- 用户直接通过 MuJoCo 窗口观察并自行录屏。

本演示的核心问题是：在相同人体控制器、初始状态和弱肌力条件下，加入受限的 G-Exo 四关节辅助力矩后，人体的存活时间、行走距离和姿态稳定性是否发生可重复的改善。

## 2. 今日模型边界

### 2.1 人体

- 仿真器：MuJoCo 3.6.0；
- 肌肉骨骼模型：MyoSuite 2.12.2 `myoLegWalk-v0`；
- 人体控制：冻结的 depRL 预训练教师；
- 人体肌力：演示时采用可配置的统一缩放，默认保留正常肌力的 55%，用于构造容易观察的助力测试场景；
- MyoSuite 环境步长：10 ms，即 100 Hz；
- MuJoCo 内部积分步长：1 ms。

弱肌力场景只是一个可重复的功能性测试条件，不等同于具体病理人群，也不能据此给出生理或医疗结论。

### 2.2 外骨骼

URDF 来源：

```text
1.hardware/G-exo_URDF/urdf/G-exo.urdf
```

使用的五个刚体网格：

```text
base_link.STL
l_thigh.STL
l_calf.STL
r_thigh.STL
r_calf.STL
```

运动驱动关系：

| G-Exo 部件 | MyoSuite 人体部件 |
| --- | --- |
| `base_link` | `pelvis` |
| `l_thigh` | `femur_l` |
| `l_calf` | `tibia_l` |
| `r_thigh` | `femur_r` |
| `r_calf` | `tibia_r` |

`base_link` 根据人体骨盆位姿整体移动；左右髋膝四个角度驱动 URDF 原有的四个关节。五个 STL 始终按 URDF 关节 origin 和 axis 组成完整机械链，不再拆开贴到人体骨段。

今日版本使用五个 MuJoCo mocap 刚体显示完整 G-Exo 运动学，其质量和惯量不参与人体动力学。四个电机通过人体髋膝自由度上的 `qfrc_applied` 等效力矩发挥作用。

这意味着今日版本能够展示：

- 实际 G-Exo 外形随人体运动；
- URDF 给出的部件、关节 origin、axis、顺序和电机参数进入演示配置；
- 四关节辅助力矩真实参与 MuJoCo 前向动力学；
- 有无助力造成的运动结果差异。

今日版本暂时不能证明：

- 真实绑带柔性、间隙和滑移；
- 外骨骼连杆质量和惯量对人体的反作用；
- 外骨骼关节轴与人体关节轴偏差；
- 独立外骨骼闭链造成的约束力；
- 电机热、电池和底层控制器的完整动态；
- 对真实人体的代谢消耗改善。

以上内容属于后续 V1 人机耦合模型，而不是今日 Demo 的验收条件。

## 3. URDF 接入原则

当前 URDF 的网格路径使用 ROS `package://G-exo/meshes/...` 形式。MuJoCo 3.6 已验证能够识别 URDF 结构，但无法直接解析该资源路径，因此接入层需要：

1. 读取 URDF；
2. 将 `package://G-exo/meshes/` 解析到本项目的实际网格目录；
3. 读取五个 link 的视觉网格和四个 joint 的 origin、axis；
4. 根据人体骨盆位姿和髋膝角实时计算完整 URDF 前向运动学；
5. 为新增几何体设置独立颜色和碰撞组；
6. 默认关闭外骨骼网格碰撞，避免纯可视化刚体参与接触；
7. 启动前检查五个网格、五个 mocap 刚体和四个人体驱动关节。

URDF 四个关节均标注：

- 额定力矩：6 Nm；
- 峰值力矩：17 Nm；
- 最大转速：275 rpm，约 28.8 rad/s；
- URDF 角度范围：约正负 30 度。

今日演示将 17 Nm 视为绝对峰值边界，同时记录超过 6 Nm 额定力矩的时间比例。URDF 关节角范围暂不直接作为人体髋膝硬限位，因为其与人体自然步态范围和装配零位仍未完成标定。

## 4. 助力控制

今日不把临时控制器描述为已训练 Actor。它是用于验证物理接口和建立上限基线的 oracle 助力控制器。

控制器从上一个时刻 MuJoCo 已产生的四关节人体肌肉广义力矩中取值：

$$
\tau_{t,\mathrm{target}}^{\mathrm{exo}}
=
\alpha\tau_{t-1}^{\mathrm{muscle}}
$$

然后经过已有 `TorqueActuator` 的峰值限制和力矩变化率限制：

$$
\tau_t^{\mathrm{exo}}
=
\operatorname{clip}_{[-17,17]}
\left(
\operatorname{rate\_limit}
\left(\tau_{t,\mathrm{target}}^{\mathrm{exo}}\right)
\right)
$$

默认参数：

```text
assist_gain = 0.5
torque_limit = [17, 17, 17, 17] Nm
torque_rate_limit = [600, 600, 600, 600] Nm/s
exo_control_frequency = 50 Hz
```

外骨骼每 20 ms 更新一次命令，并在两个 10 ms MyoSuite step 中保持该命令。

这条控制律使用了仿真特权量，不能部署到实机。后续将按以下数据流替换：

```text
实机可测历史状态
    -> TCN 时序编码器
    -> 未来运动/生物关节力矩估计
    -> PPO Actor
    -> TorqueActuator
    -> 四关节电机力矩
```

## 5. A/B 演示流程

### 5.1 无助力

1. 创建带 G-Exo 外观的 MyoSuite 环境；
2. 设置固定随机种子；
3. 将人体肌力缩放到演示值；
4. 外骨骼四关节力矩保持为零；
5. 启动 MuJoCo 被动查看器；
6. 运行至跌倒或 10 s 时间上限；
7. 保存 `baseline.csv` 和本次摘要。

### 5.2 有助力

1. 重新创建或完全重置同一环境；
2. 使用完全相同的随机种子和肌力参数；
3. 启用 50 Hz oracle 助力；
4. 启动 MuJoCo 被动查看器；
5. 运行至跌倒或 10 s 时间上限；
6. 保存 `assisted.csv` 和本次摘要。

为方便现场展示，运行器同时支持只运行 `baseline`、只运行 `assist` 和按顺序运行 `both`。

## 6. 数据展示

每个仿真 step 至少记录：

- 仿真时间；
- 骨盆/质心高度；
- 前进速度和累计距离；
- 左右髋膝角度与角速度；
- 四关节人体肌肉广义力矩；
- 四关节外骨骼辅助力矩；
- 四关节瞬时机械功率；
- 80 路肌肉 excitation 和 activation 的均值；
- episode 是否结束及结束原因。

汇总 JSON 至少包含：

- 存活时间；
- 前进距离；
- 平均前进速度；
- 最低质心高度；
- 平均肌肉 activation；
- 平均绝对辅助力矩；
- 峰值辅助力矩；
- 超过额定 6 Nm 的时间比例；
- 正向外骨骼机械功率；
- 终止原因。

## 7. 今日验收标准

必须满足：

1. MuJoCo 能编译组合模型；
2. 画面中能够辨认 G-Exo 五个 STL 部件；
3. 外骨骼部件跟随对应人体部位，无明显脱离或爆炸；
4. 无助力和有助力使用相同初始条件；
5. 四路力矩严格不超过 17 Nm；
6. 运行器可打开交互式仿真窗口；
7. 两种模式均输出 CSV；
8. 输出一个包含 A/B 指标的 JSON；
9. 至少一个固定种子下，有助力相对无助力表现出可重复的存活时间或稳定性改善；
10. 演示说明中明确控制器是 oracle 基线，不冒充 TCN 或 PPO 策略。

## 8. 文件安排与复用关系

今日只新增最少文件：

```text
RL/
├── env/myosuite/
│   └── exo_overlay.py       # URDF 解析、网格挂载、组合模型生成
├── runners/
│   └── assist_demo.py       # A/B 仿真、交互渲染、数据记录
└── output/demo_7_27/
    ├── README.md            # 本计划
    ├── generated/           # 生成的组合 MJCF 与资产记录
    └── runs/                # CSV 和 JSON
```

直接复用：

```text
RL/env/myosuite/teacher_controller.py
RL/env/torque.py
1.hardware/G-exo_URDF/urdf/G-exo.urdf
1.hardware/G-exo_URDF/meshes/*.STL
baselines_DEPRL/myoLegWalk_20230514/...
```

暂不经过尚未闭环的 `RL/env/gexo_env.py` 和 `RL/train.py`，避免 Demo 被 PPO worker、Observation 和轻量肌肉层的未完成接口阻塞。

## 9. 实施顺序、工时和剩余工作量

| 阶段 | 产物 | 预计工时 | 完成状态 |
| --- | --- | ---: | --- |
| 0 | URDF、MyoSuite 刚体和 MuJoCo 接口核对 | 0.5 h | 已完成 |
| 1 | 本演示计划与验收口径 | 0.25 h | 已完成 |
| 2 | `exo_overlay.py`：组合模型和 G-Exo 外观 | 1.0～1.5 h | 已完成 |
| 3 | `assist_demo.py`：A/B 运行、50 Hz 助力和数据记录 | 1.0～1.5 h | 待完成 |
| 4 | MuJoCo 交互渲染、相机和同种子复现检查 | 0.5 h | 待完成 |
| 5 | 指标核验、演示命令和现场参数固定 | 0.5 h | 待完成 |

当前剩余：3 个实施阶段，预计 2～2.5 小时。组合模型已通过编译、磁盘重载、MyoSuite 单步、depRL 100 步和离屏渲染检查；运行器完成后仍需在交互窗口中确认最终相机与外观。

## 10. 后续升级

今日 Demo 通过后，依次进行：

1. 使用 Phase 1/2 训练因果 TCN；
2. 用 TCN 估计代替 oracle 人体关节力矩；
3. 将估计结果和可测历史状态输入 PPO Actor；
4. 将理想刚性外观升级为独立外骨骼刚体和绑带约束；
5. 标定 URDF 零位、关节轴、长度和真实电机持续工作包络；
6. 开展 Sim2Sim 和实机台架验证。
