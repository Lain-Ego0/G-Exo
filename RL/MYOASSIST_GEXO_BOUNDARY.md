# MyoAssist / G-Exo 复用与隔离边界

状态：执行约束，2026-08-03 建立。

本文是 MyoAssist 路线接入 G-Exo 主线时的边界契约。它不覆盖 Kinesis 已完成的
实现，也不授权清理、重命名或重写现有文件。发生实现便利与本文冲突时，先停止
修改并更新设计决定，不能用临时兼容代码绕过协议。

文档权威层级固定为：

1. 本文定义共享、后端与第三方的硬边界，以及跨路线共同协议；
2. `RL/SHARED_SUPERVISED_PIPELINE_PLAN.md` 只负责路线 A 和共享基础设施；
3. `RL/MYOASSIST_GEXO_PPO_PLAN.md` 只负责路线 B 的 MyoAssist PPO；
4. `RL/MYOASSIST_PPO_IMPLEMENTATION_LOG.md` 只记录事实和证据，不覆盖设计文档；
5. 路线计划与本文冲突时以本文为准；共享协议与路线局部便利冲突时以共享协议为准。

共享计划的阶段使用 `S-P*`，MyoAssist PPO 计划使用 `B-P*`。两个命名空间互不表示
前后依赖；跨路线依赖必须写出具体产物和验收门，不能只引用相同数字的阶段名。
路线 A 独占共享教师、监督 AssistActor 和监督 PPO 初始化；路线 B 独占 MyoAssist
模型、adapter、fresh PPO 环境和训练 runner。路线 B 可以在自身 action-sensitivity
与训练前门通过后执行 fresh PPO 候选训练，不以路线 A 的监督模型为前置；只有预注册
的成对 holdout 门通过后，才能形成“在当前 MyoAssist 二维模型中有效”的有限结论。
该结论不能替代路线 A 的监督证据，也不能外推真人、URDF 或未建模场景。

| 产物范围 | 唯一 owner | 其他路线权限 |
|---|---|---|
| `RL/optimization/**`、`RL/metrics/**`、共享 TCN/Observation、安全层、教师数据与 AssistActor | 路线 A / 共享基础设施 | 路线 B、Kinesis 只能按版本化契约调用 |
| `RL/env/myoassist/**`、`RL/assets/myoassist/**`、MyoAssist train/evaluate runner | 路线 B | 路线 A 只能消费通过 review 的 `MuscleSnapshot` 和报告，不得编辑 |
| `RL/env/kinesis/**`、动态 URDF、Kinesis calibration 与 runner | Kinesis 分支 | 路线 A/B 只能通过兼容测试后的共享接口调用，不得顺带编辑 |
| `third_party/myoassist/**`、`third_party/Kinesis/**` | 上游第三方，只读 | 无明确授权不得修改 |

每个实施记录必须列出 owner 与消费者。任何文件只能出现在一个路线的“实际修改”栏；
另一条路线即便依赖它，也只能记录输入哈希和验收状态。

## 1. 当前目标与明确不做的内容

当前 MVP 使用 MyoAssist 的 22 肌肉二维人体和四个理想关节力矩执行器，推进到
正式 PPO 训练前的全部验证门：

1. 从已有 22 肌肉人体策略迁移权重，在无旧踝硬件惯量的 BASELINE 模型上完成
   零外骨骼短程适配，验收后冻结为人体基座；
2. 在左右髋、左右膝加入四路理想外骨骼关节力矩；
3. 将 MyoAssist 状态转换为统一 32 维部署传感器；
4. 运行共享的 50 Hz 因果 TCN；
5. 构造 160 维外骨骼 Actor Observation；
6. 复用统一电机安全层；
7. 提取统一肌肉生理指标；
8. 打通 Gymnasium、并行环境、PPO 冒烟、保存/恢复和配对评估。

本阶段明确不做：

- 不接入现有 G-Exo URDF、连杆、绑带、质量或碰撞；
- 不开启质量、摩擦、传感器、延迟、地形等域随机化；
- 不修改 Kinesis 的动态 URDF、人体策略或仿真后端；
- 不联合更新 22 肌肉人体策略和外骨骼策略；人体适配阶段四路外骨骼必须严格为零，
  外骨骼 PPO 阶段人体策略必须冻结；
- 不宣称二维模型支持三维转向、侧向稳定或真实上下楼梯；
- 不把仿真肌肉指标直接表述为真人代谢下降。

因此，首版能力边界是二维矢状面内的平地直行和变速行走。转向、楼梯、斜坡、
URDF 和域随机化属于通过当前训练前验收后的后续阶段。

## 2. 统一数据流

```text
Phase 1/2 数据或 MyoAssist 仿真状态
    -> 后端传感器标定
    -> G-Exo 统一 32 维部署传感器
       |-> 最近 50 帧 -> 50 Hz 因果 TCN
       |   -> 相对当前状态的 +5/+10 步 q/dq 增量
       |   -> 固定 mean/std/clip -> 16 维部署特征
       `-> 加上一步实际施加动作成为 36 维 -> 最近 4 帧成为 144 维
    -> [144 维历史, 16 维归一化增量] = 160 维 Actor Observation
    -> 四输出外骨骼 Actor
    -> 统一限矩、限速和滤波
    -> MyoAssist 四路理想髋膝力矩

released 22-muscle checkpoint
    -> BASELINE + zero G-Exo torque 上短程适配
    -> 验收并冻结的人体 Actor

MyoAssist 原生 Observation
    -> 冻结的人体 Actor
    -> 22 维肌肉动作

[22 维肌肉动作, 4 维物理外骨骼力矩]
    -> MyoAssist / MuJoCo 动力学
    -> 下一仿真状态与统一生理指标
```

人体 Actor 的原生 Observation 与外骨骼 Actor 的部署 Observation 是两条独立
数据流。不得把人体肌肉激活、完整参考轨迹、未来真值或 MyoAssist 特权状态泄漏给
外骨骼 Actor。

## 3. 固定协议

### 3.1 关节、单位和频率

| 项目 | 固定值 |
|---|---|
| 关节顺序 | `[左髋, 左膝, 右髋, 右膝]` |
| 角度 | `rad` |
| 角速度 | `rad/s` |
| 力矩 | `Nm` |
| IMU 角速度 | `rad/s`，各 IMU 局部坐标 |
| IMU 线性量 | `m/s^2` 的比力，不是世界坐标线加速度 |
| TCN 采样频率 | `50 Hz` |
| TCN 外部输入 | `[time=50, channel=32]` |
| TCN PyTorch 输入 | `[batch, channel=32, time=50]` |
| TCN 网络原始输出 | `+5`、`+10` 控制步的四关节绝对 q/dq |
| TCN 部署特征 | 相对当前 q/dq 的 `delta_q(+5), delta_dq(+5), delta_q(+10), delta_dq(+10)`，再用固定统计归一化和裁剪，共 16 维 |
| Actor 输入 | 144 维短历史 + 16 维 TCN 显式预测 = 160 维 |
| Actor 输出 | 4 维归一化动作，逐项限制在 `[-1, 1]` |

TCN 的 `+5` 和 `+10` 步分别对应约 100 ms 和 200 ms。若以后改变频率或 horizon，
必须升级协议版本并重新训练或显式迁移 checkpoint，不能只改变数组形状。

### 3.2 统一 32 维运行时顺序

运行时协议名暂定为 `gexo_sensor32_runtime_v1`。索引定义如下：

| 索引 | 内容 |
|---|---|
| `0:4` | 四关节位置 q，顺序为左髋、左膝、右髋、右膝 |
| `4:8` | 四关节速度 dq，同一顺序 |
| `8:11` | 左大腿 IMU 角速度 xyz |
| `11:14` | 左小腿 IMU 角速度 xyz |
| `14:17` | 右大腿 IMU 角速度 xyz |
| `17:20` | 右小腿 IMU 角速度 xyz |
| `20:23` | 左大腿 IMU 比力 xyz |
| `23:26` | 左小腿 IMU 比力 xyz |
| `26:29` | 右大腿 IMU 比力 xyz |
| `29:32` | 右小腿 IMU 比力 xyz |

36 维 Actor 单帧固定为：

```text
[gexo_sensor32_runtime_v1, previous_applied_action_4]
```

其中
`previous_applied_action[t] = applied_torque_nm[t - 1] / action_torque_scale_nm`，
Episode 的第一帧固定为零。当前时刻 requested/applied action 不能进入当前
Observation。

最近四个单帧按从旧到新的顺序展平为144维。MVP 的 reset/warmup 规则固定为：

1. reset 后清空人体策略状态、执行器状态、参考索引、TCN 50帧缓存和Actor四帧缓存；
2. 冻结人体在严格零外骨骼力矩下真实预滚动50个50 Hz控制步；
3. TCN 使用这50个真实 sensor32，Actor history使用最后4个真实36维帧，四帧中的
   `previous_applied_action` 均为零；
4. 预滚动推进仿真时间和内部参考索引，但不计入策略episode步数、训练回报、终止
   统计或教师标签；正式 episode 从预滚动后的状态和参考位置开始；
5. 预滚动期间跌倒或参考结束视为 reset 失败，不能用填零或重复首帧掩盖；
6. 离线数据只保留同一 trial 内50帧历史、四帧Actor历史和 `+10` horizon 都完整的
   时刻；trial 前部和尾部无效样本直接拒绝，禁止跨 trial/reset 填充。

训练、仿真和实机启动必须使用同一规则，并把规则版本写入checkpoint metadata。

### 3.3 动作尺度与硬安全上限

每个关节分别定义 Actor 动作尺度 `action_torque_scale_nm[j]` 和最终硬限矩
`torque_limit_nm[j]`，并满足：

$$
0 < action\_torque\_scale\_nm[j]
\le torque\_limit\_nm[j].
$$

归一化动作先乘动作尺度得到 requested torque，之后经过变化率限制和滤波，最后再
由硬限矩裁剪。`TorqueActuator` 必须增加可选逐关节 `action_torque_scale_nm`；省略
时默认等于 `torque_limit_nm`，从而保持现有调用逐元素等价。教师标签超出动作尺度
时必须由优化约束阻止或拒绝，禁止静默裁剪后继续保存。

### 3.4 已确认的 32 维顺序冲突

现存数据并非只有一种 32 维排列：

- `RL/env/sensors.py` 先排列全部四个 IMU 的角速度，再排列全部四个 IMU 的比力；
- `RL/data/dataset_manifest.py` 按每个 IMU 依次排列 `gyro xyz, accel xyz`，即
  左大腿、左小腿、右大腿、右小腿逐个交错。

已有 Phase 1/2 TCN checkpoint 依赖后者，不能修改已有训练数据或假装二者一致。
兼容策略固定为：

1. 环境和部署 Actor 始终输出 `gexo_sensor32_runtime_v1`；
2. 共享 TCN runtime 在推理入口执行一次显式排列转换；
3. IMU 安装旋转、编码器零位和关节符号由后端 calibration 先处理，再转换排列；
4. 数据集顺序使用独立协议名 `phase12_tcn32_interleaved_v1`；
5. 转换必须有逐索引单元测试，禁止散落的切片或隐式 `reshape`；
6. checkpoint 必须记录输入协议、输出协议、归一化统计、关节顺序和 calibration
   标识；缺少 metadata 的旧 checkpoint 只能通过明确的 legacy adapter 加载。

TCN 的 moment 输出仍可能是归一化生物力矩或 `Nm/kg`，不能当作电机 `Nm`。当前
160 维部署输入只接 q/dq 的 16 维显式预测。

### 3.5 统一 50 Hz 决定与多速率回退

共享 TCN、冻结人体 Actor 和外骨骼控制的 MVP 默认统一为 50 Hz，MyoAssist 物理
仿真保持 1200 Hz，即每个控制步积分 24 个物理步。

虽然原 speed-control 配置按 30 Hz 训练，正式 runner 已得到以下证据：

- 旧两路踝部外骨骼 actuator 的原始 `ctrlrange` 为 `[-1, 0]`，经环境动作归一化
  后，归一化 `+1` 映射为物理控制 `0`，即 `0 Nm`；
- 保留 tutorial 训练时旧踝硬件惯量、严格关闭旧踝力矩后，0.8 和 1.25 m/s 各
  三个 seed 均走满 1000 步；
- 删除每腿 1.165 kg、总计 2.33 kg 的旧踝硬件惯量后，同 checkpoint 在 0.8 m/s
  约 109 步跌倒，而保留惯量对照走满 1000 步；
- 因此依赖旧惯量的是 released checkpoint，不是 22 肌肉人体模型。隐藏兼容惯量
  只能作为迁移诊断，不得作为正式外骨骼训练资产或 sim2real 证据。

这些结果支持把 50 Hz 作为 MVP 默认频率，也推翻了“原 checkpoint 可直接冻结用于
无旧惯量模型”的假设。正式路径固定为从 `myoLeg22_2D_BASELINE.xml` 生成四髋膝
理想执行器模型，先在严格零外骨骼力矩下迁移微调 22 肌肉策略；只有该模型通过
多 seed、重复 reset 和速度覆盖验收后，才冻结人体并进入外骨骼 PPO。

只有统一 50 Hz 在正确 reset 后回归失败，才允许回退为：人体 Actor 维持 30 Hz，
用时间累加器更新并保持 22 维肌肉动作；外骨骼、传感器和 TCN 仍为 50 Hz。该回退
只能写在 MyoAssist adapter 中，不能污染共享 TCN、传感器或电机模块。

## 4. 目录所有权

### 4.1 项目级共享，只维护一份

| 路径 | 职责 |
|---|---|
| `RL/data/dataset_manifest.py` | 数据清单、固定关节和列定义 |
| `RL/data/preprocess_tcn.py` | 50 Hz 预处理 |
| `RL/data/tcn_dataset.py` | TCN 监督数据窗口 |
| `RL/data/assist_teacher_dataset.py` | 统一教师 NPZ 读取和校验 |
| `RL/runners/predictors/tcn.py` | TCN 网络结构和 checkpoint |
| `RL/runners/predictors/assist_actor.py` | 四输出监督 AssistActor |
| `RL/env/sensors.py` | 统一 runtime32 协议、校验、可选噪声和裁剪；不负责 Actor 历史组帧 |
| `RL/env/actor_observation.py` | 唯一负责 36/144/160 维 Actor Observation 组帧 |
| `RL/env/torque.py` | 动作尺度、硬限矩、限速和滤波；旧调用保持等价 |
| `RL/optimization/contracts.py` | `MuscleSnapshot` 等纯数据契约 |
| `RL/optimization/fixed_trajectory.py` | 后端无关的固定轨迹优化器 |
| `RL/metrics/physiology.py` | 后端无关的纯 NumPy 生理指标 |
| `RL/train.py` | 通用 SB3 PPO 基础设施 |

共享核心契约和指标只能依赖标准库与 NumPy；TCN/Actor 网络层可以依赖 PyTorch，
环境接口可以依赖 Gymnasium，数据预处理可以依赖 pandas，训练入口可以依赖
Stable-Baselines3。所有共享模块均不得 import MyoAssist、Kinesis，不得持有具体
MuJoCo 对象，也不得包含后端 joint/body/muscle 名称。

### 4.2 MyoAssist 后端专属

```text
RL/env/myoassist/
    gexo_leg_env.py
    sensor_adapter.py
    muscle_adapter.py
    policy_transfer.py
    human_adaptation.py

RL/assets/myoassist/
    MyoAssist 专用四髋膝理想力矩模型或生成配置
```

- `gexo_leg_env.py` 组合冻结人体控制、四外骨骼动作、reset/step 和评价数据；
- `sensor_adapter.py` 只负责 MyoAssist 到统一 32 维的标定与映射；
- `muscle_adapter.py` 将 MyoAssist 肌肉状态转换成 `MuscleSnapshot`；
- `policy_transfer.py` 显式映射 released checkpoint 的 22 肌肉权重，并在适配完成后
  加载、冻结和校验最终人体 checkpoint；
- `human_adaptation.py` 只在 BASELINE 模型和严格零四髋膝力矩下微调人体策略，不能
  接收外骨骼 Actor 或外骨骼 reward；
- MyoAssist joint、body、sensor、actuator 名字只能出现在本目录或专属资产中。

### 4.3 Kinesis 后端专属

`RL/env/kinesis/` 继续维护 Kinesis 人体策略、传感器标定、动态 URDF、绑带传力、
baseline 和环境逻辑。本阶段不得为了 MyoAssist 复用而改变 Kinesis 行为。

路线 A 只在 `RL/metrics/physiology.py` 新增中立实现，并以只读方式对
`RL/env/kinesis/physiology_metrics.py` 做数值等价测试。旧 Kinesis 路径若以后改为
兼容重新导出，必须由 Kinesis 分支在自己的独立变更和回归测试中完成；路线 A/B
均不得借共享化之名修改 `RL/env/kinesis/**`。

### 4.4 第三方代码

`third_party/myoassist/` 和 `third_party/Kinesis/` 默认只读。优先通过继承、组合、
模型生成和 G-Exo adapter 解决问题。确实无法解决时，必须满足以下全部条件才能
修改第三方文件：

1. 单独列出阻塞证据和为什么 adapter 无法解决；
2. 获得用户明确授权；
3. 补丁保持最小且不混入 G-Exo 业务逻辑；
4. 在实施日志记录上游文件哈希、补丁和回退方法；
5. 由非编辑 agent 独立 review 和回归测试。

当前已观察到 `myoassist_leg_base.py` 的随机速度初始化调用使用位置参数，参数顺序
与函数签名不一致。首选在 G-Exo adapter 中用关键字参数覆盖初始化，不直接修补
第三方源文件。

## 5. 复用分类

### 5.1 由共享 owner 兼容改造并独立 PASS 后复用

- Phase 1/2 manifest、50 Hz preprocess、TCN dataset 和 TCN 网络；
- `SensorReader` 的 runtime32 采集、输入校验、可选噪声接口；36/144/160 组帧只由
  `RL/env/actor_observation.py` 负责；
- `TorqueActuator` 的归一化动作、限矩、限速和滤波；
- `RL/train.py` 的 PPO、并行环境、checkpoint、TensorBoard 和恢复框架；其当前只
  支持新建或恢复 PPO，不含监督 AssistActor 权重导入钩子，该钩子必须单独新增并
  通过参数映射测试后才能称为复用；
- MyoAssist base 的 MuJoCo 步进、地形、跌倒检测和肌肉状态；
- MyoAssist imitation 的参考轨迹、随机起点、q/dq 模仿和轨迹终止；
- 已有 22 肌肉 speed-control checkpoint 只作为无旧惯量人体适配的初始化权重，
  不能直接作为最终冻结人体 checkpoint。

### 5.2 抽取后复用

- Kinesis 生理指标中的纯 NumPy 计算由共享 owner 抽取到中立目录并做只读等价测试；
  旧路径重新导出只允许未来由 Kinesis owner 在独立变更中完成；
- Kinesis TCN adapter 中 checkpoint、50 帧缓存、归一化和推理，抽成后端无关
  runtime；各后端 calibration 和通道映射保留在专属 adapter；
- MyoAssist `environment_handler.py`、`run_train.py` 的构建思路，不复制第二份 PPO；
- MyoAssist `rl_agent_exo.py` 的人体 Actor / 外骨骼 Actor / Critic 分网思路；旧实现
  没有满足本项目的冻结契约，不能原样训练；
- 现有 144 + 16 观测构建逻辑，抽成唯一共享协议实现。

### 5.3 必须新增

- 第 4.1 节尚不存在的共享契约、优化器、教师数据集、指标和 AssistActor；
- 第 4.2 节四个 MyoAssist adapter；
- 无旧踝硬件惯量的 22 肌肉 + 四个理想髋膝力矩正式模型，以及仅用于 checkpoint
  迁移诊断的 teacher-compatible 模型；
- 零外骨骼人体策略迁移、短程微调和稳定性评估入口；
- MyoAssist PPO 环境工厂、训练前 smoke runner 和统一评估入口；
- 协议、执行器脉冲、零助力基线、TCN、指标、并行环境及保存恢复测试。

## 6. 教师数据和 checkpoint 边界

教师 NPZ 格式可以共享，但每个文件必须包含或由 manifest 绑定：

- `teacher_backend`；
- 人体模型名称、版本和哈希；
- 教师策略路径或 ID 及文件哈希；
- 数据协议版本、关节顺序和单位；
- 控制频率与物理频率；
- calibration ID 或哈希；
- 外骨骼执行器定义和力矩安全参数；
- 逐关节 action scale、硬限矩、变化率、滤波和 reset/warmup 协议版本；
- seed、场景、速度条件和生成代码版本；
- label 的物理含义及 shape。

不同肌肉模型或后端生成的教师标签不得无标记混合。Actor 权重只有在 160 维
顺序、归一化、关节符号、力矩单位、TCN checkpoint 和安全层完全一致时才能
共享。保存 Actor 时必须把这些信息作为 sidecar metadata 一起归档。

## 7. 受保护文件与脏工作区策略

2026-08-03 审计时，根 Git 只把 `G-Exo/` 和 `third_party/` 显示为整体未跟踪，
无法利用 Git 判断其中哪些文件是用户修改。因此采用保守规则：所有既有文件都视为
用户所有，除当前实施步骤明确列出的文件外不得修改。

特别受保护：

- `third_party/myoassist/**` 全部文件；
- `third_party/Kinesis/**` 全部文件；
- 用户当前打开的 `third_party/myoassist/rl_train/envs/myoassist_leg_imitation.py`；
- `myoassist_leg_base.py` 和 `myoassist_leg_imitation_exo.py`；
- `RL/env/kinesis/**`、Kinesis checkpoint、baseline 和历史输出；
- `RL/frame.md`、`RL/MODIFICATION_LOG.md` 及既有审计文档；
- `RL/data/**`、`RL/runners/predictors/tcn.py`、`RL/env/sensors.py`、
  `RL/env/torque.py` 等由两条路线共享的文件；
- `.vscode/`、媒体文件、移动硬盘数据和与本任务无关的任何现有文件。

共享文件确需修改时，必须先记录基线哈希、列出两个分支的调用者、提供兼容测试，
再由共享基础设施阶段单独完成。不得把 MyoAssist 专属代码写进共享文件。

## 8. 每步编辑、审阅与归档规则

为满足当前迅捷开发要求，B-P0--B-P7 连续推进，不再要求每个小步骤等待独立 reviewer。
每一个变更单元仍必须：

1. 编辑 agent 在日志中写明目标、允许修改的文件和预期数据流；
2. 编辑 agent 只完成该步骤，不顺带重构；
3. 编辑 agent 运行最小自检并记录命令、退出码和关键输出；
4. 把决定、文件、哈希、命令和结果追加到实施日志，失败记录不得删除；
5. 遇到会改变科学含义、协议或训练目标的问题立即向用户报告；
6. 全部步骤通过后，由一个此前未参与编辑的更新 agent 做整体架构 review、跨模块
   测试和训练前完成度审计。

每次修改都追加记录到 `RL/MYOASSIST_PPO_IMPLEMENTATION_LOG.md`，不得覆盖历史结论。
代码注释和日志不等同于测试证据。

## 9. 当前审计基线与未决验证

当前已确认：

- MyoAssist setup verification 曾由用户运行并通过 13/13 项；
- speed-control 配置使用 22 肌肉二维模型、30 Hz 控制和 1200 Hz 物理；
- 旧踝执行器原始 `ctrlrange=[-1,0]`，归一化 `+1` 已实测对应严格 `0 Nm`；
- 保留 tutorial 训练惯量、严格关闭旧踝助力后，50 Hz 下 0.8 和 1.25 m/s 各三个
  seed 均走满 1000 步；删除旧惯量后 0.8 m/s 约 109 步跌倒，证明旧 checkpoint
  不能直接冻结迁移到正式 BASELINE 模型；
- `myoassist_leg_imitation_exo.py` 目前只是调用父类 `step()` 的空壳；
- 现有模型包含 22 路肌肉与 2 路踝部外骨骼动作，不能直接作为四髋膝环境；
- G-Exo 已有运行时 32 维、四帧 144 维、TCN 16 维和 160 维路径可供抽取；
- 当前已有 teacher-compatible 四髋膝模型和确定性人体 runtime；正式 BASELINE
  四髋膝模型及人体适配 checkpoint 尚待完成。

以下问题属于 B-P2--B-P6 的实现验收，不属于 B-P0 文档通过条件；但在它们通过前
不得启动 B-P7 并行 smoke 或正式 PPO：

1. 同一环境实例连续 reset 时，人体、参考索引、随机数、速度模式、动作缓存和仿真
   时间是否全部恢复，且能复现 50 Hz 的 3/3 稳定结果；
2. 四个新增髋膝执行器的名称、顺序、正方向和 `qfrc` 响应是否正确；
3. 迁移微调后的人体是否在正式 BASELINE 四髋膝模型上形成逐 seed 的零助力基线；
4. MyoAssist IMU site 和局部坐标是否符合统一比力语义；
5. 四关节的肌肉力臂、肌肉力和激活能否形成有限且不相互抵消的统一指标；
6. 小幅有方向力矩是否对运动和肌肉指标产生连续、可重复的剂量响应。

人体适配只允许在严格零四髋膝力矩下进行；它与外骨骼 PPO 是两个不同阶段。不得用
隐藏旧踝惯量替代正式适配，也不得在外骨骼 PPO 中偷偷更新人体策略。若 50 Hz 适配
无法通过稳定性门，再尝试 30 Hz 人体 / 50 Hz 外骨骼回退并报告结果。

## 10. 推进阶段和训练前验收

| 阶段 | 变更单元 | 必须通过的独立验收 |
|---|---|---|
| B-P0 | 建立本边界和实施日志 | 文档与现状一致，没有代码修改 |
| B-P1 | 消费共享协议与中立指标 | 只验证已 PASS 的 S-P1A/S-P1B 产物哈希和接口；不修改共享文件 |
| B-P2 | 正式 BASELINE 与兼容诊断模型、四髋膝执行器 | 两个 XML 编译；正式模型无旧惯量；维度、名称、顺序、正负脉冲通过 |
| B-P3 | 22 肌肉权重迁移、零助力适配、冻结和 50 Hz reset | 重复 reset、多速度稳定性、适配前后报告、冻结 hash 和 50 Hz 时序通过 |
| B-P4 | MyoAssist 32 维 sensor adapter | shape、索引、单位、局部坐标和确定性通过 |
| B-P5 | 消费共享 TCN/Observation 并做 MyoAssist 接线 | 验证已 PASS 的 S-P1A/S-P1C 哈希和协议；接线只改 MyoAssist 专属文件，不改共享或 Kinesis |
| B-P6 | muscle adapter 和奖励/报告 | 指标契约、零助力、脉冲和剂量响应通过 |
| B-P7 | MyoAssist PPO 环境工厂和专属 runner | 只调用 `RL/train.py` 公开接口且不修改它；8 worker smoke、TensorBoard、保存/恢复和 seed 通过 |
| B-P8 | 训练前整体审计 | 新 agent 全量 review，全部门为 PASS |

进入正式训练的最低证据：

- 零助力人体在目标速度集合上达到预先记录的存活和跟踪基线；
- 四路外骨骼零动作严格产生 0 Nm，正负脉冲方向全部正确；
- Actor Observation 始终是有版本的 160 维部署量，不含特权信息；
- TCN 只读取当前和过去 50 帧，不读取未来或 episode 标签；
- 统一安全层实际位于 PPO action 与 MuJoCo actuator 之间；
- 肌肉激活、非抵消关节肌肉负载、共收缩和正功可重复计算；
- baseline/teacher/Actor 报告能按相同 seed 和初始状态配对；
- 8-worker 短训无 NaN、死锁或异常 reset，模型保存后可确定性重载；
- B-P0--B-P7 每一步都有追加式实现与测试证据，B-P8 有此前未参与编辑的新 agent
  逐项复核并给出 `PASS`。
