# G-Exo 共享监督助力与 MyoAssist 训练前实施计划

状态：执行计划，2026-08-03 建立，尚未完成代码实施。

本文把固定轨迹教师优化、因果 TCN、监督 AssistActor、MyoAssist 人体基座和
Kinesis 动态复核组织为一条可执行路线。本文回答“哪些基础设施只实现一次、哪些
内容必须由各仿真后端分别实现”，并给出推进到正式训练前的文件、阶段门和审阅
流程。

## 1. 文档权限与冲突处理

本计划必须同时遵守：

1. `RL/MYOASSIST_GEXO_BOUNDARY.md`：共享代码、后端代码和第三方代码的强制边界；
2. `RL/FIXED_TRAJECTORY_MULTITASK_PLAN.md`：固定轨迹教师优化的科学含义；
3. `RL/MYOASSIST_PPO_IMPLEMENTATION_LOG.md`：逐步修改、测试和 review 的追加式账本；
4. 本文：把上述约束转换成实施顺序和训练前验收清单。

本计划只拥有路线 A 和共享基础设施，阶段统一命名为 `S-P*`。MyoAssist 路线 B 的
阶段由 `RL/MYOASSIST_GEXO_PPO_PLAN.md` 以 `B-P*` 命名；相同数字不表示同一阶段。

若本文与边界文档冲突，以边界文档为准并停止实施；不得用临时 import、复制代码或
更改数组形状绕过冲突。若实现过程中发现会改变科学假设、策略输入、人体控制方式、
第三方代码或教师标签含义的问题，编辑 agent 必须立即向用户提问，得到决定后才能
继续该步骤。

## 2. 目标与非目标

### 2.1 当前目标

推进到“可以正式启动外骨骼策略训练”的状态，具体包括：

- 共享并版本化四关节、单位、传感器和 Actor Observation 协议；
- 用同一套后端无关公式计算激活、肌肉力矩、共收缩和机械功指标；
- 在固定人体轨迹上比较无助力与有助力肌肉募集，生成连续四关节教师力矩；
- 复用现有 50 Hz 因果 TCN，以过去 1 s 的可部署传感器预测未来运动；
- 监督训练四输出 AssistActor，输出左右髋膝的归一化动作；
- 用同一 `TorqueActuator` 完成力矩限幅、变化率限制和滤波；
- 在 MyoAssist 中冻结并复用 22 肌肉人体策略，只训练四输出外骨骼策略；
- 完成单元测试、Gymnasium 检查、并行 smoke、保存恢复和配对评估；
- 保留 Kinesis 现有动态 URDF 路线，用于助力后的稳定性与安全复核；
- 每个小变更由未参与编辑的 agent 独立 review 和测试，最后再由新的 agent 做
  整体审计。

### 2.2 本阶段明确不做

- 不修改 `third_party/myoassist/**` 或 `third_party/Kinesis/**`；只有 adapter
  确实无法解决且用户再次明确授权后，才能建立独立第三方补丁步骤；
- 不把 Kinesis 专属 joint/body/muscle 名称写进共享模块；
- 不把 MyoAssist 专属名称、22 肌肉动作或原生 Observation 写进共享模块；
- 不删除、重写或迁移现有 Kinesis 环境、checkpoint、baseline 和历史输出；
- 不在首版 MyoAssist 环境接入完整 G-Exo URDF、绑带、质量、碰撞或域随机化；
- 不联合更新 22 肌肉人体策略和外骨骼策略；
- 不用冻结 Kinesis 的在线肌肉 Reward 从随机动作重新发现完整助力规律；
- 不把仿真激活下降直接声称为真人 EMG、代谢或疲劳下降；
- 不宣称二维 MyoAssist 人体已经覆盖三维急转、楼梯、坡道或侧向稳定。

## 3. 固定架构与端到端数据流

### 3.1 离线教师与监督训练

```text
Phase 1/2 参考数据或经过筛选的仿真参考运动
    -> 统一时间、关节顺序、单位和有效区间
    -> 后端 muscle_adapter 生成每时刻 MuscleSnapshot
    -> 共享 fixed_trajectory 优化器
       |-> 无外骨骼肌肉募集 baseline
       `-> 有外骨骼肌肉--电机联合募集
    -> TeacherSolution 和连续四关节 tau_exo*
    -> 历史 sensor32 + 冻结 TCN
    -> 标准化 [delta_q(+5), delta_dq(+5), delta_q(+10), delta_dq(+10)]
    -> assist_teacher_dataset
    -> 监督四输出 AssistActor
    -> 留出受试者、trial 和场景评估
```

### 3.2 MyoAssist 在线训练和评估

```text
MyoAssist 原生 Observation
    -> 冻结的人体 Actor
    -> 22 维肌肉动作，按当前 MVP 的 50 Hz 更新

MyoAssist 状态
    -> MyoAssist sensor_adapter
    -> gexo_sensor32_runtime_v1
       |-> 50 帧 -> 共享 TCN runtime
       |   -> [delta_q(+5), delta_dq(+5), delta_q(+10), delta_dq(+10)]
       `-> 上一步实际施加的归一化动作 -> 36 维单帧 -> 4 帧 -> 144 维
    -> 160 维外骨骼 Observation
    -> 监督 AssistActor 或 PPO 四输出 Actor
    -> 共享 TorqueActuator
    -> 四路理想髋膝力矩，按 50 Hz 更新

[22 维肌肉动作, 4 维物理外骨骼力矩]
    -> MyoAssist / MuJoCo 动力学
    -> 下一状态、终止、安全和生理指标
```

人体 Actor 和外骨骼 Actor 的 Observation 必须是两条独立数据流。肌肉激活、完整
未来参考、未来真值、教师力矩和 MyoAssist 特权状态均不得进入部署 Actor。

### 3.3 Kinesis 的保留职责

Kinesis 继续负责：

- 冻结人体策略下的动态稳定性检查；
- 动态 G-Exo URDF、绑带、质量、碰撞和人机相对运动；
- 力矩方向、脉冲、剂量响应、功率、变化率和故障终止；
- baseline、teacher、AssistActor 的跨后端安全复核与渲染。

Kinesis 在线激活变化只作为该冻结控制器下的诊断，不再作为监督教师标签的唯一
生理真值。

## 4. 统一协议

### 4.1 四关节、单位与速率

| 项目 | 固定值 |
|---|---|
| 关节顺序 | `[left_hip, left_knee, right_hip, right_knee]` |
| 中文顺序 | `[左髋, 左膝, 右髋, 右膝]` |
| 角度 | `rad` |
| 角速度 | `rad/s` |
| 力矩 | `Nm` |
| IMU 角速度 | `rad/s`，各 IMU 局部坐标 |
| IMU 线性量 | `m/s^2` 的比力，而非世界坐标线加速度 |
| TCN 与外骨骼控制 | `50 Hz`，`dt = 0.02 s` |
| 人体 Actor 默认控制 | 当前 MVP 统一 `50 Hz` |
| MyoAssist 物理仿真 | 保持原配置的 `1200 Hz` |
| TCN 历史 | `50` 帧，即过去 `1 s` |
| TCN horizon | `+5`、`+10` 外骨骼控制步，即约 `100/200 ms` |
| TCN deployment feature | `[delta_q(+5), delta_dq(+5), delta_q(+10), delta_dq(+10)]` |
| Actor 输出 | 四维归一化动作，每维位于 `[-1, 1]` |
| 动作尺度 | `action_torque_scale_nm[4]`，将归一化动作映射为requested torque |
| 硬限矩 | `torque_limit_nm[4]`，逐项不小于动作尺度 |

虽然原 speed-control checkpoint 按30 Hz训练，一次严格关闭旧踝助力的交互式测试
在50 Hz下使0.8 m/s和1.25 m/s各三个独立episode走满1000步。该结果支持把50 Hz
作为当前MVP默认候选，MyoAssist每个控制步执行24个1200 Hz物理子步；但在独立
runner归档配置、报告、哈希和重复reset证据前，不能称为正式通过。

当前尚需修复并验证的是同一环境实例重复 `reset()` 的确定性。只有正确 reset 后的
50 Hz 多 seed 回归失败，才允许启用 30 Hz 人体 / 50 Hz 外骨骼时间累加回退。该
回退只能位于 MyoAssist adapter，不能写进共享 TCN、observation 或电机模块。

### 4.2 运行时 32 维协议

协议名：`gexo_sensor32_runtime_v1`。

| 索引 | 含义 |
|---|---|
| `0:4` | 四关节位置 q |
| `4:8` | 四关节速度 dq |
| `8:11` | 左大腿 IMU 角速度 xyz |
| `11:14` | 左小腿 IMU 角速度 xyz |
| `14:17` | 右大腿 IMU 角速度 xyz |
| `17:20` | 右小腿 IMU 角速度 xyz |
| `20:23` | 左大腿 IMU 比力 xyz |
| `23:26` | 左小腿 IMU 比力 xyz |
| `26:29` | 右大腿 IMU 比力 xyz |
| `29:32` | 右小腿 IMU 比力 xyz |

`RL/env/sensors.py` 中的 `SensorReader` 负责后端中立的物理量读取、shape/finite
检查、bias/noise、物理裁剪和上述 `runtime32` 排列。S-P1A 新增明确的
`read_runtime32(state) -> (32,)` API。现有 `read(state, previous_action) -> (36,)`
必须保留以兼容 Kinesis，但其实现改为调用 `read_runtime32()`，再委托
`RL/env/actor_observation.py` 的共享单帧 builder；不得在 `SensorReader` 内维护四帧
历史、执行 Actor 缩放或拼接 TCN 特征。

Phase 1/2 的旧 TCN 数据使用 `phase12_tcn32_interleaved_v1`：每个 IMU 依次排列
gyro 与 accel。`RL/env/actor_observation.py` 是运行时32维到该 TCN 排列转换的唯一
所有者。转换必须有版本和逐索引哨兵测试，禁止散落切片、隐式 `reshape` 或改变
已有 TCN checkpoint 所理解的通道含义。

### 4.3 144 与 160 维协议

单个 Actor 历史帧为：

```text
[gexo_sensor32_runtime_v1, previous_applied_action_4]
```

其中：

$$
previous\_applied\_action_t
=\frac{teacher\_applied\_torque\_nm_{t-1}}
{action\_torque\_scale\_nm}.
$$

Episode 第一帧固定 `previous_applied_action = [0, 0, 0, 0]`。36维单帧经过唯一的
Actor feature scale 后，最近四帧按“从旧到新”展平：

$$
4\times 36=144.
$$

TCN 原始预测是未来 `+5` 和 `+10` 步的四关节 q/dq。部署特征不是绝对未来状态，
而是相对当前 $q_t,\dot q_t$ 的增量，并严格按以下顺序排列：

$$
\Delta q_{t+h}=\hat q_{t+h}-q_t,
\qquad
\Delta\dot q_{t+h}=\hat{\dot q}_{t+h}-\dot q_t,
\qquad h\in\{5,10\}.
$$

```text
tcn_feature16_raw = [
    delta_q(+5) 4,
    delta_dq(+5) 4,
    delta_q(+10) 4,
    delta_dq(+10) 4,
]
```

因此共有：

$$
2\times(4+4)=16.
$$

每个特征使用 checkpoint/calibration 固定的训练期统计量和裁剪范围：

$$
z_k=\operatorname{clip}\left(
\frac{x_k-\mu_k}{\sigma_k},-c_k,c_k
\right),\qquad k=1,\ldots,16.
$$

`mean[16]`、`std[16]` 和固定 `clip` 必须随 checkpoint/calibration 写入 metadata；
当前 legacy calibration 的 `clip` 是广播到16维的标量。禁止用当前 episode 或
验证集重新估计。最终部署 Observation 为：

$$
o_t=[h_{144},z_{16}]\in\mathbb R^{160}.
$$

当前不把 64 维 TCN latent、预测的生物力矩、相位真值、肌肉状态或任务标签直接
输入 Actor。Episode reset 的四帧历史与 50 帧 TCN 历史填充规则必须唯一实现并
写入 checkpoint metadata。`RL/env/actor_observation.py` 唯一负责：

1. `runtime32 + previous_applied_action` 构造36维；
2. Actor单帧缩放和四帧144维历史；
3. runtime32到Phase TCN通道转换；
4. 按上述delta顺序、固定mean/std/clip处理16维特征；
5. 144与16维的最终拼接。

它不采集后端物理量，也不加载人体或仿真器。

MVP 不使用合成padding。reset后的启动规则固定为：

1. 清空人体策略、执行器、参考、TCN和Actor的全部时序状态；
2. 冻结人体在严格零外骨骼力矩下真实预滚动50个50 Hz控制步；
3. TCN缓存使用全部50个真实sensor32，Actor缓存使用最后4个真实36维帧，四帧的
   `previous_applied_action` 全为零；
4. 预滚动推进仿真时间与内部reference index，但不计入正式episode步数、训练回报、
   终止统计或教师标签；正式episode从预滚动后的状态和reference位置开始；
5. 预滚动跌倒、状态无效或参考提前结束必须使reset失败；不能改用填零或重复首帧；
6. 离线trial仅在同一trial中50帧TCN历史、4帧Actor历史及 `+10` horizon同时完整时
   生成样本；trial首尾无效样本拒绝，禁止跨trial/reset补齐。

该规则形成版本化 `gexo_zero_assist_preroll50_v1`，训练、仿真和实机初始化必须一致。

### 4.4 教师数据和 checkpoint metadata

每份教师数据至少记录：

- `schema_version`、`sensor_protocol`、`joint_order` 和单位；
- `actor_observation_protocol`、`tcn_feature_protocol` 和严格的16维delta顺序；
- `teacher_backend`、人体模型名称、版本与哈希；
- 教师策略 ID/路径和哈希；
- 控制频率、物理频率、TCN checkpoint 与 calibration 哈希；
- TCN feature 的 `mean[16]`、`std[16]`、固定 `clip` 及其来源哈希；
- 受试者、trial、场景、速度、seed 和数据划分；
- `tau_required`、`tau_human`、`tau_exo` 的物理含义和 shape；
- `action_torque_scale_nm[4]`、独立硬力矩上限、变化率、功率和滤波参数；
- `gexo_zero_assist_preroll50_v1` 启动协议及有效历史/horizon mask；
- 求解器状态、残差、有效 mask 与全部生理验收指标；
- 生成代码版本或文件哈希。

不同肌肉模型产生的标签不能无标记混合。Actor checkpoint 只有在160维排列、缩放、
关节正方向、TCN、calibration 和安全层完全一致时才能跨后端复用。

首版教师 NPZ 的核心数组和时序语义固定为：

```text
time_s                         [T]
sensor_runtime32               [T, 32]
tcn_feature16                  [T, 16]
tcn_valid                      [T]
teacher_requested_torque_nm    [T, 4]
teacher_requested_action       [T, 4]
teacher_applied_torque_nm      [T, 4]
previous_applied_action        [T, 4]
teacher_valid                  [T, 4]

tcn_feature16[t] = standardize_and_clip([
    delta_q(+5), delta_dq(+5), delta_q(+10), delta_dq(+10)
])

teacher_requested_action[t]
    = teacher_requested_torque_nm[t] / action_torque_scale_nm

teacher_applied_torque_nm[t]
    = torque_actuator(teacher_requested_action[t])

previous_applied_action[0] = zeros(4)
previous_applied_action[t]
    = teacher_applied_torque_nm[t - 1] / action_torque_scale_nm, t > 0

observation[t]
    = actor_history(state[0:t], previous_applied_action[0:t])
      + tcn_feature16[t]

label[t] = teacher_requested_action[t]
```

`requested` 是教师在当前时刻要求的物理力矩，`requested_action` 是用逐关节
`action_torque_scale_nm` 归一化后的监督标签，`applied` 是经过安全层后真正用于
仿真和下一帧历史的力矩。`observation[t]` 严禁包含当前
`teacher_requested_action[t]`、`teacher_requested_torque_nm[t]` 或
`teacher_applied_torque_nm[t]`，否则产生直接标签泄漏。

教师优化器必须把 `|teacher_requested_torque_nm| <= action_torque_scale_nm` 写成
显式约束。若现有教师标签超出 scale，数据生成器必须拒绝该样本或整条轨迹，不能
通过 `clip` 篡改标签。首版教师本身还必须满足变化率约束，并将安全层滤波时间常数
固定为零；否则 requested/applied 的标签语义和重复滤波会产生歧义。

动作尺度和硬限矩是两个逐关节向量，并必须满足：

$$
0 < action\_torque\_scale\_nm[j]
\le torque\_limit\_nm[j],\qquad j=1,\ldots,4.
$$

`TorqueActuator` 的兼容API增加可选 `action_torque_scale_nm`，未提供时默认复制
`torque_limit_nm`。处理顺序固定为：归一化动作乘scale、变化率限制、低通滤波、
hard limit最终裁剪。S-P1A必须审计全部调用者，并证明默认参数下旧输出逐元素相等。

## 5. 文件归属与严格边界

### 5.1 共享基础设施：只维护一份

现有并保持兼容复用：

| 文件 | 共享职责 |
|---|---|
| `RL/data/dataset_manifest.py` | 数据列、受试者与 trial 清单 |
| `RL/data/preprocess_tcn.py` | Phase 数据的 50 Hz 预处理 |
| `RL/data/tcn_dataset.py` | 因果历史与未来目标窗口 |
| `RL/runners/predictors/tcn.py` | `MotionTCN` 网络结构 |
| `RL/env/sensors.py` | 后端中立采集、检查、噪声/裁剪和 runtime32；保留 legacy `read()` |
| `RL/env/torque.py` | 四输出动作尺度、硬限矩、限速与滤波；兼容旧调用 |
| `RL/train.py` | 通用 SB3、并行环境、checkpoint 与 TensorBoard；当前不含监督 Actor 初始化钩子 |

计划新增：

| 文件 | 唯一职责 |
|---|---|
| `RL/optimization/contracts.py` | `MuscleSnapshot`、`TrajectoryInput`、`TeacherSolution` 数据契约 |
| `RL/optimization/fixed_trajectory.py` | 后端无关的整周期肌肉--外骨骼优化 |
| `RL/metrics/physiology.py` | 纯 NumPy 生理指标 |
| `RL/env/actor_observation.py` | 唯一负责36/144/160组帧、缩放、TCN通道转换和delta16 |
| `RL/runners/predictors/tcn_runtime.py` | checkpoint、50 帧缓存、归一化和冻结推理 |
| `RL/data/assist_teacher_dataset.py` | 教师 NPZ 校验、切分和训练窗口 |
| `RL/runners/predictors/assist_actor.py` | 四输出监督 AssistActor |
| `RL/runners/generate_assist_teacher.py` | 教师数据生成入口 |
| `RL/runners/train_assist_actor.py` | 监督训练、验证和 checkpoint |
| `RL/runners/evaluate_assist_actor.py` | baseline/teacher/Actor 统一评估 |
| `RL/tests/test_shared_protocol.py` | 通道、shape、顺序、因果与 reset 测试 |
| `RL/tests/test_actor_observation.py` | previous-applied时序、delta16、缩放和160维测试 |
| `RL/tests/test_physiology.py` | 指标人工样例和不抵消性质 |
| `RL/tests/test_fixed_trajectory.py` | 合成肌肉系统的力矩平衡与约束测试 |
| `RL/tests/test_assist_teacher_dataset.py` | metadata、mask 和 split 测试 |

共享模块不得 import `myoassist`、`Kinesis`、具体环境或 MuJoCo 模型名称。共享
优化器只能读取纯数组契约；共享 Actor 只能读取160维部署 Observation。

S-P1A 允许对现有 `RL/env/sensors.py` 做一次兼容修改：新增 `read_runtime32()`，并让
原 `read()` 委托 `read_runtime32()` 与共享单帧 builder。该修改必须使用冻结输入
逐元素比较修改前后 Kinesis 36维输出，最大误差为0才允许通过；不得趁机改变噪声、
裁剪、dtype、通道顺序或旧调用签名。

### 5.2 MyoAssist 后端专属：由另一分支实现

```text
RL/env/myoassist/
    gexo_leg_env.py
    sensor_adapter.py
    muscle_adapter.py
    policy_transfer.py

RL/assets/myoassist/
    四髋膝理想执行器模型或生成配置

RL/runners/
    train_myoassist_gexo.py
    evaluate_myoassist_gexo.py
```

- `gexo_leg_env.py`：组合冻结人体动作、四外骨骼动作、50 Hz 调度和 Gymnasium
  接口；
- `sensor_adapter.py`：负责 MyoAssist joint/body/site 到运行时32维协议的标定；
- `muscle_adapter.py`：唯一负责读取 MyoAssist 肌肉力、力臂、激活上下界和动力学
  系数，并输出 `MuscleSnapshot`；
- `policy_transfer.py`：加载22肌肉人体 checkpoint、显式冻结并验证参数哈希；
- 模型资产：增加左右髋膝四路理想力矩，首版不接完整 URDF；
- 两个 runner：复用共享训练器与评价协议，不复制 PPO 算法。

MyoAssist 的 joint/body/muscle/actuator 名称只能出现在这些专属文件或专属资产中。

### 5.3 Kinesis 后端专属

`RL/env/kinesis/**` 继续拥有 Kinesis 教师、坐标标定、动态 URDF、绑带、baseline、
Reward 和渲染。路线 A 不修改这些文件，只把现有实现当作只读对照：

- 新中立生理指标对同一数组输入必须与现有 Kinesis 纯 NumPy 公式数值等价；
- 新共享 TCN runtime 对同一 checkpoint、calibration 和历史必须与现有 Kinesis
  adapter 的预测数值等价；
- 新 observation builder 对冻结输入必须与现有 Kinesis 36/144/160 组帧逐元素等价；
- Kinesis 若以后切换为兼容重新导出或共享 runtime，由 Kinesis 分支单独实施和回归，
  不属于本路线的修改范围；
- Kinesis 专属 `MuscleLoadSharing` 不得被 MyoAssist 环境直接 import；
- 如需固定轨迹 Kinesis 教师，另建 `RL/env/kinesis/muscle_adapter.py`，不得向共享
  优化器写入 Kinesis 名称。

### 5.4 第三方目录

`third_party/myoassist/**` 默认只读，包括当前的：

- `rl_train/envs/myoassist_leg_base.py`；
- `rl_train/envs/myoassist_leg_imitation.py`；
- `rl_train/envs/myoassist_leg_imitation_exo.py`。

复用通过继承、组合、wrapper 和模型生成完成。第三方修改必须单独提出、获得用户
授权、记录上游哈希和回退方法，并由另一 agent 独立 review。

## 6. 固定轨迹教师优化

### 6.1 输入与力矩平衡

对固定参考轨迹输入：

$$
q_t,\quad \dot q_t,\quad \ddot q_t,\quad \tau_{required,t}.
$$

后端 adapter 在每个时刻提供肌肉力臂和力模型。首版允许用显式声明的局部仿射
模型：

$$
F_t=F_{passive,t}+G_ta_t,
$$

但该近似、有效范围和来源必须写入 metadata。肌肉和外骨骼必须满足：

$$
R_t^TF_t+S(q_t)\tau_{exo,t}=\tau_{required,t}.
$$

其中 $R_t\in\mathbb R^{M\times4}$，$S(q_t)$ 是电机轴力矩到人体关节等效力矩的
映射。首版 MyoAssist 理想关节执行器可以显式使用单位映射；Kinesis 动态 URDF
复核不能假设该映射永久为单位阵。

### 6.2 无助力和有助力必须配对

同一条轨迹、同一肌肉模型和同一有效 mask 分别求解：

1. baseline：固定 $\tau_{exo,t}=0$；
2. assisted：允许四关节 $\tau_{exo,t}$，同时施加相同人体动力学约束。

禁止使用两个不同轨迹或两个不同时间索引比较“省力”。任何不可行帧必须保存 mask
和求解状态，不能用零值替代后混入训练。

### 6.3 生理与机械指标

至少计算：

$$
J_{act}=\sum_t\sum_{i\in\mathcal M_{target}}w_i a_{i,t}^2\Delta t,
$$

$$
J_{net}=\sum_t\sum_{j\in\mathcal J}w_j
\left(\frac{\tau_{human,j,t}}{\tau_{scale,j}}\right)^2\Delta t,
$$

$$
J_{gross}=\sum_t\sum_j\sum_{i\in\mathcal M_{target}}
|r_{ij,t}F_{i,t}|\Delta t,
$$

$$
J_{human\_work}^{+}=\sum_t\sum_j
\max(\tau_{human,j,t}\dot q_{j,t},0)\Delta t.
$$

还必须报告逐关节、逐肌肉、主动/拮抗贡献、共收缩和局部过载，防止平均值掩盖
某个关节或少数肌肉恶化。

三类量的职责固定，监督教师与在线 PPO 不得自行交换：

- $J_{act}$ 是共同的主要生理代价，反映肌肉募集强度；
- $J_{net}$ 是共同的主要机械卸载量，也是动力学平衡必须满足的关节级结果；
- $J_{gross}$ 不代表净关节需求，专门阻止拮抗肌抵消、共收缩和局部负担转移，作为
  不恶化约束、辅助惩罚和报告量，不单独替代前两项。

因此，路线 A 的教师必须同时改善 $J_{act}$ 与 $J_{net}$，并约束 $J_{gross}$；路线 B
的 PPO 也必须以激活和人体净关节力矩为 effort 信号，同时对 gross 恶化设软铰链或
硬门。只优化 activation、只优化 net 或只优化 gross 都不满足共享评价协议。

### 6.4 优化目标与硬约束

不使用“只最小化激活”迫使电机撞击上限。先扫描目标卸载比例
$\rho\in\{5\%,10\%,15\%,\ldots\}$，在满足卸载与不恶化约束时最小化电机代价：

$$
\min_{a,u,\tau_{exo}}
J_{motor}+\lambda_sJ_{smooth}+\lambda_bJ_{interaction},
$$

$$
J_{motor}=\sum_t\left(
w_\tau\|\tau_{exo,t}\|_2^2
+w_p\left|\tau_{exo,t}\odot\dot q_t\right|_1
\right)\Delta t,
$$

$$
J_{smooth}=\sum_{t=1}^{T-1}
\|\tau_{exo,t+1}-2\tau_{exo,t}+\tau_{exo,t-1}\|_2^2.
$$

约束至少包括：

$$
J_{act}^{exo}\le(1-\rho_a)J_{act}^{0},
\qquad
J_{net}^{exo}\le(1-\rho_\tau)J_{net}^{0},
$$

$$
J_{gross}^{exo}\le(1+\delta_g)J_{gross}^{0},
\qquad
J_{net,j}^{exo}\le(1+\delta_j)J_{net,j}^{0},
$$

$$
0\le a_{i,t}\le1,
\qquad
a_{t+1}=f(a_t,u_t),
$$

$$
|\tau_{exo,t}|\le\tau_{max},
\qquad
|\tau_{exo,t}-\tau_{exo,t-1}|\le\dot\tau_{max}\Delta t,
$$

$$
|\tau_{exo,t}|\le action\_torque\_scale\_nm,
$$

$$
|\tau_{exo,t}\odot\dot q_t|\le P_{max}.
$$

周期轨迹还必须约束首尾连续。求解不可行时应降低目标卸载、输出 Pareto 结果并标记
不可行原因，禁止静默放宽硬件限制或伪造标签。

只有轨迹本身是完整步态周期时才约束首尾连续；普通有限 trial 不得被强行闭合。
优化解还必须交回原后端，用真实肌肉激活动力学和统一 `TorqueActuator` 重放。若
重放后的激活、实际力矩或安全层输出不再满足教师约束，该解直接作废，不能保存为
训练标签。

### 6.5 教师进入监督训练前的门槛

先用合成肌肉系统验证数学实现；路线 B 的 B-P6 `muscle_adapter` 独立 `PASS` 后，
再用至少三条代表性真实轨迹完成 S-P2 教师审计。
每条候选教师曲线必须同时满足：

- 无助力与有助力使用同一轨迹、模型、时间轴和有效 mask；
- 力矩平衡 RMS 相对残差不高于 1%，峰值相对残差不高于 5%；
- $J_{act}$ 与 $J_{net}$ 同时下降，不能只通过其中一项；
- $J_{gross}$、任一单关节和局部过载不明显恶化；
- 人体正功下降或不恶化，正负功分开报告；
- 电机峰值、RMS、变化率、功率和安全层参数全部合法；
- 力矩二阶差分、周期首尾和肌肉激活动力学连续；
- 多个卸载目标形成合理 Pareto 曲线，而非所有解都撞击上限；
- 标签有限、可复现，求解器失败和无效帧有显式 mask；
- 后端真实激活动力学重放的最大激活误差不高于 $10^{-3}$；
- `TorqueActuator` 重放不改变教师力矩，否则该标签不具备部署一致性；
- 由非编辑 agent 复算关键公式并给出 `PASS`。

若激活平方与人体净关节力矩不能在三条轨迹上稳定同时改善，则停止生成大规模教师
数据，先检查单位、力矩正方向、肌肉力臂、目标肌肉集合和 $S(q)$。

## 7. 监督 AssistActor

AssistActor 只接受 $[h_{144},z_{16}]$ 部署 Observation，其中 $z_{16}$ 固定为
`[delta_q(+5), delta_dq(+5), delta_q(+10), delta_dq(+10)]` 经 checkpoint/
calibration 的 mean/std/clip 处理后的结果；Actor 输出四维归一化动作。TCN 在首版
监督训练中冻结。基础损失为：

$$
\mathcal L_{actor}
=\|\hat a_t-a_t^{*}\|_1
+\lambda_s\|\Delta^2\hat a_t\|_2^2,
\qquad
a_t^{*}=\tau_{exo,t}^{*}/action\_torque\_scale\_nm.
$$

训练损失统一在归一化action空间计算；MAE/RMSE评估同时将预测和标签乘相同逐关节
scale后以Nm报告。禁止把归一化action与物理torque直接放在同一个差值中。

数据必须按受试者和 trial 划分，禁止随机拆帧导致相邻窗口泄漏。归一化统计只由
训练集计算。由于二阶平滑项需要连续时间，Dataset 不能随机返回彼此无关的单帧，
而应返回同一 trial 内不跨 reset 和无效区间的连续短序列：

```text
observation [sequence, 160]
target      [sequence, 4]
mask        [sequence, 4]
```

首版序列长度暂定为16并做成配置项。二阶差分只能沿该时间维计算，不能沿打乱后的
batch 顺序计算。监督模型进入 PPO 初始化前必须：

- 在留出受试者/trial 上优于零输出、均值力矩和保持上一力矩三个基线；
- 四关节分别报告 MAE、RMSE、相关性和峰值误差；
- 通过因果遮挡测试，修改未来数据不能改变当前输出；
- 输出经共享安全层后仍保持教师方向与主要时序结构；
- 保存完整协议、TCN、归一化和教师数据 metadata；
- 能确定性保存、加载并复现同一批输出。

最小 checkpoint 归档包括 `config.json`、`history.json`、`best_model.pt`、
`last_model.pt`、`summary.json`、`validation_report.json` 和 `tensorboard/`。最佳
模型按验证集 normalized-action L1 选择，同时报告逐关节 Nm MAE；不使用 test split
早停或选模型。

路线 A 的正式 PPO 只允许从监督 Actor 初始化或围绕它学习有界 residual。路线 B
可以先用 fresh PPO 做环境、奖励和保存恢复 smoke；只有 B-P8 通过且 fresh PPO 在
预注册的同条件成对 holdout 上改善激活/人体净关节力矩、gross 不恶化并保持速度与
站立后，才可形成“在当前 MyoAssist 二维模型中有效”的路线 B 结论。该结论不能替代
路线 A 的教师或监督初始化证据，也不能外推真人、URDF、转向或楼梯。现有
`RL/train.py` 的 `resume_from` 只恢复 PPO，不是监督 Actor 初始化；共享 S-P4 必须
新增显式参数映射钩子和等价测试。

## 8. 分阶段实施顺序

所有步骤都遵循“编辑 -> 自检 -> 不同 agent review/独立测试 -> PASS 后下一步”。

| 阶段 | 实施内容 | 主要文件 | 进入下一阶段的证据 |
|---|---|---|---|
| S-P0 | 本计划、边界和归档制度 | 两份计划文档、实施日志 | 文档 review PASS，无代码变化 |
| S-P1A | runtime32、observation、动作尺度与兼容委托 | `contracts.py`、`sensors.py`、`actor_observation.py`、`torque.py` | 职责边界、32/36/144/160、preroll50、动作尺度及旧行为逐元素等价 PASS |
| S-P1B | 中立生理指标与只读 Kinesis 等价审计 | `metrics/physiology.py`、共享测试 | 人工公式测试和只读旧实现数值等价 PASS；不改 Kinesis |
| S-P1C | 共享 TCN runtime 与只读等价审计 | `tcn_runtime.py`、共享测试 | 推理等价、因果、delta顺序、固定mean/std/clip PASS；不改 Kinesis adapter |
| S-P1D | 固定轨迹优化器骨架 | `fixed_trajectory.py` | 合成系统平衡、边界、连续性 PASS |
| S-P1E | 教师数据集与 AssistActor | dataset、Actor、runner | requested/applied时序、无泄漏、超scale拒绝、端到端 PASS |
| S-P2 | 真实固定轨迹教师 | 共享教师生成 runner 与报告 | 消费已 review 的 B-P6 `MuscleSnapshot`；不编辑 MyoAssist 后端；三条轨迹教师门 PASS |
| S-P3 | 监督 AssistActor | 共享训练/评估 runner | 留出集、因果性和安全层门全部 PASS |
| S-P4 | PPO 监督初始化钩子 | `RL/train.py` 的通用显式权重映射 | 参数逐层映射、输出等价、失败拒绝和 resume 兼容 PASS |
| S-P5 | 共享配对评估协议 | 中立报告 schema/evaluator | baseline/teacher/Actor 同条件报告 PASS |
| S-P8 | 新 agent 整体 review | 仅共享/路线A实际 diff 和测试 | 共享训练前清单逐项有权威证据 |

S-P1A--S-P1E 可以在不等待真实 MyoAssist 后端时用合成数据实现和测试，但 S-P2 的
真实教师数据依赖路线 B 提供经过 review 的 B-P6
`RL/env/myoassist/muscle_adapter.py`。共享路线只消费该契约，不拥有或修改该文件。

## 9. 每个变更单元的编辑与 review 流程

每个小步骤严格执行：

1. 编辑 agent 在实施日志追加 `PLANNED` 记录，列出允许修改文件和数据流；
2. 重新读取文件并计算修改前 SHA-256，发现并行变化时停止覆盖并重新审计；
3. 只编辑本步骤文件，不顺带清理或重构；
4. 运行最小自检，记录工作目录、环境、完整命令、退出码和关键输出；
5. 将状态记为 `EDITED，待独立 review`；
6. 父 agent 分配一个未参与本步骤编辑的 review agent；
7. reviewer 必须读取实际 diff、检查边界、独立运行单元测试或审计命令；
8. reviewer 在日志追加 `PASS`、`REWORK` 或 `BLOCKED`，不得覆盖编辑者记录；
9. `REWORK` 由编辑 agent 修复后重新提交另一次 review；
10. 只有 `PASS` 后才能开始依赖该步骤的下一项工作；
11. S-P0--S-P5 全部 PASS 后，由此前未参与这些编辑的更新 agent 执行 S-P8 整体 review。

编辑者自测不能替代 reviewer 测试。编译成功不能替代接口、物理语义、因果性或
跨后端等价性测试。

## 10. 变更归档规则

统一账本为 `RL/MYOASSIST_PPO_IMPLEMENTATION_LOG.md`，只追加，不覆写历史结论。
每条记录至少包含：

- 记录 ID、时间、阶段、状态、编辑和 review agent；
- 目标、非目标、用户授权和允许修改文件；
- 修改前后数据流和实际修改文件；
- 修改前后 SHA-256；
- 兼容性、已知限制和回退方法；
- 自检命令、reviewer 独立命令、退出码与关键结果；
- 证据、报告、生成资产和 checkpoint 路径及哈希；
- 下一步和依赖关系。

由于当前根 Git 将 `G-Exo/` 和 `third_party/` 整体显示为未跟踪，不能用 Git 历史
推断文件所有权。所有既有文件默认视为用户所有；每一步只允许编辑日志中明确列出
的文件。并行分支修改共享文件时，以重新读取和哈希审计后的当前内容为准，不回退
他人变化。

## 11. 正式训练前验收清单

以下项目必须逐项有权威证据，不能用“没有报错”概括：

### 11.1 架构与隔离

- [ ] 共享模块没有 import MyoAssist、Kinesis 或具体模型名称；
- [ ] `third_party/myoassist/**` 没有变化，或存在用户授权的独立补丁记录；
- [ ] Kinesis 历史行为和 checkpoint 兼容性测试通过；
- [ ] MyoAssist 与 Kinesis 只通过版本化纯数组契约连接共享层。

### 11.2 传感器、TCN 与 Actor

- [ ] 32维索引、单位、局部坐标和比力语义逐项通过；
- [ ] `SensorReader.read_runtime32()`只负责采集/检查/噪声/裁剪，`read()`兼容委托；
- [ ] Kinesis legacy 36维输出在兼容修改前后逐元素完全一致；
- [ ] `actor_observation.py`唯一拥有36/144/160组帧、缩放和TCN通道转换；
- [ ] 运行时与 Phase TCN 通道转换逐索引通过；
- [ ] 四帧历史顺序、reset 填充和144维缩放唯一且有 metadata；
- [ ] 第一帧 previous-applied action 为0，其后只使用上一帧实际施加动作；
- [ ] Observation不含当前requested/applied action或其他标签泄漏；
- [ ] reset真实零助力预滚动50步，TCN取50帧、Actor取最后4帧且不计训练回报；
- [ ] 离线样本不跨trial/reset填充，历史和 `+10` horizon必须同时完整；
- [ ] TCN 只读取当前及过去50帧，delta16严格按
  `[delta_q(+5), delta_dq(+5), delta_q(+10), delta_dq(+10)]` 排列；
- [ ] delta相对当前q/dq，使用checkpoint/calibration固定mean/std/clip；
- [ ] Actor Observation 固定为160维且不含特权信息；
- [ ] TCN 和监督 Actor checkpoint 可确定性保存、加载和复现。

### 11.3 MyoAssist 人体与外骨骼物理

- [ ] 22肌肉人体 Actor 参数在外骨骼训练前后哈希不变；
- [ ] 50 Hz人体/外骨骼和1200 Hz物理的24子步调度时间戳正确；
- [ ] 同一环境连续reset没有qpos/qvel/act/ctrl、参考索引、计时器或历史缓存泄漏；
- [ ] 零助力四路执行器严格输出0 Nm；
- [ ] 左髋、左膝、右髋、右膝正负脉冲方向全部正确；
- [ ] 零助力人体在目标速度和多个seed上复现基线；
- [ ] 小力矩产生连续、可重复且有方向的状态与肌肉剂量响应；
- [ ] 共享安全层确实位于策略动作和MuJoCo执行器之间。
- [ ] 动作尺度逐项不大于硬限矩，默认尺度保持旧 `TorqueActuator` 输出逐元素等价；

### 11.4 教师与生理指标

- [ ] `MuscleSnapshot` 的力臂、力、激活和四关节映射有独立测试；
- [ ] 合成系统固定轨迹优化满足力矩平衡、边界和时序连续性；
- [ ] 至少三条真实轨迹的 baseline/assisted 配对教师门全部 PASS；
- [ ] 激活平方和人体净关节力矩同时改善；
- [ ] 非抵消肌肉负担、共收缩、局部过载和正负功分别报告；
- [ ] 教师数据包含模型、协议、求解器、mask 和安全 metadata；
- [ ] requested torque/action、applied torque和previous-applied action语义逐帧一致；
- [ ] requested torque超出action scale会被优化约束阻止或拒绝，绝不静默clip；
- [ ] 求解失败帧未以零标签混入训练。

### 11.5 训练基础设施

- [ ] 监督 Actor 在留出数据上优于零、均值和保持值基线；
- [ ] Gymnasium `check_env` 通过；
- [ ] 8-worker smoke 无 NaN、死锁、异常 reset 或数据泄漏；
- [ ] TensorBoard 包含回报、生理、安全、力矩和终止指标；
- [ ] checkpoint 保存/恢复后步数、参数和输出一致；
- [ ] baseline/teacher/Actor 能在同 seed、同初态下配对评估；
- [ ] S-P0--S-P5 每一步均有不同 agent 的 PASS；
- [ ] S-P8 新 reviewer 完成整体架构、测试覆盖和训练前审计。

只有全部必要项通过，才能给出正式训练指令。通过流水线 smoke 不等于策略有效，
正式训练后的有效性仍须由留出数据、配对仿真和最终实机实验验证。

## 12. 当前已知阻塞与并行接口

当前共享层可以立即推进到合成数据端到端测试，但固定轨迹优化器的求解依赖尚未
决策。整周期力矩平衡、激活动力学、限矩、限速、功率和卸载约束适合由 CVXPY 或
同等级凸优化器统一表达；现有逐帧 `scipy.optimize.lsq_linear` 只能作为较弱的分步
近似，不能直接实现完整问题。边界文档当前又限制共享模块依赖范围。因此在 S-P1D
开始前必须由用户选择并归档：

1. 允许 `RL/optimization` 引入 CVXPY/凸求解器；或
2. 明确接受 SciPy 分步近似，并强制执行后端重放与更严格的标签拒绝门。

不得为了继续推进而静默选择依赖或删掉约束。

真实教师数据还有一个明确外部依赖：

> 另一分支必须提供经过独立 review 的
> `RL/env/myoassist/muscle_adapter.py`，能够从指定固定轨迹输出版本化
> `MuscleSnapshot`，包括肌肉激活边界、肌肉力或主动增益、被动力、四关节力臂、
> 目标肌肉 mask、时间戳、模型哈希和有效性状态。

在该 adapter 到位前：

- 可以完成共享契约、指标、优化器合成测试、教师数据格式和 AssistActor smoke；
- 不能生成真实 MyoAssist 教师标签；
- 不能声称固定轨迹优化在人体现实模型上可行；
- 不能以合成标签启动正式外骨骼训练。

若 adapter 输出不能同时满足力矩平衡和生理指标需要，必须由两分支共同审计接口，
不得在共享优化器中加入 MyoAssist 特例。

Phase 1/2 数据还需在教师生成前解决两个数据语义问题：

- `moment_filt_bio` 当前以 `Nm/kg` 存储，必须获得受试者质量或把质量作为明确条件，
  不能直接当成绝对 `Nm`；
- 必须核实助力 `on` trial 的生物力矩是否已经扣除了外骨骼贡献。首版优先从 `off`
  trial 建立总需求力矩，避免把已有助力重复计算。

四关节数据本身也不足以唯一恢复完整肌肉长度和力臂；`muscle_adapter` 必须在完整
模型姿态上生成 snapshot。理想 MyoAssist 首版可以令 $S(q)=I$，但不能据此声称已经
约束动态 URDF 的绑带力。

## 13. 当前下一步

1. 由未参与本文编辑的 agent review S-P0 文档并独立核对现有代码事实；
2. S-P0 PASS 后开始 S-P1A，新增中立契约与 actor observation，并按兼容门最小修改
   `sensors.py`；
3. 每个小步骤 PASS 后按第8节继续；
4. 另一分支并行实现 MyoAssist 四髋膝模型、冻结人体 wrapper 和
   `muscle_adapter.py`；
5. 路线 B 的 B-P6 muscle adapter 通过后，两路在 S-P2 的共享教师生成入口汇合，
   之后才进入路线 A 的监督 Actor 和监督初始化 PPO。
