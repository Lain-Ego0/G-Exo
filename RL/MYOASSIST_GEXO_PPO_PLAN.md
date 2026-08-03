# MyoAssist / G-Exo 四髋膝 PPO 执行计划

状态：B-P0--B-P8 已完成；训练基础设施通过验收。当前协议下的 100k T0 策略在
`1.0/1.25 m/s` 有配对减负，但在 `0.8 m/s` 跌倒，因此尚未通过全速度策略门；
2026-08-03 建立并持续更新。

架构和复用边界以 `RL/MYOASSIST_GEXO_BOUNDARY.md` 为准；逐步修改、review 和
测试证据写入 `RL/MYOASSIST_PPO_IMPLEMENTATION_LOG.md`。本文回答“以什么顺序做到
正式 PPO 训练前、每一步产出什么、何时允许继续”。

## 1. 已锁定的 MVP

### 1.1 范围

- 人体：MyoAssist 22 肌肉二维下肢模型；
- 人体控制：从已有 speed-control checkpoint 迁移 22 肌肉权重，在无旧踝惯量的
  BASELINE 模型上以零外骨骼力矩短程微调，通过验收后冻结；
- 外骨骼：左髋、左膝、右髋、右膝四个理想关节力矩；
- 物理：MyoAssist / MuJoCo，1200 Hz；
- 人体、外骨骼、传感器和 TCN 控制：统一 50 Hz；
- 部署传感器：四关节位置/速度和四个大腿/小腿 IMU，共 32 维；
- 时序模型：50帧因果TCN；原始预测转换为两个horizon相对当前q/dq的归一化增量，
  共16维；
- 外骨骼 Actor：160 维输入、4 维归一化输出；
- 电机输出：复用项目统一的限矩、限速和滤波；
- 训练：SB3 PPO，只更新四输出外骨骼 Actor 和对应 Critic；
- 评价：相同 seed、速度和初始状态下的零助力 baseline / policy 配对报告。

### 1.2 非目标

- 不接 G-Exo URDF，不加入外骨骼质量、惯量、碰撞或绑带；
- 不开启任何域随机化；
- 不从零训练人体，不在外骨骼 PPO 期间更新人体，也不联合训练人体与外骨骼；
- 不支持三维转向、横向平衡、楼梯或斜坡；
- 不把参考轨迹、未来真值、肌肉状态或完整 MyoAssist Observation 输入部署 Actor；
- 不把 Kinesis 负载分担求解器带入 MyoAssist；
- 不直接用仿真百分比推断真人代谢节省。

## 2. 启动证据与当时阻塞

本轮实施启动时已有的可复现实验事实：

1. MyoAssist setup verification 为 13/13；
2. 旧踝执行器原始 `ctrlrange=[-1,0]`，经环境归一化后，归一化动作 `+1`
   对应物理控制 `0`，即 `0 Nm`；
3. 保留 tutorial 训练惯量、严格零踝力矩且控制改为 50 Hz 时，0.8 和 1.25 m/s
   各三个 seed 全部走满 1000 步；
4. 删除旧踝硬件的 2.33 kg 总惯量后，同 checkpoint 在 0.8 m/s 约 109 步跌倒；
5. 项目已经有 Phase 1/2 TCN、32 维传感器、四帧 144 维 Observation 和四电机
   安全层。

结果证明 released checkpoint 依赖 tutorial 的附加惯量；隐藏兼容惯量可以验证加载、
reset 和频率，但不能作为正式 PPO 物理模型。正式人体基座必须使用 BASELINE +
四髋膝模型，迁移并短程微调 22 肌肉策略。开始组合环境前必须定位并清理：

- MuJoCo qpos、qvel、act、ctrl 和仿真时间；
- MyoAssist imitation reference index；
- 目标速度模式、相位和切换计时器；
- episode step counter、足跟触地缓存和 reward 累计；
- Gymnasium、NumPy、Python 和策略随机数状态；
- 外骨骼安全层、TCN 和 Actor 历史缓存。

## 3. 目标数据流

```text
released checkpoint 的 22 肌肉权重
    -> BASELINE 模型 + 严格零四髋膝力矩短程适配
    -> stable human checkpoint（随后冻结）

MyoAssist 原生人体 Observation
    -> 冻结 adapted human_actor
    -> 22 维肌肉动作

MyoAssist q/dq/body sensor
    -> RL/env/myoassist/sensor_adapter.py
    -> gexo_sensor32_runtime_v1 @ 50 Hz
       |-> 50 帧传感器历史
       |   -> 共享因果 TCN
       |   -> +100/+200 ms 四关节 q/dq 相对当前状态的增量
       |   -> 固定 mean/std/clip = 16 维
       |
       `-> [32 维传感器, 上一步实际施加归一化动作 4 维]
           -> 最近 4 帧，按旧到新展平 = 144 维

[144, 16] -> 160 维部署 Observation
    -> PPO AssistActor
    -> 归一化动作 4 维
    -> TorqueActuator
    -> 四路物理 Nm

[22 路肌肉, 4 路 G-Exo]
    -> MyoAssist / MuJoCo，24 个物理子步
    -> 下一状态、肌肉快照、奖励和终止
```

新模型的动力学 action 数量为 26：前 22 路肌肉、后 4 路 G-Exo。旧两路踝部
执行器不进入新动作空间。`+1 -> 0 Nm` 的结论只用于验证旧 checkpoint 的零助力
基线，不应变成新四髋膝执行器的零点；新执行器必须满足归一化 `0 -> 0 Nm`。

## 4. 共享与后端文件组织

### 4.1 直接复用

- `RL/data/dataset_manifest.py`
- `RL/data/preprocess_tcn.py`
- `RL/data/tcn_dataset.py`
- `RL/runners/predictors/tcn.py`
- `RL/env/sensors.py`
- `RL/env/torque.py`
- `RL/train.py` 的并行环境、PPO、checkpoint、TensorBoard 和恢复框架；当前没有
  监督 AssistActor 初始化钩子，不能把该能力算作直接复用
- MyoAssist base、imitation 和已有 22 肌肉 checkpoint 的初始化权重

### 4.2 抽取到中立目录

- `RL/metrics/physiology.py`：从 Kinesis 指标抽取纯 NumPy 计算；
- `RL/optimization/contracts.py`：定义不含 MuJoCo 名字的 `MuscleSnapshot`；
- 后端无关 TCN runtime：checkpoint、归一化、50 帧缓存和推理；
- 统一 144 + 16 Observation 构造；
- 教师 NPZ、AssistActor 和统一评估报告在需要时只维护一份。

### 4.3 必须新增

实施启动时需要由共享 owner 新增（当前落地状态见第 12 节）：

- `RL/optimization/contracts.py`
- `RL/metrics/physiology.py`
- `RL/data/assist_teacher_dataset.py`
- `RL/runners/predictors/assist_actor.py`
- 统一 TCN runtime 和 160 维 Observation contract/test

MyoAssist 后端专属：

- `RL/env/myoassist/gexo_leg_env.py`
- `RL/env/myoassist/sensor_adapter.py`
- `RL/env/myoassist/muscle_adapter.py`
- `RL/env/myoassist/policy_transfer.py`
- `RL/env/myoassist/human_adaptation.py`
- `RL/assets/myoassist/` 下的四髋膝理想执行器模型或生成配置
- MyoAssist 环境工厂、smoke runner 和统一 evaluator

所有 MyoAssist joint、body、muscle、sensor 和 actuator 名称留在该后端。默认不改
`third_party/myoassist/`；随机速度位置参数错误通过 adapter 的关键字参数覆盖。
`third_party/Kinesis/` 同样保持只读；本路线不从其上游仓库搬运后端实现。

### 4.4 固定协议与 checkpoint metadata

所有共享数据固定使用：

| 项目 | 协议 |
|---|---|
| 关节顺序 | `[左髋, 左膝, 右髋, 右膝]` |
| q / dq / torque | `rad` / `rad/s` / `Nm` |
| IMU | 局部 `rad/s` 和局部比力 `m/s^2` |
| TCN 外部 / PyTorch shape | `[50,32]` / `[B,32,50]` |
| Actor Observation | `4 x 36 + 16 = 160` |
| Actor action | `[4]`，归一化 `[-1,1]` |
| TCN部署特征 | `[delta_q(+5), delta_dq(+5), delta_q(+10), delta_dq(+10)]`，使用checkpoint/calibration固定统计 |
| 动作尺度/硬限矩 | 逐关节 `0 < action_torque_scale_nm <= torque_limit_nm` |

TCN、教师数据和 Actor checkpoint 至少记录：

- `sensor_protocol`、Observation 协议版本和关节顺序；
- 输入、TCN feature 和 action 的归一化统计；
- TCN history、frequency、horizons、模型结构和 checkpoint hash；
- MyoAssist model、人体 checkpoint、calibration 和代码版本/hash；
- 四执行器名称、顺序、符号、逐关节action scale、硬限矩、限速和滤波参数；
- TCN delta16固定统计及 `gexo_zero_assist_preroll50_v1` 启动协议；
- `teacher_backend`、seed、速度/参考条件和数据集 split；
- 是否启用 URDF、域随机化和任何特权信息，MVP 必须全部为否。

metadata 不完整或协议不一致时只能显式走 legacy adapter，禁止自动猜测维度后加载。

## 5. 人体策略迁移、适配与冻结

旧 checkpoint 是 44 维观察到 24 维动作的 human/exo 分网策略。只迁移其中 44 到
22 的人体 Actor 参数；旧两路踝动作和旧 critic 都不是正式人体 checkpoint：

```text
released human_actor weights
    -> 22-action human-only PPO on BASELINE + zero G-Exo torque
    -> adapted 44-to-22 checkpoint
    -> freeze
```

人体适配 reward 只使用 MyoAssist 原有的速度、存活、足底冲击、关节约束和肌肉激活
项；四路外骨骼控制在 wrapper 内固定为严格零，不允许外骨骼策略或外骨骼 reward
进入该阶段。外骨骼 PPO 不复用旧 exo Actor，也不能把旧两路踝动作映射到四髋膝。
适配完成后的冻结必须可验证：

- 人体网络所有参数 `requires_grad=False`；
- 人体网络保持 evaluation mode；
- optimizer parameter list 不含人体参数；
- PPO smoke 前后计算人体参数 hash，必须完全一致；
- reset 必须重置策略需要的随机状态，但不能重新初始化权重。

正式适配验收至少覆盖 0.8、1.25 m/s 和训练速度范围内的若干中间速度；每档多 seed
运行 1000 步，报告存活、平均速度、最低骨盆高度、躯干俯仰、关节限位和激活代价。
未通过该门不得启动外骨骼 PPO。

MVP 统一 50 Hz 调用人体 Actor。只有正确 reset 后 50 Hz 回归失败，才启用 30 Hz
人体 / 50 Hz 外骨骼的时间累加回退；不得先实现双频增加复杂度。

## 6. 传感器、TCN 与 Actor

### 6.1 32 维运行时传感器

运行时固定为：

```text
q4, dq4,
gyro(left_thigh, left_shank, right_thigh, right_shank),
specific_force(left_thigh, left_shank, right_thigh, right_shank)
```

后端负责 MyoAssist 零位、正方向和 IMU 局部旋转。共享 runtime 只做 shape、单位、
历史和网络推理，不知道任何 body ID。

Phase 1/2 TCN 数据按每个 IMU 的 gyro/accel 交错排列。必须通过一处有版本的排列
转换从 `gexo_sensor32_runtime_v1` 变成 `phase12_tcn32_interleaved_v1`，并用索引
哨兵单元测试证明 32 个通道没有错位。

### 6.2 160 维部署 Observation

每个 Actor 单帧为32维传感器加上一步4维实际施加归一化动作：

$$
a^{applied}_{t-1}
=\tau^{applied}_{t-1}/action\_torque\_scale\_nm.
$$

Episode第一帧该动作固定为零，当前requested/applied action不得进入当前
Observation。最近四帧按从旧到新展平：

$$
o_{hist,t} = [f_{t-3}, f_{t-2}, f_{t-1}, f_t] \in \mathbb{R}^{144}.
$$

TCN读取独立的50帧纯传感器缓存。网络先输出绝对未来q/dq，再相对当前状态求差：

$$
\hat{x}_{t+5},\hat{x}_{t+10},\qquad
\hat{x}=[q_{LH},q_{LK},q_{RH},q_{RK},
\dot q_{LH},\dot q_{LK},\dot q_{RH},\dot q_{RK}].
$$

进入Actor前，严格按
`[delta_q(+5), delta_dq(+5), delta_q(+10), delta_dq(+10)]` 排列，并使用
checkpoint/calibration冻结的mean/std/clip处理为 $z_{16}$。最终：

$$
o_t=[o_{hist,t},z_{16}]
\in \mathbb{R}^{160}.
$$

MVP reset后先让冻结人体在严格零外骨骼力矩下真实预滚动50个50 Hz控制步。TCN使用
全部50帧，Actor使用最后4帧，动作历史全为零；预滚动推进仿真和参考内部状态，但
不计入策略episode步数、reward、终止统计或教师标签。预滚动失败则reset失败。
离线trial只在同一trial内50帧历史、四帧历史及 `+10` horizon均有效时生成样本，
禁止填零、重复首帧或跨trial/reset拼接。TCN必须冻结且只读取当前及过去帧；Actor
首版不使用64维latent。

### 6.3 动作尺度与安全层

归一化Actor动作先乘逐关节 `action_torque_scale_nm` 得到requested torque，再依次
执行变化率限制、滤波和最终 `torque_limit_nm` 硬裁剪。两者逐项满足：

$$
0 < action\_torque\_scale\_nm[j]
\le torque\_limit\_nm[j].
$$

共享 `TorqueActuator` 新增可选动作尺度；未提供时默认等于硬限矩，确保旧调用行为
不变。监督教师必须在动作尺度内产生标签，禁止靠安全层静默clip教师标签。

## 7. 奖励原则与公式

### 7.1 主目标：MyoAssist 仿真中的生理与机械减负

激活代价使用 22 块肌肉的平方均值：

$$
C_a(t)=\frac{1}{22}\sum_{i=1}^{22}a_i(t)^2.
$$

人体净关节力矩用于衡量外骨骼是否真正承担了关节级机械需求：

$$
C_h(t)=\frac{1}{4}\sum_{j=1}^{4}
\left(\frac{\tau_{human,j}(t)}{S_{h,j}}\right)^2.
$$

但净力矩会抵消拮抗肌共收缩，因此还要用肌肉力 $F_i$ 与 moment arm $r_{ij}$
计算非抵消负载：

$$
C_g(t)=\frac{1}{4}\sum_{j=1}^{4}
\frac{\sum_{i=1}^{22}|r_{ij}(t)F_i(t)|}{S_j},
$$

其中 $S_{h,j}$ 和 $S_j$ 是只由训练 baseline 估计的逐关节正尺度。三个量的职责固定：
$C_a$ 是主要生理代价，$C_h$ 是主要机械卸载量，$C_g$ 只用于阻止共收缩或局部负担
转移，不单独替代前两项。

现有人体 checkpoint 的步态相位没有被 imitation reference index 锁定，因此禁止按
参考帧逐帧减 baseline。只用训练速度集合的零助力 rollout 建立速度条件统计
$\mu_a(v),\sigma_a(v),\mu_h(v),\sigma_h(v)$；它们只负责中心化和尺度归一化：

$$
s_a=\operatorname{clip}\left(
\frac{\mu_a(v)-C_a(t)}{\sigma_a(v)+\epsilon},-s_{max},s_{max}\right),
$$

$$
s_h=\operatorname{clip}\left(
\frac{\mu_h(v)-C_h(t)}{\sigma_h(v)+\epsilon},-s_{max},s_{max}\right).
$$

首版 effort 使用加权和，不使用逐帧 `min()` 或负值双倍惩罚：

$$
s=\alpha s_a+(1-\alpha)s_h.
$$

$\alpha$ 首版固定为 `0.6`。22 块肌肉全部纳入、等权且权重和为 1；四关节同样等权。
各尺度在 B-P6 只用训练 baseline 标定，不能使用 reference frame、验证集
或 total reward 反调统计量。最终“省力百分比”不从单步 reward 反推，只在同 seed、
同速度、同初态的整段零助力 / policy 配对 rollout 上按时间积分计算。

非抵消负载只在超过速度条件 baseline 容差后产生软惩罚：

$$
C_{gross,excess}=\left[\max\left(0,
\frac{C_g-(1+\delta_g)\mu_g(v)}{\sigma_g(v)}\right)\right]^2.
$$

$\mu_g(v)$ 固定为训练 split 零助力 rollout 中相应速度 bin 的 $C_g$ 稳健中位数；
$\sigma_g(v)$ 使用 `max(MAD, 0.05 * median, 1e-6)`。速度落在相邻 bin 间线性插值，
超出训练速度范围直接拒绝，不做静默外推。$\delta_g$、所有 baseline 数组、reward/gate
参数、指标 schema 和产物 SHA256 都必须写入训练与评估 metadata。

### 7.2 速度和无相位站立包络是安全铰链

人体 checkpoint 不锁定 imitation reference phase，因此 reward 和 gate 禁止读取
reference index 或逐帧 q/dq tracking。B-P6 必须只从训练 baseline 固定以下参数：
速度免费误差 $e_{v,free}$、速度过渡尺度 $\Delta v$、最低骨盆高度 $h_{min}$、躯干
免费俯仰 $\theta_{free}$、各关节限位余量，以及对应过渡尺度。验证和训练期间冻结。

速度与站立越界量定义为：

$$
E_v=\max\left(0,
\frac{|v_x-v^*|-e_{v,free}}{\Delta v}\right),
\qquad
C_v=E_v^2,
$$

$$
E_u=\max(E_h,E_{pitch},E_{joint}),
\qquad
C_u=E_u^2,
$$

其中 $E_h$ 是骨盆低于 $h_{min}$ 的归一化越界，$E_{pitch}$ 是躯干俯仰超出免费区间
的归一化越界，$E_{joint}$ 是四关节进入限位余量后的最大归一化越界。安全 gate 为：

$$
g_v=\operatorname{clip}(1-E_v,0,1),
\qquad
g_u=\operatorname{clip}(1-E_u,0,1),
\qquad
g=g_vg_u.
$$

正的省力只有在速度和站立合格时兑现，负的省力始终保留：

$$
R_{effort}=g\max(s,0)+\min(s,0).
$$

这样策略不能靠跌倒、降低速度或逼近关节限位伪造肌肉放松，同时不会被未锁定的
参考相位强行扭曲。

### 7.3 电机正则和总奖励

四类正则分别约束力矩幅值、二阶变化和超过允许阈值的正功：

$$
C_{\tau}=\frac{1}{4}\sum_j
\left(\frac{\tau_j}{\tau_{j,max}}\right)^2,
$$

$$
C_{jerk}=\frac{1}{4}\sum_j
\left(\frac{\tau_{j,t}-2\tau_{j,t-1}+\tau_{j,t-2}}
{\Delta\tau_{scale}}\right)^2,
$$

$$
C_{power}=\max\left(0,
\frac{\sum_j\max(\tau_j\dot q_j,0)-P_{free}}{P_{scale}}\right)^2.
$$

总奖励结构为：

$$
r_t=w_eR_{effort}+r_{alive}
-w_vC_v-w_uC_u
-w_gC_{gross,excess}-w_{\tau}C_{\tau}-w_jC_{jerk}-w_pC_{power}
-w_f\mathbb{1}_{fall}.
$$

原则：

- effort 是唯一需要持续最大化的目标；
- 速度和无相位站立包络只在越界后处罚；
- 不增加相位模仿奖励、`tau * dq` 方向奖励或 dense imitation 正奖励；
- 限矩和限速属于硬安全层，reward 正则不能替代硬约束；
- gross 恶化作为软铰链；共收缩、分肌群结果、负功和峰值继续单独报告；
- baseline、oracle、policy 的所有指标使用同一实现和相同 seed 配对。

### 7.4 Reward 与 baseline 的职责边界

Reward 和 baseline 不是二选一。Reward 定义优化目标和约束；baseline 是同条件
零助力反事实参照，只用于把“绝对负担”转换成“相对无助力是否减负”。具体约束如下：

- 训练 reward 仍由本节定义的激活、人体净关节力矩、非抵消负载、速度、站立安全和
  电机正则共同组成；baseline 不输出动作、不控制人体，也不提供逐帧模仿轨迹；
- 速度条件 baseline 只提供 $\mu_a(v),\sigma_a(v),\mu_h(v),\sigma_h(v)$ 和 gross
  包络，使不同速度的绝对负担具有可比尺度；
- 不允许只优化绝对激活或绝对关节力矩，否则策略可通过减速、缩短 episode 或跌倒
  降低代价；正 saving 仍必须通过速度和站立 gate；
- 最终好坏不由训练 total reward 单独决定，而由同 seed、同速度、同初态、同长度的
  `baseline / policy` 配对积分决定；oracle 只是动作敏感性诊断，不是生理真值或性能
  上界；
- baseline 条件不匹配、pair 未走满或 horizon 不一致时，省力百分比必须为空并排除，
  不能拿不完整 episode 计算看似更好的改善。

## 8. B-P0--B-P8 实施顺序

为满足迅捷开发要求，B-P0--B-P7 连续实施并逐项追加测试证据，不再等待逐阶段独立
review；B-P8 仍必须由此前未参与编辑的新 agent 做一次完整审计。

### B-P0：边界、计划和日志

产出：

- `RL/MYOASSIST_GEXO_BOUNDARY.md`
- `RL/MYOASSIST_GEXO_PPO_PLAN.md`
- `RL/MYOASSIST_PPO_IMPLEMENTATION_LOG.md`

验收：文档与当前文件一致；频率决定、旧踝零点、非目标和 review 规则无歧义；没有
代码修改。

### B-P1：消费共享契约和中立指标

路线 B 不新增或修改任何共享文件。本阶段只消费路线 A 已独立通过的：

- S-P1A：runtime32、Actor Observation、动作尺度与安全层契约；
- S-P1B：`MuscleSnapshot` 和中立生理指标。

验收：记录 S-P1A/S-P1B 的 `PASS` 状态、文件哈希、schema/version 和导入 smoke；
MyoAssist adapter 只依赖公开契约，不 import Kinesis，也不把 MyoAssist 名称写入共享
模块。若共享产物尚未 PASS，B-P2/B-P3 可独立推进，但 B-P4/B-P6 不得用私有复制品
绕过依赖。

### B-P2：四髋膝理想执行器模型

在 G-Exo 资产目录生成两类模型，不改第三方 XML：

1. 正式模型从 `myoLeg22_2D_BASELINE.xml` 生成，只包含 22 肌肉和四个髋膝理想
   torque actuator，不含旧踝硬件惯量；
2. teacher-compatible 模型保留 tutorial 训练时的不可见惯量，只用于迁移前诊断，
   禁止用于最终外骨骼 PPO 和有效性结论。

验收：两模型编译；正式模型 `nu=26`；前 22 路肌肉顺序与人体 Actor 一致；后四路严格按
`[左髋, 左膝, 右髋, 右膝]`；归一化零动作产生 0 Nm；正负单位脉冲的 qacc/qvel
响应方向正确；不存在 URDF 或旧踝执行器；正式模型不存在 `teacher_inertia_*`。

### B-P3：人体迁移适配、冻结和 reset

建议文件：

- `RL/env/myoassist/policy_transfer.py`
- `RL/env/myoassist/human_adaptation.py`
- `RL/env/myoassist/gexo_leg_env.py` 的 reset/人体最小路径

先修复同一实例重复 reset，不接 TCN 和外骨骼 PPO。把 released 人体 Actor 权重映射
到 22-action human-only PPO，在正式 BASELINE 模型上以零外骨骼力矩短程微调，
使用统一 50 Hz；通过稳定性门后冻结适配 checkpoint。

验收：

- 连续至少 10 次 reset，无历史状态泄漏；
- 固定 seed 的初态、目标速度和首步人体动作可复现；
- 0.8、1.25 m/s 及至少一个中间速度各至少 3 seed，连续 reset 后走满 1000 步；
- 权重迁移逐层 shape、参数值和动作输出均有测试；四路外骨骼在适配中严格为 0 Nm；
- 保存、重载后的 adapted checkpoint 输出一致；冻结后参数 hash 在外骨骼 smoke
  前后不变。

若 50 Hz 适配失败，先使用 30 Hz 人体 / 50 Hz 外骨骼多速率回退；不得回到隐藏旧踝
惯量作为正式方案。

### B-P4：MyoAssist 32 维传感器

建议文件：`RL/env/myoassist/sensor_adapter.py`。

验收：四关节顺序、rad、rad/s、四 IMU 局部角速度和比力逐项正确；静止、单位旋转
和重力方向样例通过；输出 `(32,)`、finite、确定；noise 和 domain randomization
保持关闭。

### B-P5：TCN 和 160 维 Observation

本阶段只消费并验证已独立 `PASS` 的 S-P1C 共享 TCN runtime，以及 S-P1A 的
Observation builder；记录文件哈希、schema/version、checkpoint/calibration 协议和
导入 smoke。接线代码只落在路线 B 所有的 MyoAssist adapter/environment 中，用于
构造四帧 144 维和 16 维预测。不得新增或修改共享 TCN/Observation 文件，也不得
修改 Kinesis adapter；共享产物尚未 `PASS` 时，B-P5 不得用私有复制品继续。

验收：

- 运行时到数据集 32 维排列逐索引正确；
- TCN 恰好读取 50 个当前/历史帧；改变未来数据不影响当前输出；
- PyTorch shape 为 `[B,32,50]`；Actor shape 为 `(160,)`；
- reset 填充、归一化、checkpoint metadata 和 calibration 可复现；
- TCN checkpoint 冻结，输出 finite，no-TCN/零特征仅作为对照而非正式配置。

### B-P6：肌肉 adapter、baseline 和奖励

建议文件：`RL/env/myoassist/muscle_adapter.py`，并复用 B-P1 指标。

验收：

- 22 肌肉 activation、force 和四目标关节 moment arm 对齐；
- 人工样例证明净关节力矩 $C_h$ 与非抵消负载 $C_g$ 含义不同，且拮抗肌不会在
  $C_g$ 中抵消；
- 零助力 baseline 只按速度条件提供固定统计，不按未锁定的 reference index 查询，
  训练和验证数据不串；
- 零、正负小脉冲和多档力矩产生连续、重复的指标响应；
- 速度或无相位站立包络越界时正 saving 被 gate，负 saving 不被隐藏；
- 所有 reward 分项单独记录，初始尺度无单一常数项淹没 effort。

### B-P7：PPO 工厂、冒烟和统一评估

复用 `RL/train.py` 的公开通用训练接口，但 B-P7 不修改该文件。所有新增环境工厂、
训练入口参数和 evaluator 只落在路线 B 所有的
`RL/runners/train_myoassist_gexo.py`、`RL/runners/evaluate_myoassist_gexo.py` 及
`RL/env/myoassist/**`；不复制 PPO 算法。公开接口若不足，必须向共享 owner 提交独立
变更依赖，不得在本阶段顺带修改共享训练器。路线 B 的最快候选训练固定为 fresh PPO：只有 B-P6
action-sensitivity、零助力基线和 B-P8 训练前审计通过后才允许启动。它不属于路线 A
的监督训练，也不能替代路线 A 的教师/AssistActor 证据；训练回报升高本身也不构成
有效助力结论。

当路线 A 产出协议兼容的监督 AssistActor 后，路线 B 再增加独立的 warm-start 对照。
现有 `RL/train.py` 没有该初始化钩子，必须由共享 S-P4 新增显式权重映射并测试；
`resume_from` 不能冒充监督初始化。

当前共享 owner 已增加后端无关的 `additional_callbacks` 公开参数，路线 B 只用它挂载
专属 TensorBoard callback；`RL/train.py` 中不保留 MyoAssist 字段名或后端判断。该
扩展不改变 PPO、向量环境、checkpoint 或旧调用的默认行为。

验收：

- 1 worker 随机动作 smoke；
- 8 worker、至少 100k steps PPO smoke；
- TensorBoard 含 total、每个 reward 分项、存活、速度、骨盆高度、躯干俯仰、关节
  越界、激活、人体净关节力矩、非抵消负载、外骨骼力矩、二阶变化和功率；
- checkpoint 保存/恢复后 Observation 协议和输出一致；
- 人体 Actor 与 TCN hash 在训练前后不变；
- baseline / oracle / policy 可按同 seed 输出统一 JSON/NPZ 报告；
- 无 NaN、worker 死锁、reset 串状态、URDF 或域随机化。

### B-P8：新的整体 reviewer

由此前未参与编辑的更新 agent 重新读取边界、计划、日志、实际代码和所有测试报告。
它必须逐条证明 B-P0--B-P7，而不是只运行一个总测试命令。

B-P8 `PASS` 后状态是“已到 fresh PPO 候选训练前”，不是“策略已经有效”。随后才
启动分级候选训练。监督 warm start 由路线 A 的 S-P4 单独提供，不是 B-P8 的前置
依赖。

## 9. 工时估计

| 阶段 | 乐观 | 保守 | 主要不确定性 |
|---|---:|---:|---|
| B-P0 文档 | 0.5 h | 1 h | 独立 review 修改 |
| B-P1 消费共享契约/指标 | 0.25 h | 0.5 h | 等待 S-P1A/S-P1B PASS 与接口哈希 |
| B-P2 四执行器模型 | 1 h | 2 h | actuator 顺序和 XML 资源路径 |
| B-P3 人体迁移适配/冻结/reset | 2 h | 6 h | 无旧惯量策略适配速度与稳定性 |
| B-P4 传感器 | 1 h | 2 h | IMU site 和局部坐标 |
| B-P5 TCN/160 维 | 1 h | 2 h | calibration 和旧 checkpoint metadata |
| B-P6 指标/reward | 2 h | 4 h | moment arm 对齐和 baseline 方差 |
| B-P7 PPO smoke/评估 | 1.5 h | 3 h | 多进程内存与 reset |
| B-P8 总审计 | 1 h | 2 h | 回归发现返工 |

若人体适配一次通过，距离正式训练前约 10--16 工时；保守约 18--28 工时。正式
外骨骼训练时间不计入此表。100k smoke 预计数十分钟，首个 1M 筛选通常约
0.5--2 小时，具体由 8 worker 实测速率决定。

## 10. 主要风险和回退

| 风险 | 先做的证据检查 | 回退 |
|---|---|---|
| 重复 reset 泄漏状态 | 同 seed 连续 10 次初态/首步 hash | 每项显式 reset；必要时每 episode 重建环境作诊断 |
| 50 Hz 经正确 reset 后失稳 | 0.8/1.25 多 seed 连续 episode | 30 Hz 人体 + 50 Hz 外骨骼时间累加 |
| released 策略依赖旧踝惯量 | 已由删除惯量 A/B 确认 | 正式 BASELINE 上迁移微调；兼容惯量只作诊断 |
| 四髋膝符号错误 | 正负脉冲 qacc/qvel | 只修 MyoAssist calibration/actuator 映射 |
| Phase TCN 仿真迁移差 | 输入分布、预测误差、zero-TCN 对照 | 先冻结使用显式输出；重新标定，不动网络结构 |
| reward 被近常数项淹没 | 分项均值、方差、action 敏感度 | 移除常数正奖励，只按训练 baseline 方差重标 effort |
| 策略通过慢走/跌倒伪省力 | speed + phase-free upright gate | 收紧安全阈值和异常终止，不添加 dense 模仿奖励 |
| 多进程内存或死锁 | 1/2/4/8 worker 梯度 smoke | 降 worker；保持相同环境协议和 seed 测试 |
| 二维模型无法覆盖目标场景 | 明确能力报告 | 平地变速 MVP 后再进入三维模型，不伪造转向结果 |

回退不得跨越架构边界：不能为了跑通而改 Kinesis、把 MyoAssist 名字写入共享模块、
把 URDF 提前接入、开启未记录的域随机化，或在外骨骼 PPO optimizer 中加入人体参数。

## 11. B-P8 通过后的训练阶段

B-P8 以前的 PPO 只属于工程 smoke。B-P8 `PASS` 后按以下阶段训练，不能直接挂长程任务：

### T0：100k 因果和数值筛选

- 8 worker，固定训练速度集合和 seed 策略；
- 检查 reset、NaN、TensorBoard 分项、动作饱和、人体/TCN hash；
- 与随机策略、零动作和简单相位 oracle 比较 action sensitivity；
- 任一协议或生理指标错误立即停止，不通过调 reward 权重掩盖。

### T1：1M 策略筛选

- 至少三个随机 seed；
- 每 250k 保存 checkpoint 并在固定 holdout 上配对评估；
- 同时报告激活平方、人体净关节力矩、非抵消肌肉负载、速度、骨盆高度、躯干俯仰、
  关节越界、跌倒率、外骨骼力矩和功率；
- 只有训练集和 holdout 都出现可重复改善，才能继续。

### T2：3--5M 候选策略训练

- 使用 T1 最稳定的结构和 reward，不在训练中途改变定义；
- 保留最佳 holdout checkpoint，不以 total reward 单独选模；
- 若 1M 后 action sensitivity、肌肉节省和 holdout 均无改善，停止并回到 B-P6 审计，
  不盲目扩到 10M；
- 通过后再讨论速度课程、三维模型、地形、URDF 和域随机化。

路线 B 有效性结论的最低标准是：在预注册的相同条件成对 holdout 中，激活平方和
人体净关节力矩均不恶化，至少一项有跨 seed 的稳定改善；gross 非抵消负载不超
容差，目标速度、无相位站立包络和存活在允许阈值内；改善不是由更低速度、更短
episode 或更大共收缩换来的。通过后只能表述为“当前 MyoAssist 二维模型内有效”，
不能替代路线 A 的监督证据，也不能外推实机效果。

## 12. 2026-08-03 当前实施状态

当前已经完成 B-P0--B-P7 的训练前工程闭环。B-P8 首轮审查发现正式 baseline
代码已升级到 `v3`，但旧产物和旧 100k run 仍锁定 `v2`；现已重建产物并补跑当前
协议 smoke/resume。第二个全新 agent 已完成只读复审并给出 B-P8 PASS，但范围严格
限定为“训练就绪 + 固定二维平地 `1.0 m/s` 仿真/数据 demo”，不是“已经得到有效
实机策略”。当前权威约束为：

- 正式模型是 22 肌肉人体加 `[左髋、左膝、右髋、右膝]` 四个理想力矩执行器；不接
  G-Exo URDF，不开启域随机化；
- 控制频率 50 Hz；`runtime32 -> 4 x 36 = 144 -> TCN feature16 -> Actor160 ->
  normalized4 -> TorqueActuator -> physical4 Nm`；
- TCN 与适配后人体 Actor 全程冻结，训练前后 SHA256 必须一致；
- 训练速度协议固定为 `uniform_per_episode_v1`：每回合从 `[0.8,1.25] m/s` 均匀采样
  一个目标，回合内部不跳变；回合内变速、地形、URDF 和域随机化均推迟；
- 不可变训练协议为 `gexo_myoassist_ppo_protocol_v3`，恢复训练必须逐字段和哈希一致；
- 零助力 baseline、TCN calibration、物理模型、人体 checkpoint 和 TCN checkpoint
  的身份哈希在环境构建前交叉验证。

当前代码和 baseline `v3` 的工程证据为
`RL/outputs/myoassist_exo_ppo_current_protocol_smoke/`：8 worker 从 0 运行至 8192 步，
TensorBoard、4096/8192 checkpoint、确定性 Eval 和冻结哈希检查通过；随后
`RL/outputs/myoassist_exo_ppo_current_protocol_resume/` 从该 final model 续训至
12288 步，协议哈希均为
`b07f4ed75247cfe51f02e790825a44b0c280bf414b15425318691c777dc8c477`。

旧 `RL/outputs/myoassist_exo_ppo_100k_smoke_v5/` 是 baseline `v2` 下的历史 100k
候选，不再作为“当前协议训练证据”，但 Observation、动作和物理模型没有变化，仍可
作为固定工况 demo 候选。用当前 baseline `v3` 和当前 evaluator 在 `1.0 m/s`、3 个
seed 上重新配对，3/3 均走满 500 步，激活平方、人体四关节力矩和非抵消肌肉负载的
saving 分别为 `3.49%`、`14.78%`、`4.75%`。报告位于
`RL/outputs/myoassist_quick_demo_1ms/paired_evaluation.json`。因此：

- 该结果证明训练、记录、恢复和评估流水线已经可运行；
- 快速 demo 明确锁定二维平地 `1.0 m/s`，不把这组结果外推到低速、变速、转向、
  楼梯、URDF 或真人代谢节省；
- seeds 0/1/2 在 canonical 确定性条件下生成相同轨迹，3/3 只证明重复性，不证明
  独立随机鲁棒性；
- 历史 100k policy 在 `0.8 m/s` 的 3 组均于 157 步跌倒，仍不满足全速度策略
  有效性门；不得删除该反例或用固定工况结果冒充全域有效性；
- 快速 sim2real 只继续做模型导出、离线输出一致性、50 Hz 推理和高频电机安全层；
  当前 demo 平均绝对力矩约 `6.43 Nm`，实机首测必须把幅值缩放到约 `1--2 Nm`，并
  使用支撑、急停和 watchdog，不能直接使用仿真 `17 Nm` 上限；
- URDF、域随机化、楼梯和长时多 seed 调参全部推迟到 demo 之后。

## 13. 当前权威训练前证据

本节晚于第 12 节，覆盖其中相同主题的旧数值，但不删除旧实验记录。

### 13.1 模型与旧踝外骨骼的边界

- 正式物理模型为 `RL/assets/myoassist/myoLeg22_2D_GEXO.xml`，SHA256 为
  `7127a1cb67a64782410659f73dfd752b5b490c3d8c3a4f0e2f615e5af6c331fe`；
- 人体解剖踝关节和踝肌仍存在，因为人体步态需要它们；
- MuJoCo 模型 `nu=26`：前 22 路是人体肌肉，最后四路严格为
  `gexo_left_hip/gexo_left_knee/gexo_right_hip/gexo_right_knee`；
- 不存在旧踝部外骨骼 actuator，也不存在为兼容旧 checkpoint 而隐藏保留的踝部
  外骨骼惯性；已发布策略只提供人体 Actor 初始化权重，正式冻结人体 checkpoint 是在
  当前无旧踝硬件模型上重新适配得到的；
- 本阶段仍不接 G-Exo URDF，不开启域随机化。以后接入 URDF 会改变动力学，必须重新
  验证人体稳定性并视情况短程适配，不能假设理想力矩模型权重无条件直迁。

### 13.2 逐速度 baseline 修复

旧 baseline 对所有速度共用一个速度误差阈值，掩盖了 `0.8/1.0/1.25 m/s` 三档基座
自身误差差异。当前 `gexo_myoassist_zero_assist_baseline_v3` 分别标定每档
`speed_free_error_m_s` 和 `speed_transition_m_s`，相邻速度只做线性插值，超出标定
范围直接拒绝。当前产物为：

- JSON SHA256：`bf87bab90bc2336e1f165c849b23e4ea2df101b622cd7e0eb40883e223a704a7`；
- trace NPZ SHA256：`f6ab19fc6f63a54780ed1e602748e2e59c1e0275ab1dba5af72e3ff7bdd58f88`；
- 4500 帧，`3 speeds x 3 seeds x 500 steps`，9/9 零助力 episode 完整；
- 三档 free error 分别约为 `0.3009/0.1454/0.0750 m/s`；
- 零动作 500 步回归在三档均完成，平均单步速度惩罚约为
  `-0.00583/-0.00039/-0.00443`，不再由错误的全局阈值支配低速 reward。

### 13.3 当前协议 100k 与恢复测试

当前权威 T0 输出为 `RL/outputs/myoassist_gexo_ppo_100k_smoke_v3/`：

- 8 worker、seed 42、`100352` 实际步数、500 步上限、`n_steps=256`、
  `batch_size=512`、`n_epochs=5`、CPU；
- 不可变协议 SHA256：
  `199f16b039cbc0329421e8ea498d0b4a1b8d52cffb427d4b28b35e48312f3185`；
- final model SHA256：
  `bbe30959902babf7dbf9dcced69cad99c8c9da21283487250070e75ab52af6fe`；
- TensorBoard 有 82 个 scalar tags，包含 PPO、全部 reward、安全、三类人体代价、
  速度/姿态、四关节状态/力矩/功率；训练 `ep_rew_mean` 从约 `-55.8` 上升到
  `62.7`，但 `ep_len_mean` 从 500 降到约 493.8，说明训练 reward 不能替代协议门；
- 人体 checkpoint 与 TCN checkpoint 的训练前后 SHA256 完全一致；
- 模型保存再加载后的确定性动作最大误差为 0，160 维 Observation、4 维动作和一步
  环境推进均 finite；
- `RL/outputs/myoassist_gexo_ppo_resume_smoke_v3_round2/` 从该模型续训 4096 步，
  SB3 计数从 `100352` 连续到 `104448`，协议哈希相同，冻结产物仍未改变。

### 13.4 严格配对结论

报告为
`RL/outputs/myoassist_gexo_ppo_100k_smoke_v3/paired_evaluation.json`，包含
`3 speeds x 3 seeds x reference 0` 的 baseline/oracle/policy 同条件配对：

- baseline 和 oracle 在 9/9 条件走满 500 步；
- policy 在 `1.0/1.25 m/s` 的 6/6 完整 pair 均通过协议；相对零助力基线的完整段
  平均 saving 为：activation-squared `3.31%`、人体四关节力矩代价 `17.35%`、
  gross 非抵消肌肉负载 `5.35%`；
- policy 在 `0.8 m/s` 的 3/3 条件均于第 175 步因骨盆高度终止；这些短 episode
  不计算 saving，也不能借较短积分伪造减负；
- 因此总结果是 `valid_pair_count=6/9`、`protocol_pass=false`、
  `effectiveness_pass=false`。这证明训练链路和动作因果有效，但该 100k checkpoint
  不是全速度可用策略。

### 13.5 下一阶段放行条件

工程层面已经可以开始 T1；策略层面不得直接挂 3--5M。最快路线是先以至少三个 PPO
seed 分别训练到 1M，并在 250k 间隔运行同一三速度配对评估。选模顺序固定为：

1. 三档速度全部存活并满足运动学协议；
2. activation 与人体力矩均不恶化，gross 在容差内；
3. 至少一个主要人体代价稳定下降；
4. 最后才比较 total reward。

若三个 seed 在 1M 仍重复出现 `0.8 m/s` 固定时刻跌倒，应停止延长训练，转而做低速
课程采样或低速专用初始化审计；不得通过放宽骨盆阈值、删除低速样本或只报告中高速
结果来换取 PASS。

当前可手动启动 T1。把训练与自动选模完全无人值守之前，还应完成两个非阻塞加固：

- 将 `RL/train.py` 继承的 `clip_range`、`ent_coef`、`vf_coef`、`max_grad_norm` 和
  `normalize_advantage` 也显式写入新 run 的不可变协议；现有 checkpoint 自身保存了
  实际值，所以该缺项不影响当前 100k/resume 证据；
- evaluator 默认校验 policy 相邻 `config.json` 与当前 baseline、物理模型、人体、
  TCN、Observation 和动作尺度；跨协议评估只能通过显式 override。当前报告已人工按
  路径、哈希和 config 交叉核对，因此该缺项不改变本轮结论。
