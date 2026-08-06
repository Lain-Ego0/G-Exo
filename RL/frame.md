# G-Exo 强化学习训练框架设计（V3）

> 状态：首版固定为平地行走、Phase 1/2 监督预训练、轻量肌肉协同控制层和 PPO 四关节助力；OpenSim 原型迁入 `RL/legacy/opensim/` 保留，不再作为主线训练后端  
> 首版目标：先在 50 Hz 下跑通“轻量人体肌肉驱动—MyoSuite 人体动力学—虚拟传感器—TCN—PPO—四关节助力—评估/回放”闭环  
> 后续目标：加入详细外骨骼刚体/URDF→MJCF 映射、TCN 编码器和 Actor 的 K3 部署

## 1. 目标与范围

本项目希望训练一个外骨骼控制策略：策略根据人体—外骨骼系统最近一段时间的可测状态，隐式理解和预测人体接下来的运动趋势，并同时输出左髋、左膝、右髋、右膝四个关节的辅助动作。

首版不追求最终人体生理真实性或最优参数，只要求训练流水线完整、接口稳定、结果可回放、指标可追踪，并为后续人体模型替换、外骨骼 URDF 接入和 Sim2Sim 迁移保留边界。

### 1.1 人体和外骨骼的边界

- **人体动力学**：使用 MyoSuite 2.12.2 和 MuJoCo 3.6 的 80 肌肉下肢模型；物理步长为 1 ms，首版只处理平地正常行走。
- **人体参考**：Phase 1/2 的关节位置、速度、真实 gait cycle、足接触和动力学标签用于形成平地参考命令；参考只供仿真人体、Reward 和 Critic 使用，不输入外骨骼 Actor。
- **人体驱动**：使用 100 Hz 的轻量肌肉协同控制层。它根据当前人体状态、参考误差、相位/接触和上一外骨骼力矩输出 8～12 维肌肉协同，再通过固定非负映射生成 80 路肌肉 excitation；不从零训练大型 80 输出人体策略。
- **教师边界**：depRL 和反射控制器只用于生成仿真伪标签、初始化或联调。它们的输出不是 EMG 真值，只有通过平地闭环验证的数据才能进入轻量肌肉层训练。
- **训练策略**：只训练 PPO 外骨骼策略，50 Hz 输出四个髋膝辅助力矩；Actor 不直接控制肌肉。
- **V0 外骨骼**：不修改人体模型的 80 维肌肉动作空间。通过 MuJoCo `qfrc_applied` 向四个关节自由度施加等效外骨骼广义力矩。
- **V1 外骨骼**：将 URDF 转换为 MJCF，加入外骨骼刚体、连杆、电机惯量、绑带/连接约束和执行器模型。
- **OpenSim 边界**：既有 OpenSim Demo、后端和PD人体控制器保留为 legacy 对照；其结果不再作为主线训练或生理负担结论。

## 2. 已确定内容与待验证内容

### 2.1 当前固定

1. 训练运行时目录按环境、训练/放映、资产、产出四部分组织。
2. MyoSuite 是首阶段唯一的人体—外骨骼闭环动力学后端，Gymnasium 环境通过统一接口调用它；首版地形固定为平地。
3. Phase 1 按被试划分训练/验证，Phase 2 用于部署分布适配，Phase 3 在冻结数据处理、网络和超参数后作为最终测试。
4. Phase 1/2 的运动学、接触、GRF/COP、生物关节力矩和功率是人体参考与真实动力学锚点；它们不是 80 路肌肉激活标签。
5. 人体使用轻量肌肉协同控制层。首版输出 8～12 维协同并映射为 80 路 excitation；外骨骼 PPO 训练前将该层冻结。
6. depRL/反射控制器只提供伪标签或稳定基线，不能作为真实肌肉验证集；Phase 3 也不能验证单块肌肉，肌肉级真值需要 EMG。
7. 外骨骼先用四个 `qfrc_applied` 等效髋膝力矩，再升级为 MJCF 内的外骨骼刚体和 URDF 映射。
8. 外骨骼控制频率固定为 50 Hz，即控制周期为 20 ms；人体肌肉控制层为 100 Hz，MuJoCo 物理积分为 1 ms。
9. 策略在每个控制周期同时输出四个关节动作。
10. 默认动作为四关节直接/残差力矩；保留目标位置加 PD 的对照接口。
11. 首版强化学习算法使用 PPO。
12. Actor 只能依赖真实硬件可获得的因果观测和历史状态。
13. Critic、奖励和训练期辅助任务可以使用 MyoSuite 的肌肉、接触和完整人体状态特权信息。
14. 4 帧历史只用于 PPO 快速基线；正式 TCN 使用 50 Hz 下约 44～50 帧、即 0.88～1 s 的因果窗口。
15. TCN 是共享时序编码器；未来位置/速度、生物力矩和相位/接触由编码器后的轻量预测头输出。最终 Actor 目标是不依赖外置规则或完整预测向量。
16. 使用 TensorBoard 监控训练、预测、肌肉层、奖励、安全和执行器指标。
17. 最终通过模型保真度升级、Sim2Sim 和实机台架检查策略鲁棒性。

### 2.2 暂不固定

- MyoSuite 肌肉仿真在单进程和多进程下的实际吞吐量，以及轻量肌肉控制层在外骨骼扰动下的稳定性。
- 肌肉协同维度最终采用 8、12 还是肌肉组形式，以及固定映射由解剖分组还是 NMF 获得。
- depRL、反射控制器和真实动力学约束在伪标签中的权重，以及由教师切换到轻量控制层的混合系数课程。
- 正式 TCN 历史窗口在 44～50 帧范围内的最终长度。
- 是否加入编码器角加速度、IMU 姿态、重力方向、电机电流或实测力矩。
- 直接力矩和目标位置加 PD 的最终性能对比。
- PPO 超参数、网络宽度、奖励权重和域随机化范围。
- 个体质量、肌力和人机参数随机化的具体范围。
- 坡面、楼梯和随机粗糙地形全部推迟到平地主线通过后，不属于 V0 验收范围。
- 真实电机的转矩—转速、功率、热和延迟参数及 K3 推理后端。

这些项目通过配置文件和对照实验决定，不写死在环境实现中。

## 3. 总体数据流

```text
Phase 1：按被试训练/验证 TCN；Phase 2：适配；Phase 3：最终测试
                    ↓
      TCN 共享时序编码器 + 运动/力矩/相位预测头
                    ↓
depRL/反射闭环 rollout：生成受筛选的肌肉伪标签和协同结构
                    ↓
 轻量肌肉协同控制层（100 Hz，冻结后进入外骨骼训练）
                    ↓
              MyoSuite 80肌肉平地人体
                    ↓
 qfrc_applied 等效外骨骼力矩 / 后续 MJCF 外骨骼刚体
                    ↓
  虚拟编码器 + 虚拟 IMU + 噪声/延迟
                    ↓
       4 帧 PPO 基线 / 44～50 帧 TCN 窗口
                    ↓
             共享时序编码器
            ┌───────┼────────┐
            ↓       ↓        ↓
          Actor   Critic   预测辅助头
            ↓       ↓        ↓
      四关节动作  状态价值  未来运动监督
            ↓
      动作限幅/滤波/执行器模型
            ↓
      MuJoCo 1 ms 物理积分，累计 20 ms
            ↓
人体努力、运动保持、能耗、安全 Reward
            ↓
 TensorBoard、评估、回放、Sim2Sim、K3 导出
```

## 4. 文件夹设计

训练运行时文件按四部分管理；`papers/`和`frame.md`属于研究与设计资料，不属于运行时目录。

```text
RL/
├── frame.md
├── papers/
│
├── env/                             # 一、环境
│   ├── myosuite/
│   │   ├── myosuite_backend.py       # 主线物理后端
│   │   ├── human_reference.py        # Phase 参考、周期和接触命令
│   │   ├── teacher_controller.py     # depRL/反射教师适配
│   │   ├── light_muscle.py           # 轻量协同控制层
│   │   └── human_evaluate.py         # 冻结前人体闭环评估
│   ├── sensors.py
│   ├── torque.py
│   ├── reward.py
│   └── gexo_env.py
│
├── legacy/
│   └── opensim/                     # 旧 OpenSim 后端、Demo 和输出
│
├── runners/                         # 二、训练/评估/放映
│   ├── configs/
│   ├── policies/
│   ├── predictors/
│   │   └── tcn.py
│   ├── callbacks/
│   ├── pretrain_tcn.py
│   ├── train.py
│   ├── evaluate.py
│   ├── playback.py
│   └── export_policy.py
│
├── assets/                          # 三、资产管理
│   ├── datasets/                    # 只保存清单/软链接，大文件放移动硬盘
│   ├── humans/
│   │   ├── opensim/
│   │   ├── references/
│   │   └── controllers/
│   ├── exoskeleton/
│   │   ├── simple/
│   │   └── urdf/
│   ├── motions/
│   ├── sensors/
│   └── mappings/
│       ├── joint_map.yaml
│       ├── sensor_map.yaml
│       └── frame_map.yaml
│
└── outputs/                         # 四、产出
    └── runs/<run_id>/
        ├── config_snapshot.yaml
        ├── environment_manifest.json
        ├── checkpoints/
        ├── tensorboard/
        ├── evaluation/
        ├── trajectories/
        ├── videos/
        └── sim2sim/
```

大体积原始数据、预处理缓存和训练 checkpoint 默认存放在移动硬盘；仓库内只保存配置、数据清单、相对路径或软链接。代码、少量测试样本和最终部署模型保留在本地工作区。

### 4.1 产出可复现性

每次训练必须保存：

- 随机种子；
- 完整配置快照；
- Python、OpenSim、Gymnasium、PyTorch 和 RL 框架版本；
- 人体模型、简化外骨骼或 URDF 文件哈希；
- 关节名称、顺序、轴向和符号映射；
- Observation 归一化统计量；
- 最佳模型、最终模型和定期 checkpoint；
- 评估轨迹、TensorBoard 日志和确定性回放结果。

## 5. 仿真后端设计

### 5.1 统一后端接口

训练逻辑不能直接依赖 OpenSim 或某个 URDF 仿真器的 API。后端至少提供：

```text
reset(seed)
step_physics(dt)
get_human_state()
get_exoskeleton_state()
get_privileged_state()
apply_exoskeleton_action(action)
get_reward_terms()
is_terminated()
close()
```

更换人体模型或外骨骼仿真器时，Actor 的输入语义、动作顺序和控制周期保持不变。

### 5.2 MyoSuite 和轻量肌肉控制层的职责

主线固定使用 MyoSuite 2.12.2、MuJoCo 3.6 和 `myoLegWalk-v0` 的 80 肌肉人体模型计算平地人—外骨骼闭环动力学：

```text
MyoSuite / MuJoCo：在线状态、肌肉、接触、约束和 1 ms 前向动力学积分
轻量肌肉控制层：每 10 ms 根据人体状态、参考误差、相位/接触和上一外骨骼力矩输出低维肌肉协同
固定协同映射：将 8～12 维协同映射为 80 路肌肉 excitation
PPO 外骨骼策略：每 20 ms 根据 144 维可测 Observation 输出 4 维辅助动作
```

肌肉控制层的首版定义为：

$$
x_t^{muscle}
=
[s_t^{human},q_t^{ref}-q_t,\dot q_t^{ref}-\dot q_t,
\sin\phi_t,\cos\phi_t,c_t^{foot},\tau_{t-1}^{exo}]
$$

$$
z_t^{muscle}=f_m(x_t^{muscle}),\qquad
z_t^{muscle}\in\mathbb R^{8\sim12}
$$

$$
e_t^{80}=\operatorname{clip}(Wz_t^{muscle},0,1),\qquad W\ge0
$$

这里必须区分：策略归一化动作、环境映射后的 muscle excitation、具有激活动力学的 muscle activation，以及由肌肉长度/速度共同决定的 muscle force。教师数据必须记录这些量，不能把 depRL 的 `[-1,1]` 原始 action 直接称为真实肌肉激活。

轻量层的监督分为两类：

- 仿真教师 rollout 提供 excitation、activation、肌肉力、肌肉功和协同伪标签；
- Phase 1/2 提供关节运动、接触、GRF/COP、生物关节力矩和功率，只约束可以真实验证的聚合动力学量。

在闭环验证通过前，轻量层只作为估计/蒸馏头，人体仍由稳定教师或反射基线驱动；随后使用

$$
e_t^{human}
=
(1-\lambda)e_t^{baseline}
+
\lambda e_t^{light}
$$

逐步增加 $\lambda$。只有连续平地步态、动力学误差和扰动测试合格后，才冻结轻量层作为外骨骼 PPO 的仿真人体驱动器。外骨骼 PPO 训练期间不再更新该层。

当前本机模型的四关节映射固定为：

```text
[left_hip, left_knee, right_hip, right_knee]
= [hip_flexion_l, knee_angle_l, hip_flexion_r, knee_angle_r]
= [qpos 21, 26, 7, 12]
= [qvel 20, 25, 6, 11]
```

冻结轻量肌肉控制层不是外骨骼的第二个联合训练策略：外骨骼 PPO 训练期间不更新其权重，Actor 也不能访问完整人体状态、参考轨迹、肌肉激活、肌肉力、接触力或显式步态相位。它只负责在仿真内部维持平地人体运动。

depRL 如用于教师 rollout，必须保留其原生 403 维输入和 100 Hz 下的 `qvel * 0.01`；该约定不得传播到外骨骼 Actor。Actor 使用原始 `qvel`，单位为 rad/s，以维持 50 Hz 控制和实机传感器的单位一致性。

OpenSim、Moco、LocoMuJoCo 和临时 MuJoCo Demo 保留为 legacy 或外部对照，不再作为当前主训练后端。

### 5.3 外骨骼模型演进

V0 不修改 MyoSuite 人体模型的 80 维肌肉动作空间。后端通过 `data.qfrc_applied[dof_id] += exo_torque` 向左右髋膝四个自由度施加等效外骨骼广义力矩。这样人体模型的 80 路肌肉执行器定义和轻量层的输出语义保持不变。

V0 必须验证：

- 四关节名称、顺序、轴向和符号；
- 肌肉激活、外骨骼力矩和总关节响应之间的因果关系；
- 力矩、速度和位置限制接口；
- 编码器、IMU 和历史观测生成；
- 动作限幅、滤波和延迟。

V1 将 URDF 显式转换或映射为 MJCF，加入外骨骼大腿/小腿刚体、电机等效惯量、关节以及人机连接约束。URDF 不能被视为无需转换即可运行的人机耦合模型。

## 6. 50 Hz 控制与仿真时序

首版控制频率固定为：

$$
f_{control}=50\ \text{Hz}
$$

$$
\Delta t_{control}=0.02\ \text{s}
$$

每个控制周期的数据流为：

```text
读取人体与外骨骼状态
        ↓
生成编码器/IMU观测
        ↓
更新历史窗口
        ↓
Actor同时输出四关节动作
        ↓
动作安全过滤和执行器模型
        ↓
内部物理积分若干子步，累计到20 ms
        ↓
计算Reward和终止条件
```

物理积分步长可小于 20 ms，但不得改变 Actor 的 50 Hz 更新频率。`terminated`用于跌倒、超限和数值失败；时间上限使用`truncated`。

在线步进由 MuJoCo 前向动力学负责。在一个 20 ms 外骨骼控制周期内保持外骨骼动作不变；冻结的轻量肌肉控制层每 10 ms 更新一次 muscle excitation；MuJoCo 每 1 ms 更新激活动力学并积分。累计到下一个 20 ms 边界后再生成新观测。

## 7. Observation 设计及论文依据

### 7.1 论文依据

#### 仿真学习外骨骼 RL 论文

[Experiment-free exoskeleton assistance via learning in simulation](./papers/s41586-024-07382-4.pdf)使用：

- 左右大腿各一个 IMU；
- 大腿角度和角速度；
- 当前状态及之前三个时间步；
- 100 Hz 控制；
- 总输入为 16 维；
- 策略不显式执行动作分类或步态相位分类。

#### TCN 生物关节力矩估计论文

[Task-agnostic exoskeleton control via biological joint moment estimation](../G-Exo/3.paper/Task-agnostic%20exoskeleton%20control%20via%20biological%20joint%20moment%20estimation.pdf)使用：

- 髋、膝编码器；
- 大腿、小腿、足部六轴 IMU；
- 足底压力、垂直地面反力和压力中心；
- TCN 历史序列；
- 55 Hz 外骨骼控制循环，网络输入实时上采样到 200 Hz；
- IMU 对估计精度贡献最大，编码器次之，鞋垫贡献相对较小。

#### 混合振荡器论文

[基于运动预测的髋关节外骨骼实时助力控制](../G-Exo/3.paper/基于运动预测的髋关节外骨骼实时助力控制.pdf)主要使用大腿角度和角速度，以振荡器内部状态预测步态相位，并补偿约 200 ms 的滤波和执行延迟。

### 7.2 V0 Actor 单帧观测

单帧观测定义为：

$$
o_t=[q_t,\dot q_t,\omega_t^{IMU},a_t^{IMU}]
$$

| 信号 | 维度 | 说明 |
|---|---:|---|
| 四个电机位置 $q$ | 4 | 左髋、左膝、右髋、右膝 |
| 四个电机速度 $\dot q$ | 4 | 与位置顺序一致 |
| 四个 IMU 角速度 | 12 | 每个 IMU 三轴 |
| 四个 IMU 线加速度 | 12 | 每个 IMU 三轴，比力语义需保持一致 |
| 单帧合计 | 32 | 不含历史和上一动作 |

四个 IMU 的首版位置与硬件规划一致：左右大腿、左右小腿。

### 7.3 历史窗口

历史窗口分为快速基线和正式时序模型，二者不得混为同一配置。

参考 RL 论文使用本体状态历史的思路，PPO 快速基线固定：

$$
H=4
$$

在 50 Hz 下，最早帧到当前帧的时间跨度约为 60 ms。论文只说明使用关节角度和角速度的历史，并不规定本项目必须采用 132 维或 144 维输入。

本项目的执行器包含力矩变化率限制、低通滤波，后续还会加入延迟。当前状态不仅取决于传感器状态，也取决于之前执行过的动作。因此将每个 32 维传感器帧与生成该状态的上一动作配对：

$$
z_t=[q_t,\dot q_t,\omega_t^{IMU},a_t^{IMU},u_{t-1}]
$$

其中 $u_{t-1}\in\mathbb R^4$ 是上一控制周期实际发出的归一化动作，故：

$$
\dim(z_t)=32+4=36
$$

PPO 快速基线观测固定为四个完整的时序帧：

$$
o_t^{actor}
=
[z_{t-3},z_{t-2},z_{t-1},z_t]
$$

$$
\dim(o_t^{actor})=4\times36=144
$$

144 维相比 132 维只增加 12 个历史动作值。若策略首层宽度为 128，只增加 $12\times128=1536$ 个权重，约为 6 KiB FP32 或 1.5 KiB INT8，对 K3 部署不是实质负担。过去动作来自控制器自身，在实机上同样可得，不属于特权信息，也不会造成当前动作泄漏。

132 维仍保留为对照配置：

$$
o_t^{132}=[s_{t-3},s_{t-2},s_{t-1},s_t,u_{t-1}]
$$

其中每个 $s_t$ 只包含 32 维传感器信息。该配置只保留最近一次动作，不能完整表示限速、滤波和延迟产生的动作历史。无动作历史的 128 维输入、仅一个上一动作的 132 维输入、完整四帧动作历史的 144 维输入，后续可进行消融实验；V0 默认采用 144 维。

该 144 维输入只用于检查 MyoSuite 环境、Reward、PPO 和四关节动作能否正常工作，不承担完整人体运动预测。环境复位时，不存在的历史动作全部填零；每次物理积分后，将新传感器状态与刚刚执行的动作组成新的 36 维帧。

正式 TCN 使用约 0.88～1 s 的因果历史。在 50 Hz 下：

$$
H_{TCN}\in[44,50]
$$

正式 TCN 默认沿用每帧 32 维传感器加四维上一动作，即每帧 36 维，输入形状为：

$$
X_t\in\mathbb R^{H_{TCN}\times36}
$$

若以后用电机实测力矩替代上一动作，单帧仍为 36 维；若同时保留上一动作和实测力矩，则单帧变为 40 维，必须作为独立配置重新训练。最终窗口长度通过被试外验证确定，但部署输入保持固定形状。

### 7.4 V0 暂不加入电机角加速度

首版不直接加入编码器角加速度，原因是：

- 历史速度已经允许时序编码器隐式推断加速度；
- 真实编码器二次差分噪声较大；
- 仿真中的理想角加速度会形成明显 Sim2Real 信息差。

后续如果加入，只允许使用与真实硬件一致的滤波算法：

$$
\ddot q_t=
\operatorname{LPF}
\left(
\frac{\dot q_t-\dot q_{t-1}}{\Delta t}
\right)
$$

### 7.5 后续候选观测

- IMU 姿态估计或重力方向；
- 大腿—小腿相对姿态；
- 电机实测电流或估算力矩；
- 传感器有效标志和采样间隔；
- 绑带相对位移或人机交互力。

这些信号只有在仿真和真实系统中能够使用相同计算流程时，才允许加入 Actor。

### 7.6 观测归一化与传感器模型

- 连续观测需要归一化，部署时冻结训练统计量。
- IMU 仿真需逐步加入零偏、白噪声、安装角误差、延迟、采样抖动和丢帧。
- 编码器仿真需加入量化、速度滤波、通信延迟和可能的零点偏差。
- Actor 不允许访问 MyoSuite 完整人体状态、肌肉激活、足底力或未来真实状态。

## 8. 隐式人体运动预测与特权 Critic

### 8.1 设计目标

最终策略应从历史传感器中隐式学习人体运动趋势，并直接生成辅助动作，而不是依赖一个独立 TCN 的显式预测结果才能运行。

显式预测的作用是训练期正则化和可解释评估，不是部署期必需模块。

### 8.2 目标网络结构

$$
z_t=f_\theta(o_{t-H+1:t})
$$

$$
a_t\sim\pi_\phi(a|z_t)
$$

$$
V_t=V_\psi(z_t,x_t^{priv})
$$

$$
\hat y_{t+K}=g_\eta(z_t)
$$

其中：

- $f_\theta$是共享时序编码器；
- $z_t$是包含隐式运动趋势的潜在状态；
- Actor 只使用 $z_t$；
- $x_t^{priv}$是 Critic 在仿真中可用的特权当前状态；
- $g_\eta$是训练期显式预测头；
- 部署时只保留时序编码器和 Actor。

### 8.3 数据集监督预训练与显式预测头

`temporaysim/content.pdf`对应的数据集提供外骨骼传感器、虚拟 IMU、关节角度/速度、生物关节力矩、活动标志和步态分段。实际数据下载后先在 RL 之外完成 TCN 监督预训练：

```text
Phase 1：按被试划分训练和验证，覆盖无助力和启发式助力分布
Phase 2：对学习型助力下的部署分布进行适配，仍保留被试/试验级验证
Phase 3：冻结预处理、归一化、网络和超参数后进行最终测试
200 Hz 原始数据：先低通抗混叠，再降采样到 50 Hz
无效力矩 NaN：通过数据清单过滤，不允许静默填零
```

若 Phase 3 中含有 Phase 1/2 的重复参与者，最终结果分别报告未见被试和重复被试；所有划分按被试和完整 trial/gait cycle 完成，禁止随机打散时间帧后切分。

Actor 可用的输入只选择实机能够复现的编码器、IMU、电机实测量和历史动作；`torque_desired`、MyoSuite 完整状态以及未来标签不得混入输入。

监督头包括四关节生物力矩、未来髋膝角度/速度以及步态状态：

$$
\hat\tau^{bio}_{t+K}\in\mathbb R^4
$$

$$
y_{t+K}
=
[q^{human}_{hip/knee},\dot q^{human}_{hip/knee}]
$$

$$
\hat p^{phase/contact}_{t+K}
$$

评估时域预留 50 ms、100 ms 和 200 ms。预测损失为：

$$
\mathcal L_{pred}
=
\sum_K\lambda_K
\left(
\|\hat q_{t+K}-q_{t+K}\|^2
+
\beta\|\hat{\dot q}_{t+K}-\dot q_{t+K}\|^2
\right)
$$

总监督和强化学习损失可扩展为：

$$
\mathcal L
=
\mathcal L_{PPO}
+\lambda_{motion}\mathcal L_{motion}
+\lambda_{moment}\mathcal L_{moment}
+\lambda_{phase}\mathcal L_{phase}
$$

训练按三步推进：先单独预训练 TCN；再冻结编码器，用显式生物力矩基线加 PPO 残差降低探索难度；最后共享时序编码器并逐步移除 Actor 对显式预测值的依赖。预测误差始终是监督损失，不作为环境 Reward。

### 8.4 Critic 特权信息

Critic、Reward 和训练期预测监督可以额外使用：

- MyoSuite 完整人体关节角和速度；
- 骨盆姿态、位置和速度；
- 肌肉激活、肌肉功和人体关节功；
- 足底接触、地面反力和压力中心；
- 人体生物关节力矩；
- 与动作无关的未来参考运动片段。

不允许把由当前动作造成的“未来真实人体状态”直接输入当前 Critic，这会产生未来信息泄漏并破坏价值函数语义。未来真实状态只作为 rollout 完成后的预测监督标签。

### 8.5 V0 与目标结构的差异

Stable-Baselines3 标准 PPO 不直接支持 Actor 和 Critic 使用不同观测，也不直接支持额外预测头。因此：

1. V0 先用相同的 144 维因果观测跑通 PPO 流水线；
2. 环境接口从一开始预留`actor_obs`、`critic_obs`和`prediction_target`；
3. 下一阶段通过自定义 Policy/RolloutBuffer 实现特权 Critic 和预测辅助头；
4. 最终部署模型只导出 Actor 所需部分。

## 9. 动作空间与执行器

### 9.1 四关节同时动作

$$
a_t=
[a_{LH},a_{LK},a_{RH},a_{RK}]
$$

所有关节在同一个 20 ms 控制周期内同时更新。

### 9.2 默认动作：直接力矩

策略输出归一化动作：

$$
a_t\in[-1,1]^4
$$

动作适配器将其映射为：

$$
\tau_t=
[\tau_{LH},\tau_{LK},\tau_{RH},\tau_{RK}]
$$

直接力矩作为默认模式，原因是：

- 与外骨骼助力目标一致；
- 与电机电流/力矩控制模式一致；
- 更容易加入转矩—转速、功率、热和电流约束；
- 不会天然要求外骨骼强迫人体追踪固定轨迹；
- 便于和生物力矩估计或残差助力策略对接。

TCN 引导的过渡阶段使用：

$$
\tau_{exo}
=
\alpha\hat\tau_{bio}
+\tau_{RL,residual}
$$

其中$\alpha$是受限的辅助比例，PPO 只学习安全范围内的残差。完成对照实验后，目标 Actor 直接从共享时序潜在状态输出$\tau_{exo}$，不要求部署时保留独立的生物力矩预测接口。

### 9.3 对照动作：目标位置加 PD

RL 仿真论文使用目标位置，经低通和 PD 变换为最终力矩。项目保留该模式：

$$
q_d=q+\Delta q_{RL}
$$

$$
\tau=
K_p(q_d-q)+K_d(\dot q_d-\dot q)
$$

该模式可能更容易得到稳定运动，但也可能使外骨骼主导人体轨迹。它作为可配置对照实验，不作为默认唯一方案。

### 9.4 硬安全层

动作必须依次经过：

```text
归一化动作
    → 力矩/位置范围映射
    → 峰值限幅
    → 变化率限制
    → 低通滤波
    → 执行器延迟
    → 转矩—转速/功率/热约束
    → 物理关节
```

安全约束不能只依赖 Reward 学习。

## 10. PPO 原理与选型理由

### 10.1 Actor-Critic

PPO（Proximal Policy Optimization）是一种 On-policy Actor-Critic 算法：

- Actor 根据观测输出动作分布；
- Critic 估计当前状态未来可获得的累计奖励；
- 当前策略先采集一批 rollout，再使用这批数据更新网络。

[PPO 原论文](https://arxiv.org/abs/1707.06347)

### 10.2 TD 与 GAE

单步 TD 误差为：

$$
\delta_t=
r_t+\gamma V(s_{t+1})-V(s_t)
$$

GAE 优势估计为：

$$
A_t=
\sum_{l=0}^{\infty}
(\gamma\lambda)^l\delta_{t+l}
$$

$A_t>0$表示该动作优于 Critic 的预期，Actor 应提高该动作在类似状态下的概率。

### 10.3 PPO 裁剪目标

新旧策略对同一动作的概率比为：

$$
\rho_t(\theta)=
\frac{\pi_\theta(a_t|o_t)}
{\pi_{\theta_{old}}(a_t|o_t)}
$$

PPO 使用裁剪代理目标：

$$
L^{clip}=\mathbb E
\left[
\min
\left(
\rho_tA_t,
\operatorname{clip}(\rho_t,1-\epsilon,1+\epsilon)A_t
\right)
\right]
$$

裁剪限制一次更新远离旧策略的程度，降低接触、肌肉和人机耦合产生的高方差梯度破坏已有策略的风险。

总损失通常包括：

$$
\mathcal L_{PPO}
=
-L^{clip}
+
c_v\mathcal L_{value}
-
c_e\mathcal H(\pi)
$$

其中价值损失训练 Critic，熵项保持早期探索。

### 10.4 选择 PPO 的原因

1. 支持四维连续动作空间；
2. 裁剪更新在噪声和接触较强的环境中相对稳定；
3. 容易使用多个独立仿真环境并行收集 rollout；
4. Actor-Critic 结构便于后续扩展特权 Critic；
5. Stable-Baselines3 提供环境检查、保存加载、回调和 TensorBoard；
6. PPO 在机器人 locomotion 和论文中的人体—外骨骼仿真均有直接参考。

[Stable-Baselines3 PPO 文档](https://stable-baselines3.readthedocs.io/en/master/modules/ppo.html)

### 10.5 PPO 的限制

- On-policy，样本利用率低于 SAC 等 Off-policy 算法；
- MyoSuite 肌肉仿真和冻结轻量肌肉控制层较慢时，采样可能成为主要瓶颈；
- 历史信息需要帧堆叠、时序编码器或 RecurrentPPO；
- 特权 Critic 和预测辅助头需要自定义 Policy/Buffer；
- PPO 的稳定性不等于真人部署安全，仍需硬安全层和 Sim2Sim。

V0 先以 PPO 建立可靠基线，后续再比较 SAC、RecurrentPPO 或其他算法。

## 11. Reward 设计

Reward 参考 RL 仿真论文中的人体负担、外骨骼能耗、姿态跟踪、骨盆跟踪、CoP 和动作平滑项，并扩展到四个关节。TCN 预测误差不进入环境 Reward。

$$
r_t=
w_{pose}r_{pose}
+w_{root}r_{root}
+w_{stable}r_{stable}
-w_hc_h
-w_Ec_E
-w_sc_s
-w_lc_{limit}
$$

### 11.1 人体运动保持

$$
r_{pose}
=
\exp
\left(
-\left\|
\frac{q-q_{ref}}{\sigma_q}
\right\|^2
-\beta
\left\|
\frac{\dot q-\dot q_{ref}}
{\sigma_{\dot q}}
\right\|^2
\right)
$$

该项避免策略通过改变人体动作或让人体停止运动来虚假降低肌肉负担。

### 11.2 人体负担

主线直接使用 MyoSuite 的平均肌肉激活平方作为人体努力代理：

$$
c_h=
\frac{1}{N_m}
\sum_i activation_i^2
$$

也可加入肌肉力、肌肉正功和人体关节机械功：

$$
c_h^{power}=
\sum_j|\tau_{human,j}\dot q_j|
$$

### 11.3 外骨骼能耗

$$
c_E=
\frac{1}{P_{scale}}
\sum_j|\tau_{exo,j}\dot q_j|
$$

首版对正负机械功都计入成本，避免策略利用理想回生能力产生现实中无法处理的负功率。

### 11.4 动作平滑

参考论文的二阶动作差分：

$$
c_s=
\left\|
\tau_t-2\tau_{t-1}+\tau_{t-2}
\right\|^2
$$

位置加 PD 模式下，则对目标位置的二阶差分进行相同惩罚。

### 11.5 稳定和安全

安全项包括：

- 骨盆高度和躯干姿态；
- 足底接触或压力中心；
- 关节位置、速度和力矩限位；
- 电机功率和动作变化率；
- 跌倒；
- 数值积分失败。

跌倒、严重超限和积分失败直接终止 episode，并记录具体终止原因。

### 11.6 Reward 权重策略

论文中的权重只能作为参考，不能直接照抄，因为模型、频率、动作和子奖励尺度均不同。正式调权重前，应先把每个子项归一化到相近量级。

不把`alive=0.5`或其他任意固定常数写死为核心奖励。首版优先通过运动保持、稳定性和跌倒终止惩罚区分有效 episode；只有在确认策略因短期收益主动提前终止时，才加入经过归一化的小型存活项。

推荐课程：

1. 运动保持、稳定性、跌倒终止和硬安全；
2. 加入动作平滑；
3. 加入人体肌肉负担；
4. 加入外骨骼能耗；
5. 加入个体、传感器和执行器随机化。

预测误差属于辅助监督损失，不直接混入环境 Reward。

## 12. 训练、评估和放映流水线

### 12.1 V0 训练流程

```text
整理 Phase 1/2/3 清单、关节符号、周期边界和被试级划分
      ↓
用 Phase 1 训练/验证 TCN，Phase 2 适配，冻结后在 Phase 3 测试
      ↓
验证 depRL/反射平地教师并生成 excitation、activation、肌肉力/功伪标签
      ↓
训练 8～12 维轻量肌肉协同层，并以真实生物力矩、GRF/COP 作聚合约束
      ↓
从教师混合到轻量层，完成无助力和固定外骨骼扰动下的平地闭环验证
      ↓
冻结轻量层，构建虚拟传感器、四个 qfrc_applied 力矩和 50 Hz Gymnasium 环境
      ↓
check_env + 随机动作冒烟测试
      ↓
PPO 快速基线 → 冻结 TCN 的残差 PPO → 共享编码器 PPO
      ↓
定期评估、保存 checkpoint、确定性回放和轨迹导出
```

### 12.2 训练和评估隔离

- 训练环境允许探索和随机化；
- 评估环境使用固定种子集合；
- playback 默认使用确定性动作；
- 评估不得复用训练环境的未重置内部状态；
- 训练回报和独立评估回报分别记录。

### 12.3 V0 验收条件

1. MyoSuite 人体在无外骨骼帮助时能够由冻结轻量肌肉控制层完成可重复的平地基准步态；
2. 正负外骨骼测试力矩能够因果地改变肌肉激活、关节运动和跌倒率；
3. 轻量层必须区分 teacher action、excitation、activation 和 muscle force，并报告教师留出 rollout 上的蒸馏误差；
4. 平地闭环验证必须报告关节运动、步态周期、足接触、GRF/COP、生物力矩、肌肉平滑性和跌倒率，不能只报告80路伪标签误差；
5. MyoSuite 环境可重复`reset()`并连续`step()`；
6. 控制周期为 20 ms，轻量肌肉层周期为 10 ms，内部物理积分步长为 1 ms；
7. PPO 快速基线 Observation 为 144 维，正式 TCN 输入使用固定的 44～50 帧窗口；
8. 动作空间为四维连续`Box`；
9. Gymnasium和SB3环境检查通过；
10. 随机动作运行不产生 NaN；
11. TCN 在冻结的 Phase 3 测试集上分别报告未来运动、力矩和步态状态指标；
12. PPO 可以完成短训练；
13. checkpoint 能保存、加载和继续评估；
14. TensorBoard 能看到训练损失、肌肉层指标、总奖励和子奖励；
15. playback 能确定性重放完整 episode；
16. 每次运行保存配置、种子、模型版本和资产哈希；
17. 失败 episode 的终止原因可以追踪；
18. V0 只验收平地正常行走，不以坡面、楼梯或粗糙地形结果阻塞主线。

## 13. TensorBoard 指标

至少记录以下层级：

```text
train/episode_return
train/episode_length
eval/episode_return
eval/fall_rate

loss/policy
loss/value
loss/entropy
loss/prediction
loss/muscle_distillation

prediction/mae_50ms
prediction/mae_100ms
prediction/mae_200ms

reward/pose
reward/root
reward/stability
reward/human_effort
reward/exo_energy
reward/smoothness
reward/safety

actuator/left_hip_torque
actuator/left_knee_torque
actuator/right_hip_torque
actuator/right_knee_torque
actuator/saturation_ratio
actuator/power
actuator/torque_rate

human/muscle_activation
human/muscle_excitation
human/muscle_synergy
human/teacher_student_error
human/joint_power
human/biological_moment

system/steps_per_second
system/integration_failures
system/episode_termination_reason
```

不能只记录 Reward 总和；每个子奖励、安全约束和执行器指标必须独立记录，以便发现奖励投机和异常策略。

## 14. 模型保真度升级、Sim2Sim 与实机迁移

主训练人体后端固定为 MyoSuite 后，迁移分为 MyoSuite 内部模型保真度升级、独立第二仿真模型 Sim2Sim 和 K3 实机部署三部分。OpenSim legacy 仅可作为独立对照，不与主训练后端混称为零样本迁移。

### 14.1 外骨骼刚体迁移

```text
四个等效 qfrc_applied 力矩
          ↓
MyoSuite / MJCF 外骨骼刚体、连杆和人机约束
          ↓
详细 URDF 外骨骼及第二刚体仿真器
```

主要比较：

- 关节名称、轴和力矩正方向；
- 质量、质心和转动惯量；
- 关节摩擦、阻尼和限位；
- 电机延迟、饱和和转矩—转速包络；
- 编码器和 IMU 的观测语义；
- 同一动作下的关节角、速度、力矩和功率。

### 14.2 MyoSuite 人体模型保真度升级

将同一策略从无质量等效外骨骼力矩逐步放入带外骨骼刚体、绑带和详细执行器的 MyoSuite/MJCF 模型验证：

- 人体关节运动误差；
- 生物关节力矩；
- 肌肉激活和肌肉功；
- 人体关节功；
- 外骨骼机械功；
- 稳定性和跌倒率。

肌肉激活、肌肉力和肌肉功用于生理意义更强的仿真比较；但轻量肌肉层使用伪标签、缺少 EMG 真值、人体模型参数和人机连接假设必须作为局限报告。V0 不据此声称单块肌肉激活与真实人体一致。

### 14.3 K3 实机部署边界

K3 只运行固定形状的因果时序编码器、Actor、归一化和安全层；轻量肌肉估计头只有在证明有实机诊断价值且不影响时延时才可选部署。K3 不运行 Critic、人体肌肉控制层、depRL/反射教师、MyoSuite、训练循环或 TensorBoard。目标模型参数量为 0.1M～1M，绝对上限暂定 3M；先验证 FP16，再根据工具链和精度评估 INT8。

在 50 Hz 下每个周期为 20 ms，目标模型推理延迟小于 3 ms，并保留传感器处理、通信、硬安全、故障检测和电机命令的时间余量。

### 14.4 严格迁移条件

Sim2Sim 时必须冻结：

- Actor 网络权重；
- Observation 顺序和历史长度；
- Observation 归一化统计量；
- 动作映射和关节顺序；
- 控制频率；
- 策略推理方式。

迁移后如果继续训练或重新归一化，应标记为微调实验，不能记作零样本 Sim2Sim。

## 15. 论文与开源参考

### 15.1 项目论文

- [Experiment-free exoskeleton assistance via learning in simulation](./papers/s41586-024-07382-4.pdf)
- [Task-agnostic exoskeleton control via biological joint moment estimation](../G-Exo/3.paper/Task-agnostic%20exoskeleton%20control%20via%20biological%20joint%20moment%20estimation.pdf)
- [基于运动预测的髋关节外骨骼实时助力控制](../G-Exo/3.paper/基于运动预测的髋关节外骨骼实时助力控制.pdf)

### 15.2 开源项目

- [OpenSim Core](https://github.com/opensim-org/opensim-core)
- [OpenSim Models](https://github.com/opensim-org/opensim-models)
- [OpenSim Moco](https://opensim-org.github.io/opensim-moco-site/)
- [Bio-Torque Estimator](https://github.com/neumovelab/bio-torque_estimator)
- [MyoSuite](https://github.com/MyoHub/myosuite)
- [LocoMuJoCo](https://github.com/robfiras/loco-mujoco)
- [论文作者公开的训练伪代码](https://github.com/IntelligentRobotLearning/pseudocode_learning_in_simulation)
- [osim-rl](https://github.com/stanfordnmbl/osim-rl)

论文作者的公开仓库只有网络结构和 PPO 流程伪代码，并未公开完整的 50 自由度、208 肌肉人体环境、训练权重或可直接复现实验的工程，因此不能作为项目主代码直接运行。

### 15.3 PPO 与环境接口

- [Proximal Policy Optimization Algorithms](https://arxiv.org/abs/1707.06347)
- [Stable-Baselines3 PPO](https://stable-baselines3.readthedocs.io/en/master/modules/ppo.html)
- [Gymnasium 环境检查](https://gymnasium.farama.org/api/utils/)

## 16. 数据、模型和存储管理

当前本地系统盘空间不足，大型资产必须与代码分离：

```text
本地工作区：代码、配置、少量测试样本、数据清单、最终部署模型
移动硬盘：原始数据、预处理缓存、MyoSuite/legacy OpenSim 大型资产、训练 checkpoint、视频和长周期日志
```

仓库通过配置项`data_root`、`asset_root`和`output_root`引用移动硬盘，不在代码中写死用户名或挂载路径。可在`RL/assets/datasets/`建立指向移动硬盘的软链接，但每次运行仍需检查目标是否已挂载、可写以及剩余空间是否足够。

下载顺序为：

1. MyoSuite 版本和 `myoLegWalk-v0` 资产；
2. task-agnostic 数据集 Phase 1/2 最小训练子集和 Phase 3 最小测试子集，先验证列名、单位、周期边界和标签；
3. Phase 1/2/3 完整数据及哈希；
4. depRL `step_150000000.pt` 和反射控制器只作为教师/基线资产，不登记为最终人体权重；
5. Bio-Torque Estimator 的关键网络、数据工具、LOSO 和部署文件，不无差别克隆大型数据目录；
6. 只有在数据流水线通过冒烟测试后才下载剩余任务和生成大规模缓存。

每个外部资产保存来源 URL、版本/提交号、文件大小和 SHA256；原始数据只读，清洗和降采样结果写入独立 processed 目录。

## 17. 实施顺序

1. 建立 Phase 1/2/3 数据清单和被试/trial 级划分，确认全部列名、单位、膝关节符号、真实 gait cycle 和 NaN 规则；
2. 实现统一 `PhaseDataset`，完成 200→50 Hz 抗混叠降采样、训练统计量和预测标签窗口；
3. 实现共享 TCN 编码器与运动、总/生物力矩、相位/接触预测头，在 Phase 1 训练/验证、Phase 2 适配、Phase 3 测试；
4. 验证 MyoSuite 平地人体、depRL/反射教师、100 Hz 控制和 1 ms 物理积分，生成带清晰语义的教师 rollout；
5. 实现并训练 8～12 维轻量肌肉协同层，以教师伪标签和 Phase 1/2 聚合动力学标签约束；
6. 从教师逐步切换到轻量层，完成平地无助力、固定力矩扰动和留出参考轨迹的闭环验收，然后冻结轻量层；
7. 通过四个 `qfrc_applied` 力矩加入 V0 外骨骼，验证人机力矩因果关系；
8. 实现 50 Hz Gymnasium 环境、144 维 PPO 基线观测、四维动作、Reward、终止、硬安全、TensorBoard 和确定性回放；
9. 跑通 PPO 快速基线，再训练冻结 TCN 的残差 PPO；
10. 加入共享时序编码器、预测辅助头和特权 Critic；
11. 接入 MJCF 外骨骼刚体、URDF 映射和传感器/执行器随机化；
12. 平地主线通过后再单独立项特殊地形，最后完成 Sim2Sim、K3 导出和实机台架测试。

## 18. 当前决策问答

### 18.1 TCN 是否就是预测头

不是。TCN 是共享时序编码器：

$$
h_t=f_{TCN}(X_{t-H+1:t})
$$

预测头是编码器后的轻量线性层或 MLP：

$$
\hat y_{t+K}=g_{pred}(h_t)
$$

独立监督预训练时可以把二者合称“TCN 预测模型”；进入 PPO 后必须区分共享编码器、Actor、Critic 和预测头。预测头通过 Phase 1/2 的未来真实位置、速度、力矩和相位/接触标签监督获得，不是手工规则。

### 18.2 Phase 1/2 是否优于只用 Phase 3 训练

是。Phase 1 覆盖无助力和启发式助力，适合主训练；Phase 2 覆盖学习型助力介入后的部署分布，适合适配；Phase 3 应保留为冻结后的最终测试。若 Phase 3 含重复参与者，分别报告未见被试和重复被试结果。

### 18.3 Phase 数据能否直接输入 MyoSuite 肌肉

不能把关节位置/速度直接当成 80 路肌肉 excitation，也不能在训练闭环中逐帧覆盖 `qpos`。Phase 数据作为参考命令和聚合动力学标签，经当前状态反馈和轻量肌肉控制层生成 excitation；逐帧设置 `qpos` 只允许用于非动力学可视化或坐标检查。

### 18.4 depRL 肌肉激活是否是真值

不是。depRL 只保证在特定 MyoSuite 任务和奖励下产生某种控制行为，其归一化 action、excitation、activation 和 force 也不是同一物理量。它只能作为受筛选的仿真教师；真实 Phase 数据可以验证关节运动、GRF/COP、生物力矩和功率，没有 EMG 时不能验证单块肌肉激活。

### 18.5 为什么轻量肌肉层不直接输出 80 个互相独立的数

从外部运动到 80 块肌肉是非唯一逆问题；直接 80 输出容易继承教师的共收缩和饱和错误。首版输出 8～12 维非负肌肉协同，再用固定矩阵映射到 80 路 excitation，在参数量、平滑性、可解释性和闭环稳定性之间更合适。

### 18.6 轻量肌肉层与反射/depRL 的关系

轻量层先作为估计与蒸馏头训练；反射或通过验证的 depRL 提供基线闭环和伪标签。随后逐步提高轻量层混合比例，平地闭环合格后冻结。外骨骼 PPO 训练期间只更新四输出 Actor，不联合更新人体肌肉层。

### 18.7 肌肉层是否输入外骨骼 Actor

不直接输入。Actor 使用真实硬件可得的编码器、IMU 和动作历史；肌肉层使用的完整人体状态、参考误差和接触属于仿真内部信息。轻量肌肉估计头可以作为辅助监督或诊断，但最终 Actor 不依赖其 80 路输出。

### 18.8 V0 是否包含上下坡和楼梯

不包含。OpenSim legacy 中讨论的坡面方案是“地形几何 + 任务专用参考轨迹 + 前馈/PD 跟踪”，不是自主多地形人体。当前 V0 只验收平地正常行走；坡面、楼梯和随机粗糙地形在平地主线稳定后单独立项。

### 18.9 为什么 Reward 使用仿真真实肌肉状态而不是轻量估计值

在 MyoSuite 中已经能够读取 activation、force 和 power。PPO 若以可被其动作影响的近似估计器作为唯一 Reward，可能利用估计误差作弊。因此训练 Reward 优先使用仿真真实肌肉状态和配对零助力基线；轻量肌肉层只用于蒸馏、辅助损失、解释和后续实机诊断研究。

## 19. 2026-07-29 路线收敛：多地形人体底座与平地优先训练

本节覆盖第 17 节中“先完成轻量肌肉层再做人体闭环”的旧顺序。当前主线改为：Phase 1/2 提供参考运动和生物关节力矩，PPO 只学习 12 维平衡残差，现有 BVLS 层负责将目标关节力矩转换为 80 维 MyoSuite 肌肉动作。人体策略仅存在于仿真中，最终 K3 仍只部署 TCN、外骨骼 Actor、归一化和安全层。

### 19.1 为什么 Phase 1/2 不能直接保证稳定

Phase 1/2 是运动记录和聚合动力学标签，不是可执行控制器。当前数据提供 12 维下肢关节角、速度、生物关节力矩、GRF/COP 和 IMU，但没有完整骨盆六自由度轨迹、80 路肌肉激活真值以及与 MyoSuite 完全一致的人体参数和接触状态。因此：

- 轨迹参考不等于受到扰动后的反馈控制；
- 原受试者的净关节力矩不能逐帧原样驱动另一个肌骨模型；
- 静态肌肉募集只解决力矩分配，不能独立解决骨盆和质心平衡；
- 当前 `PhaseReference + PD + BVLS` 已经跑通。修正 MyoSuite 双 `MjData` 同步后，在半体重骨盆支撑和 10 个固定验证种子下，零平衡残差平均维持 78.8 步，即约 0.79 s。

### 19.2 人体底座控制结构

人体目标力矩固定为：

$$
\tau_{human}
=
\tau_{Phase}
+K_p(q_{ref}-q)
+K_d(\dot q_{ref}-\dot q)
+\tau_{balance}
-\tau_{exo}
$$

其中 PPO 只输出 12 维 `tau_balance`，不直接输出 80 维肌肉动作。BVLS 根据当前肌肉力臂、主动增益和被动力求解 excitation：

$$
a^*=\arg\min_a
\left\|R(q)^T(G(q,\dot q)a+F_{passive})-\tau_{human}\right\|^2
+\lambda\|a\|^2
$$

这种组织保留 Phase 运动风格和 MyoSuite 肌肉动力学，同时把 PPO 动作维度从 80 降到 12。人体策略训练时可以读取骨盆姿态、COM、接触、地形和肌肉状态等特权信息；这些信息不进入外骨骼实机 Actor。

### 19.3 数据规模、划分与采样

当前 Phase 1/2 正常行走清单包含 127 条可用 trial：112 条训练、15 条验证；其中 50 条 `off` 数据来自 10 名受试者，覆盖 0.6、1.2、1.8、2.0 和 2.5 m/s，每种速度 10 条。平地人体策略首轮使用 0.6 和 1.2 m/s，并按受试者隔离：BT11、BT12 作为平地验证，其余 `off` 受试者用于训练。Phase 3 的 7 名受试者、31 条 `on` trial 保持冻结测试，不参与训练。

每个 episode 随机选择受试者、trial 和起始相位；后续再加入人体质量、惯量、地面摩擦、阻尼、传感器延迟和外骨骼扰动。不能按帧随机拆分训练和验证，也不能把全部数据不加区分地混合。

### 19.4 特殊地形设置

`myoLegWalk-v0` 已包含一个 100 x 100、约 14 m x 14 m 的 MuJoCo heightfield，只是默认移到地下。后续环境在 `reset()` 时启用 heightfield 并程序化生成：

$$
h_{flat}(x,y)=0
$$

$$
h_{slope}(x,y)=y\tan\theta
$$

$$
h_{stairs}(x,y)=H\left\lfloor\frac{y-y_0}{D}\right\rfloor
$$

坡道初始范围为正负 3～8 度；台阶高度 0.08～0.18 m、深度 0.25～0.35 m；路缘使用单次高度跃迁；粗糙地面使用平滑随机高度。需要精确垂直侧面或移动障碍时再使用 box geom。训练课程顺序为平地低速、平地全部速度、坡道和低台阶、楼梯/路缘/启停、障碍与随机外骨骼扰动。

heightfield 的每个网格不能单独设置摩擦系数。局部湿滑或冰面应拆成多个地面 geom，再分别修改 `geom_friction`；精确楼梯也优先使用 box geom，避免高度场斜面近似影响接触。若实机仍只有编码器和 IMU，没有视觉、足底触地或地形预览，策略只能在接触地形后进行反应式稳定，不能在脚接触台阶前可靠规划抬脚。因此平地 V0 不加入楼梯，后续坡道与粗糙地面先验证反应式鲁棒性。

地形课程固定为：平地 0.6/1.2 m/s、平地全部速度、正负 3 度坡、逐步扩大到正负 8 度并加入低台阶、最后才加入粗糙地面和摩擦变化。不能第一轮就均匀混合全部难度，否则大量早期跌倒会淹没有用的 PPO 信号。

### 19.5 平地优先与外骨骼训练衔接

不等待完整多地形人体收敛后才开始外骨骼训练。首先训练并冻结 `human_flat_v0`，随后立即启动平地外骨骼 PPO；人体策略继续扩展成 `human_terrain_v1` 后，用冻结的新人体底座继续微调 `exo_flat_v0` 得到 `exo_terrain_v1`。

```text
Phase off 低速参考
        ↓
12 维平衡残差 PPO
        ↓
BVLS 80 肌肉动作
        ↓
human_flat_v0
        ↓
平地外骨骼 PPO
        ↓
exo_flat_v0
```

### 19.6 今晚训练命令与设备

平地人体 PPO 使用现有 `RL/train.py`、SB3 PPO 和 `SubprocVecEnv`。MyoSuite 和 BVLS 主要消耗 CPU；小型 MLP 在 CPU 上通常更快，但保留 CUDA 运行方式用于本机比较。

CPU 推荐命令：

```bash
cd ~/HK_hackthon
conda activate gexo-opensim-rl
PYTHONPATH="$PWD/G-Exo" \
python -m RL.runners.train_human_balance \
  --total-timesteps 10000000 \
  --num-envs 8 \
  --device cpu
```

CUDA 命令：

```bash
cd ~/HK_hackthon
conda activate gexo-opensim-rl
PYTHONPATH="$PWD/G-Exo" \
python -m RL.runners.train_human_balance \
  --total-timesteps 10000000 \
  --num-envs 8 \
  --device cuda
```

TensorBoard：

```bash
tensorboard --logdir G-Exo/RL/outputs/human_balance/tensorboard --port 6006
```

2026-07-29 在本机实测 8 个 CPU 仿真 worker 为 680～725 steps/s。1000 万步按纯训练时间约 3.8～4.1 h，计入留出集评估和系统波动后按 4～5 h 预留。MuJoCo 和 BVLS 仍在 CPU 上运行，`--device cuda` 只将 PPO 网络更新放到 GPU；本项目的小 MLP 不保证 CUDA 比 CPU 更快，应以 8192 步短基准实测选择。

### 19.7 平地 V0 验收标准

今晚开始长训练前必须满足：环境通过 `check_env`；随机动作和零动作不产生 NaN；两环境 PPO 短训练可以保存并加载 checkpoint；TensorBoard 能看到总奖励和姿态、速度、直立、高度、肌肉激活、残差惩罚等子项。

一晚训练后的初步验收目标为：

1. 固定验证受试者上 10 s episode 成功率不低于 80%；
2. 平均 episode 长度显著高于零残差基线，至少提高 25%；
3. 12 关节位置 RMSE 小于 0.30 rad，并继续向 0.20 rad 调整；
4. 平均肌肉激活不持续饱和，激活大于 0.9 的比例低于 10%；
5. 在质量、阻尼和摩擦变化的参数迁移环境中，成功率保留名义环境的 70% 以上；
6. 参数迁移评估冻结策略权重、Observation 顺序、归一化、动作映射和控制频率。

当前参数迁移只记作 `sim2sim-lite`，用于今晚快速判断策略是否依赖单一模型参数；严格 Sim2Sim 仍按第 14 节要求迁移到带详细外骨骼刚体/URDF 的第二模型，并保持策略冻结。

### 19.8 当前实现和首轮证据

平地人体基线环境位于 `RL/env/myosuite/human_balance_env.py`；人体目标力矩到 80 路肌肉动作的转换位于 `RL/env/myosuite/muscle_controller.py`；训练入口为 `RL/runners/train_human_balance.py`；统一评估入口为 `RL/runners/evaluate_human_sim2sim.py`。

MyoSuite 内部由 `base.mj_data` 生成观测，由 `base.robot.mj_data` 执行动力学积分。Phase 初态必须在重置后从前者同步到后者，`qfrc_applied` 也必须写入后者。支撑比例定义为：`0.0` 不施加骨盆支撑，`1.0` 补偿全部体重并叠加骨盆位置/姿态弹簧，`0.5` 补偿一半体重。这个支撑是人体策略的课程脚手架，不是最终外骨骼助力，后续必须逐级降低并单独报告支撑比例。

10 万步 pilot 使用 8 个环境、CPU PPO，共耗时 2 min 40 s。10 个固定留出种子得到：零残差名义环境平均 78.8 步，pilot 为 184.0 步，即 2.34 倍；参数扰动环境零残差为 59.1 步，pilot 为 175.5 步，即 2.97 倍。该结果证明训练和参数迁移方向有效，但成功率仍为 0，尚未达到 1000 步/10 s 的最终门槛，不能把 pilot 当作 `human_flat_v0`。

冻结模型的统一评估命令为：

```bash
cd ~/HK_hackthon
conda activate gexo-opensim-rl
PYTHONPATH="$PWD/G-Exo" \
python -m RL.runners.evaluate_human_sim2sim \
  --model G-Exo/RL/outputs/human_balance/best_model/best_model.zip \
  --episodes 10 \
  --require-pass
```

评估脚本会自动用相同种子再跑零残差基线，输出名义/参数扰动结果、平均长度提升倍率和成功率保留率。`--require-pass` 失败是正常的非零退出，不应删除报告或改低门槛来制造通过。

### 19.9 当前奖励函数与调参原则

当前平地人体奖励只使用仿真状态、Phase 参考和控制代价。定义关节位置误差 $e_q=q-q_{ref}$、关节速度误差 $e_{dq}=\dot q-\dot q_{ref}$、骨盆重力方向误差 $e_g=g_{body}-g_{target}$，则每步奖励为：

$$
\begin{aligned}
r_{pose} &= 2.0\exp\left(-2.0\operatorname{mean}(e_q^2)\right) \\
r_{velocity} &= 0.5\exp\left(-0.05\operatorname{mean}(e_{dq}^2)\right) \\
r_{upright} &= 1.5\exp\left(-5.0\operatorname{mean}(e_g^2)\right) \\
r_{height} &= \exp\left(-20.0(h-h_{target})^2\right) \\
r_{speed} &= 0.5\exp\left(-(v-v_{target})^2\right) \\
r_{effort} &= -0.1\operatorname{mean}(a_{muscle}^2) \\
r_{residual} &= -0.02\operatorname{mean}(u_{PPO}^2) \\
r &= r_{pose}+r_{velocity}+r_{upright}+r_{height} \\
&\quad +r_{speed}+r_{effort}+r_{residual}
\end{aligned}
$$

发生原生跌倒终止时再加 $-10$。正奖励每多存活一步就继续累积，因此已经隐含“存活奖励”，无需再无条件加一个固定 alive 常数。各正项理论最大值依次为 2.0、0.5、1.5、1.0、0.5，总计 5.5；当前 effort 和 residual 在实测中约为 $-0.01$，只起正则作用，不应主导早期平衡。

调参顺序固定为：先存活与直立，再轨迹跟踪，最后肌肉能耗和残差平滑。每次只改变一组权重或一个指数尺度，使用相同的 10 个验证 seed 对照零残差基线；不能同时改 reward、支撑范围和动作限额，否则无法判断因果。动作峰值、关节范围和电机限额属于硬约束，不能只靠 reward 惩罚。骨盆支撑是 curriculum 参数，也不能混入 reward 伪装成策略能力。

判断 reward 是否需要修改时先看外部指标：episode length、success rate、关节 RMSE、肌肉饱和率和参数迁移保留率。只有训练回报上升但这些指标不升，或单项 reward 长期压倒其他项时，才修改公式。不能为了让 gate 通过而降低门槛。

### 19.10 PPO 轮数、阶段训练与播放

当前 `num_envs=8`、`n_steps=512`，所以一个 PPO iteration 收集 $8\times512=4096$ 个 transition；每个 iteration 对这批数据执行 5 个 optimization epoch。对应关系为：10 万步约 25 iterations，100 万步约 245 iterations，500 万步约 1221 iterations，1000 万步约 2442 iterations。项目以 transition 数和固定验证集结果决定是否停止，不以模糊的“epoch 数”决定。

推荐分段而不是直接盲跑 1000 万步：

1. 8192 步 smoke 已完成，只检查接口；
2. 从已验证的 10 万步模型继续 90 万步，到约 100 万步后做 10-seed 评估；
3. 若平均长度仍持续提高，则继续约 400 万步到 500 万步；
4. 500 万步通过 gate 就冻结为 `human_flat_v0`，不必凑满 1000 万步；若未通过且曲线仍上升，再继续到 1000 万步；若已经平台或退化，先检查 reward 和 curriculum，不能继续堆步数。

此前被中断的 50 万步试跑只训练到 TensorBoard step 245760；其唯一 `best_model` 位于 step 202400，5 个验证 episode 长度为 220、91、116、120、98，没有优于 10 万步模型的固定 10-seed 结果，因此不作为新的续训起点。继续训练仍从 `human_balance_pilot_100k/final_model.zip` 开始。

100 万步阶段推荐命令：

```bash
cd ~/HK_hackthon
conda activate gexo-opensim-rl
PYTHONPATH="$PWD/G-Exo" \
python -m RL.runners.train_human_balance \
  --resume G-Exo/RL/outputs/human_balance_pilot_100k/final_model.zip \
  --total-timesteps 900000 \
  --num-envs 8 \
  --device cpu \
  --output G-Exo/RL/outputs/human_balance_1m
```

CUDA 只替换 `--device cpu` 为 `--device cuda`；MuJoCo 和 BVLS 仍运行在 CPU。训练后先去掉 `--require-pass` 查看完整报告，再用 `--require-pass` 做正式门禁。

数值评估加策略/零残差同初态顺序播放：

```bash
PYTHONPATH="$PWD/G-Exo" \
python -m RL.runners.evaluate_human_sim2sim \
  --model G-Exo/RL/outputs/human_balance_1m/best_model/best_model.zip \
  --episodes 10 \
  --play nominal \
  --play-mode both \
  --show-muscles
```

参数扰动播放将 `--play nominal` 改为 `--play shifted`。该脚本是同一 MyoSuite 模型的参数迁移 `sim2sim-lite`；严格 Sim2Sim 必须冻结策略后接入独立第二模型，不能用本脚本的质量/阻尼/摩擦缩放替代。

## 20. 2026-07-30 路线收敛：Kinesis 人体底座上的外骨骼 PPO

本节覆盖第 19 节中“继续训练 MyoSuite 人体平衡策略后再训练外骨骼”的执行顺序。当前已经验证 Kinesis `legs_abs` 人体能够稳定复现多条平地动作，四个髋膝等效外骨骼力矩能够产生正确方向的因果响应，`MuscleLoadSharing` 也能够在保持名义关节合力矩的条件下减少一部分人体肌肉输出。因此先冻结 Kinesis 人体策略，直接训练四输出外骨骼 PPO；原 MyoSuite、OpenSim 和人体平衡 PPO 文件全部保留，不删除。

### 20.1 冻结组件和训练组件

训练过程中只更新外骨骼 Actor 和 Critic：

```text
Kinesis 预训练策略（冻结）
        ↓ 86 维名义肌肉兴奋度
MuscleLoadSharing（固定解析层）← 四关节外骨骼力矩
        ↓ 受助力肌肉兴奋度
MuJoCo 激活动力学和人体前向动力学
        ↓
144 维可部署观测 → PPO → 四维外骨骼动作
```

Kinesis 负责给出无助力人体的名义肌肉控制；MuJoCo 负责 excitation、activation、肌肉力和运动积分；`MuscleLoadSharing` 负责外骨骼介入后的首版显式卸力。PPO 不更新 Kinesis 权重，不输出 86 维肌肉动作，也不能在 Actor Observation 中读取肌肉激活、参考动作、完整人体状态或未来状态。

当前 `MuscleLoadSharing` 只维护反事实肌肉激活，并不是一套完全独立的影子人体动力学。它足以用于首版平地 PPO 和方法验证，但由此得到的激活下降仍属于模型内代理指标。后续若要加强人机共同适应，应升级为完整影子人体或 MyoAssist 式多 Actor 训练，不能把首版结果直接表述为真人代谢下降。

### 20.2 文件位置和职责

```text
RL/env/kinesis/teacher.py
    加载冻结 Kinesis checkpoint，并把策略包装为 86 维人体动作回调

RL/env/kinesis/assist_backend.py
    20 ms 外骨骼步进、力矩限幅/限速、解析卸力和 MuJoCo 积分

RL/env/kinesis/exo_env.py
    Gymnasium 环境、144 维历史观测、四维动作、奖励和终止

RL/train.py
    通用 SB3 PPO、并行环境、checkpoint、TensorBoard、验证和墙钟停止

RL/runners/train_kinesis_exo.py
    训练/验证步态分配、PPO 参数和命令行入口

RL/runners/evaluate_kinesis_exo.py
    零助力、固定 oracle 助力和冻结 PPO 的数值评估及 GUI 播放
```

`RL/env/gexo_env.py` 的旧抽象接口与 Kinesis 的“冻结人体策略 + 外骨骼力矩”调用方式不同。本阶段不继续给旧类堆叠适配器，而是新增一个只负责 Kinesis 的最小 Gymnasium 环境；通用训练器、执行器、传感器读取、Kinesis 后端和已有 checkpoint 加载逻辑继续复用。

### 20.3 Observation、动作和频率

外骨骼控制周期保持 $20\,\mathrm{ms}$，即 $50\,\mathrm{Hz}$。单帧仍采用第 7 节确定的 36 维定义：

$$
z_t=[q_t,\dot q_t,\omega_t^{IMU},a_t^{IMU},u_{t-1}]
$$

其中四个 IMU 依次位于左大腿、左小腿、右大腿和右小腿。Kinesis 模型已有对应刚体角速度和线速度传感器；V0 用相邻控制帧线速度差分得到线加速度，减去重力并旋转到各刚体局部坐标系，形成与真实 IMU 一致的比力语义。噪声和零偏默认关闭，保留参数接口后再做随机化。

四帧历史组成：

$$
o_t=[z_{t-3},z_{t-2},z_{t-1},z_t]\in\mathbb R^{144}
$$

物理量使用固定尺度归一化并裁剪，部署时可原样复现，不使用仿真在线统计量。动作固定为：

$$
a_t=[a_{LH},a_{LK},a_{RH},a_{RK}]\in[-1,1]^4
$$

外骨骼动作直接使用 RS02 的物理包络：峰值力矩 $\pm17\,\mathrm{Nm}$，额定力矩 $6\,\mathrm{Nm}$ 只作为代价归一化和超额时间统计，不作为第二层裁剪。力矩变化率仍由 `TorqueActuator` 作为执行器硬约束；当前 $50\,\mathrm{Nm/s}$ 是待实机阶跃测试替换的保守值，不属于 Reward。

### 20.4 集中式 Reward

Reward 只在 `RL/env/kinesis/exo_env.py` 顶部的 `REWARD_WEIGHTS` 和 `_compute_reward()` 中定义，避免权重散落在 runner、后端或 XML。定义当前人体与参考刚体位置均方误差为 $e_p$，影子和实际肌肉激活分别为 $a_0$、$a$，影子和实际四关节肌肉力矩分别为 $\tau_{m,0}$、$\tau_m$，则首版为：

$$
r_{track}=\exp(-200e_p)
$$

$$
r_{activation}=\operatorname{clip}\left(
\frac{\operatorname{mean}(a_0^2)-\operatorname{mean}(a^2)}
{\operatorname{mean}(a_0^2)+\epsilon},-1,1\right)
$$

$$
r_{muscle}=\operatorname{clip}\left(
\frac{\operatorname{mean}(|\tau_{m,0}|)-\operatorname{mean}(|\tau_m|)}
{\operatorname{mean}(|\tau_{m,0}|)+\epsilon},-1,1\right)
$$

$$
\begin{aligned}
r_t={}&w_{track}r_{track}+w_{upright}r_{upright}
+w_{activation}r_{activation}+w_{muscle}r_{muscle}\\
&-w_{torque}c_{torque}-w_{smooth}c_{smooth}
-w_{negative}c_{negative\ power}-w_{balance}c_{balance}
\end{aligned}
$$

原生 Kinesis 跟踪失败时额外加入终止惩罚。正的跟踪和直立项已经随存活时间累计，不再添加任意固定 `alive=0.5`。动作峰值和变化率由执行器硬限制负责，Reward 中的力矩与平滑项只用于偏好优化，不能替代安全边界。

调参时先看成功率、运动覆盖率和当前 MPJPE，再看肌肉激活/肌肉力矩下降，最后才压低外骨骼力矩、负功和抖动。每次只修改一组权重，并固定训练步态、验证步态、种子和力矩限额；不能通过降低跟踪门槛制造“省力”。

### 20.5 步态划分和训练课程

进入 PPO 前通过稳定筛选的动作中，首版按 motion ID 固定划分：

- 训练：`2,8,9,11,16,38,43,52`；
- 验证：`64,82,99`。

每个并行 worker 固定加载一条训练动作，避免每次 reset 重建 Kinesis 大模型。8 个 worker 正好覆盖 8 条训练动作；验证回调固定使用未进入训练的 motion 64，训练结束后再由统一评估脚本遍历全部三个留出动作。motion 10 的无助力基线曾出现失败，不进入首轮正式集合。

TCN 暂不接入本次快速 PPO。V0 先证明“编码器/IMU/动作历史能够产生稳定的动态助力”；随后冻结已训练的 TCN 编码器，并保持同一动作、Reward 和评估口径进行对照。2026-07-31 的 300k 筛选表明“64 维 latent + 200 ms 显式预测”的 216 维接口跨步态不稳定，因此下一版 Actor 不再直接读取 latent，只读取 100/200 ms 的四关节 `delta_q + delta_dq`，形成 144+16=160 维 Observation。latent 仍保留在 TCN 内部供预测头使用。

### 20.6 训练前门禁和约八小时运行

长训练前依次通过：

1. `py_compile`；
2. Gymnasium `check_env`；
3. 零动作和随机动作无 NaN；
4. GUI 中分别播放零助力和 2.5% 生物力矩 oracle 助力；
5. 8192 transition 的 PPO smoke 能保存并加载；
6. 20 万 transition pilot 的 TensorBoard 中各 Reward 子项、episode length、MPJPE、肌肉激活和四关节力矩均可解释。

正式训练同时设置较大的 transition 上限和 8 小时墙钟上限。墙钟回调到时正常停止 `learn()`，保存 `final_model.zip`；checkpoint 和最佳验证模型仍按固定 transition 间隔保存。因此机器速度变化不会让“八小时训练”变成无法预估的步数任务。

训练后必须用同一留出动作和种子配对比较零助力、固定 oracle 与 PPO，至少报告成功率、覆盖率、MPJPE、实际/影子激活平方、人体肌肉力矩、外骨骼力矩、正负机械功和力矩平衡误差。只有运动质量没有退化且人体负担指标下降，才能把策略记为有效候选。

### 20.7 实现状态、验证结果和运行入口

截至 2026-07-30，以上最小流水线已经落位并完成以下验证：

- Gymnasium `check_env` 通过，Observation 为 `(144,)`，Action 为 `(4,)`；
- 零动作和随机动作各连续运行 100 步，无 NaN、Inf 或异常终止；
- 2 个并行 worker 的 8192-transition PPO smoke 完成，模型可保存并重新加载；
- 8 个并行 worker 均能加载不同训练动作，首轮采样吞吐约为 445 transition/s；
- 3.6 秒墙钟停止 smoke 在 rollout 边界正常退出，并保存 `final_model.zip`；
- 留出动作 64 的 smoke 策略仍接近零助力，符合 8192 步只验证接口、不验证收敛性的定位。

Kinesis 原实现即使只加载一个动作也会无条件创建 `multiprocessing.Manager`，而 SB3 的 daemon worker 不能再创建子进程。兼容补丁位于 `third_party/Kinesis/src/KinesisCore/kinesis_core.py`：仅当动作加载确实包含多个并行 job 时才创建 Manager 和 Queue。每个 PPO worker 只加载一个 motion，因此走串行分支；原有多动作并行加载行为保持不变。

训练前用相同 motion 和 seed 顺序播放零助力与 2.5% 生物力矩 oracle。oracle 会读取仿真特权力矩，只用于确认助力方向、渲染和指标链路，不能作为可部署策略：

```bash
cd ~/HK_hackthon/G-Exo
conda activate kinesis
export PYTHONNOUSERSITE=1

PYTHONPATH="$PWD:$PWD/../third_party/Kinesis" \
python -m RL.runners.evaluate_kinesis_exo \
  --motion-ids 8 \
  --modes baseline,oracle \
  --episodes 1 \
  --render \
  --output RL/outputs/kinesis_exo_evaluation/pretrain_render.json
```

正式首轮训练用 8 个 worker 覆盖 8 条训练动作。`--total-timesteps` 是防止异常长跑的上限，`--hours 8` 才是本轮正常停止条件：

```bash
PYTHONPATH="$PWD:$PWD/../third_party/Kinesis" \
python -m RL.runners.train_kinesis_exo \
  --hours 8 \
  --total-timesteps 100000000 \
  --num-envs 8 \
  --device cpu \
  --output RL/outputs/kinesis_exo_ppo_8h
```

TensorBoard 监视命令：

```bash
tensorboard \
  --logdir RL/outputs/kinesis_exo_ppo_8h/tensorboard \
  --port 6006
```

训练后在三个完全留出的动作上做确定性配对评估；数值指标通过后，再追加 `--render` 录制策略画面：

```bash
PYTHONPATH="$PWD:$PWD/../third_party/Kinesis" \
python -m RL.runners.evaluate_kinesis_exo \
  --model RL/outputs/kinesis_exo_ppo_8h/best_model/best_model.zip \
  --motion-ids 64,82,99 \
  --modes baseline,policy \
  --episodes 3 \
  --device cpu \
  --output RL/outputs/kinesis_exo_ppo_8h/holdout_report.json
```

奖励只允许从 `RL/env/kinesis/exo_env.py` 的 `REWARD_WEIGHTS`、`TRACKING_EXP_SCALE`、`NEGATIVE_POWER_SCALE_W` 和 `_compute_reward()` 调整。训练 runner 只记录配置，不重复定义公式；动作峰值和力矩变化率仍在 `AssistBackend` 中作为硬约束。

### 20.8 Kinesis 渲染中的 G-Exo URDF

Kinesis PPO 的 `render_mode="human"` 已复用 `RL/env/myosuite/exo_overlay.py` 中的 URDF 解析、五连杆正运动学和 `GExoMocapDriver`。由于 Kinesis 的预训练策略会把人体模型中的全部 body 数量用于构造 Observation，不能把五个外骨骼 mocap body 直接加入教师动力学模型；否则教师输入维度会改变，原 checkpoint 失效。因此渲染采用与旧 Demo 相同的双模型数据流：

```text
原始 Kinesis 模型
    ├── 86 维人体肌肉控制和 MuJoCo 动力学
    ├── 四路 qfrc_applied 等效外骨骼力矩
    └── qpos/qvel/act/ctrl
                    ↓ 每个显示帧复制
Kinesis + G-Exo 显示模型
    ├── 相同 nq=38、nv=37、nu=86
    ├── 五个无质量、无碰撞 mocap link
    └── GExoMocapDriver 根据骨盆和四个髋膝角更新 URDF
```

MuJoCo 3.1.2 没有 `MjSpec`，所以原 overlay 生成器增加了标准 XML fallback：先用 `mj_saveLastXML` 展开 Kinesis 的嵌套 include，再插入 URDF mesh 和 mocap body，并重新加载检查维度。生成文件位于：

```text
RL/output/demo_7_27/generated/kinesis_gexo.xml
```

只有 `--render` 时才生成和加载显示模型，headless PPO 训练路径不增加额外模型或渲染开销。该方案已经把完整 URDF 外观和关节运动接入仿真播放，但外骨骼质量、惯量、碰撞和绑带柔性仍未进入动力学；当前动力学助力仍由四路等效力矩和 `MuscleLoadSharing` 表示。后续物理 URDF 阶段必须把电机力矩施加到实体外骨骼关节，并避免与人体 `qfrc_applied` 重复施力。

运行必须使用装有 Kinesis 依赖的 `kinesis` Conda 环境，而不是 `gexo-opensim-rl`：

```bash
cd ~/HK_hackthon/G-Exo
conda activate kinesis
export PYTHONNOUSERSITE=1

PYTHONPATH="$PWD:$PWD/../third_party/Kinesis" \
python -m RL.runners.evaluate_kinesis_exo \
  --motion-ids 8 \
  --modes baseline,oracle \
  --episodes 1 \
  --render \
  --output RL/outputs/kinesis_exo_evaluation/pretrain_render.json
```

### 20.9 Reward V2 与文件落位（覆盖 20.4～20.7 的 V0 奖励）

V2 不再把“尽可能贴近理想参考轨迹”作为外骨骼优化目标。冻结的 Kinesis 人体已经负责运动复现；外骨骼策略只在运动质量不比同条件零助力人体明显变差时优化人体减负。数据流固定为：

```text
同 motion、seed 和时间的零助力 baseline
    ├── 跟踪 MSE
    └── 全部肌肉激活平方均值
                    ↓
50 Hz 外骨骼 rollout → tracking/balance 有效性门控
                    ↓
有效的激活平方节省 + 执行器代价 + 异常终止
```

零助力 baseline 由 `RL/runners/collect_kinesis_baseline.py` 离线采集，`RL/env/kinesis/baseline_reference.py` 按 `motion_id + seed + simulation_time` 加载和插值。PPO worker 只从已有 baseline 的成功 seed 中抽样，避免每个 worker 同时运行第二套人体而使计算量翻倍。`shadow_activation` 仍可供解析肌肉层内部计算，但不再作为 Reward 的零助力真值。

定义全肌肉激活平方代价：

$$
E_a=\frac{1}{N}\sum_i a_i^2
$$

真实 baseline 相对省力为：

$$
e_a=\operatorname{clip}\left(
\frac{E_{a,base}-E_{a,assist}}
{\max(E_{a,base},E_{floor})},-1,1\right)
$$

省力时 $r_{effort}=e_a$；增力时 $r_{effort}=2e_a$，使人体负担增加受到双倍惩罚。实际与 baseline 激活平方均使用相同的短时指数平滑，避免单个物理步的激活动力学噪声主导 PPO。

Tracking 使用相对 baseline 的归一化铰链约束。设 $E_{track,base}$ 为同一时刻零助力 MSE，初始允许上限为：

$$
E_{threshold}=\max(1.5E_{track,base},E_{track,base}+E_{margin})
$$

$$
z=\max\left(0,\frac{E_{track}-E_{threshold}}
{\max(E_{threshold},E_{floor})}\right),\qquad
c_{track}=\min(z^2,c_{max})
$$

阈值内 $c_{track}=0$，不再用跟踪梯度继续修正 Kinesis；超限后才产生二次惩罚。正的 effort 还要乘 tracking gate，轨迹明显退化时不兑现“省力”。负 effort 永远保留，不能通过故意破坏 tracking 隐藏增力惩罚。

解析肌肉层必须尽量满足：

$$
\tau_{human}+\tau_{exo}\approx\tau_{baseline}
$$

定义相对残差：

$$
e_{balance}=\frac{\operatorname{mean}(|\tau_{human}+\tau_{exo}-\tau_{baseline}|)}
{\max(\operatorname{mean}(|\tau_{exo}|),\tau_{floor})}
$$

`balance` 不再作为一个可与省力交换的微小线性 Reward，也不等同于物理摔倒。正 effort 的门控使用 `MuscleLoadSharing` 在当前姿态下求解目标激活时得到的预测残差，因为它直接回答“该助力是否存在可行的肌肉卸载解”。肌肉激活存在动力学延迟，物理积分后的实际瞬时残差会另外记录为诊断量，但不直接关掉当步 effort。`muscle_torque_saving` 退出 Reward，只作为诊断指标。若预测残差长期偏高，必须先修正 `MuscleLoadSharing`，不能靠调小权重掩盖；若实际残差长期偏高并导致 tracking 退化，则由 tracking 门控和异常终止处理。

力矩平滑使用二阶差分：

$$
c_{jerk}=\operatorname{mean}\left[
\left(\frac{\tau_t-2\tau_{t-1}+\tau_{t-2}}
{6\,\mathrm{Nm}}\right)^2\right]
$$

其中 $6\,\mathrm{Nm}$ 只是额定力矩归一化尺度。两步历史在每次 `reset()` 清零；一阶变化率继续由执行器硬限制负责。

功率必须逐关节计算 $P_i=\tau_i\dot q_i$，禁止先把四关节求和后取绝对值，以免正负功互相抵消。V2 只惩罚超过免费正功阈值的部分：

$$
c_{P+}=\frac{1}{4}\sum_i\left[
\frac{\max(\max(P_i,0)-P_{free},0)}{P_{scale}}
\right]^2
$$

首版 $P_{free}=20\,\mathrm{W}$、$P_{scale}=20\,\mathrm{W}$，并在评估中输出逐关节 `P95/P99/max` 后再校准。负功单独记录，不与正功抵消；是否加入负功阈值等待电机回馈能力确认。

V2 初始权重固定为：

```text
effort                 1.000
tracking_cost          0.300
upright_cost           0.050
alive                   0.005
torque_cost             0.050
jerk_cost               0.030
positive_power_cost     0.030
abnormal_termination   10.000
```

`upright` 同样采用安全铰链：Kinesis 内置 upright reward 不低于 0.2 时代价为零，低于该值后才按归一化平方产生惩罚，避免把自然躯干前倾优化成僵硬直立。`alive` 的原始值恒为 1，因此每步实际贡献就是 $+0.005$，不能再次乘 `0.005`。骨盆过低、躯干倾角过大、Kinesis tracking failure 或非有限状态属于异常终止；`motion_complete` 和 `time_limit` 是正常截断，不扣终止惩罚。

文件职责如下：

```text
RL/env/kinesis/assist_backend.py
    有界肌肉卸载、逐关节功率、balance 诊断和连续仿真时间

RL/env/kinesis/baseline_reference.py
    零助力 baseline 文件命名、加载、seed 选择和时间插值

RL/runners/collect_kinesis_baseline.py
    对训练/验证 motion 采集成功的零助力 baseline

RL/env/kinesis/exo_env.py
    Reward V2、门控、二阶力矩、17 Nm 动作映射和异常终止

RL/train.py
    TensorBoard 记录 Reward、baseline、门控、功率和额定力矩指标

RL/runners/train_kinesis_exo.py
    baseline 路径检查、训练/验证环境参数和完整配置留档

RL/runners/evaluate_kinesis_exo.py
    同 seed 配对数值评估与带 G-Exo URDF 的 GUI 播放
```

Reward、动作映射和 Critic 目标都已改变，旧的 $\pm2\,\mathrm{Nm}$ PPO checkpoint 不得用 `--resume` 继续训练。新链路必须从头训练并写入新输出目录。训练前依次通过 baseline 采集、零动作复现、固定 oracle、随机动作、Gymnasium `check_env` 和短 PPO smoke；之后才允许开始长训练。

### 20.10 Reward V2 的运行顺序、命令和当前证据

所有命令都从项目根目录运行，并使用 Kinesis 环境：

```bash
cd ~/HK_hackthon/G-Exo
conda activate kinesis
export PYTHONNOUSERSITE=1
export PYTHONPATH="$PWD:$PWD/../third_party/Kinesis"
```

第一次运行 V2 或 baseline 定义改变后，先重新采集 11 条动作、每条 4 个成功 seed 的零助力真值。Kinesis 在同一进程中连续切换 motion 会残留全局动作缓存，因此采集器和多 motion 评估器都让每条 motion 在独立 Python 进程中运行：

```bash
python -m RL.runners.collect_kinesis_baseline \
  --motion-ids 2,8,9,11,16,38,43,52,64,82,99 \
  --rollouts-per-motion 4 \
  --first-seed 0 \
  --max-attempts 32 \
  --output RL/outputs/kinesis_baseline_v2
```

先做零助力复现。每条结果都应成功完成，`activation_change_percent` 应接近 0，当前 tracking MSE 应与缓存 baseline 对齐：

```bash
python -m RL.runners.evaluate_kinesis_exo \
  --motion-ids 2,8,9,11,16,38,43,52,64,82,99 \
  --modes baseline \
  --episodes 1 \
  --baseline-dir RL/outputs/kinesis_baseline_v2 \
  --output RL/outputs/kinesis_baseline_v2/reproducibility_report.json
```

训练前 GUI 顺序播放零助力和固定 oracle。显示模型包含 G-Exo URDF；oracle 使用仿真特权力矩，只验证符号、肌肉卸载、轨迹质量和渲染链路：

```bash
python -m RL.runners.evaluate_kinesis_exo \
  --motion-ids 8 \
  --modes baseline,oracle \
  --episodes 1 \
  --first-seed 0 \
  --baseline-dir RL/outputs/kinesis_baseline_v2 \
  --render \
  --output RL/outputs/kinesis_exo_evaluation/reward_v2_pretrain_render.json
```

最小 8-worker PPO smoke 用于验证并行环境、Reward、日志和模型保存，不用于判断策略效果：

```bash
python -m RL.runners.train_kinesis_exo \
  --baseline-dir RL/outputs/kinesis_baseline_v2 \
  --total-timesteps 4096 \
  --num-envs 8 \
  --device cpu \
  --output RL/outputs/kinesis_exo_reward_v2_8env_smoke
```

通过 smoke 后，从头开始八小时训练。不能恢复旧 Reward 或旧 $\pm2\,\mathrm{Nm}$ checkpoint：

```bash
python -m RL.runners.train_kinesis_exo \
  --baseline-dir RL/outputs/kinesis_baseline_v2 \
  --hours 8 \
  --total-timesteps 100000000 \
  --num-envs 8 \
  --device cpu \
  --output RL/outputs/kinesis_exo_ppo_reward_v2_8h
```

训练期间查看数值：

```bash
tensorboard \
  --logdir RL/outputs/kinesis_exo_ppo_reward_v2_8h/tensorboard \
  --port 6006
```

需要观察中间模型时，另开终端对最新 checkpoint 做一次单 motion 渲染。把下面模型路径替换为实际存在的 checkpoint；渲染进程只读取模型，不影响训练文件：

```bash
python -m RL.runners.evaluate_kinesis_exo \
  --model RL/outputs/kinesis_exo_ppo_reward_v2_8h/checkpoints/gexo_ppo_500000_steps.zip \
  --motion-ids 64 \
  --modes baseline,policy \
  --episodes 1 \
  --baseline-dir RL/outputs/kinesis_baseline_v2 \
  --device cpu \
  --render \
  --output RL/outputs/kinesis_exo_ppo_reward_v2_8h/render_500000.json
```

训练结束后必须在三个留出动作上做配对数值评估。先使用 `best_model`；若它不存在，再用 `final_model.zip`：

```bash
python -m RL.runners.evaluate_kinesis_exo \
  --model RL/outputs/kinesis_exo_ppo_reward_v2_8h/best_model/best_model.zip \
  --motion-ids 64,82,99 \
  --modes baseline,policy \
  --episodes 3 \
  --baseline-dir RL/outputs/kinesis_baseline_v2 \
  --device cpu \
  --output RL/outputs/kinesis_exo_ppo_reward_v2_8h/holdout_report.json
```

截至 2026-07-30，V2 已有以下实测证据：

- 44 个成功 baseline 文件已生成；11 条 motion 的 seed 0 复现均成功，激活变化为 0；
- Gymnasium `check_env` 通过，144 维 Observation、4 维 Action 和 100 步随机动作均为有限值；
- motion 8 的 2.5% oracle 完整走完，MPJPE 从 42.89 mm 降到 42.45 mm，激活平方降低 5.13%，人体肌肉力矩降低 2.26%；
- oracle 的预测 balance 残差比为 0.01%，实际瞬时残差比约为 98.47%，后者体现肌肉激活动力学延迟，已单独记录；
- 8-worker、4096-transition smoke 约为 299 transition/s，成功保存 `final_model.zip`；
- smoke 模型在留出 motion 64 上成功完整运行，激活平方降低 3.39%，但 MPJPE 从 48.76 mm 增至 54.41 mm。该模型只证明训练、保存和加载链路闭环，不能作为已收敛结果。

长训练的第一验收顺序固定为：成功率/覆盖率不下降，留出 MPJPE 不明显恶化，真实 baseline 相对激活平方下降，然后才检查力矩、jerk、逐关节功率和额定力矩超限比例。只看到训练回报上升不能宣布策略有效。

### 20.11 肌肉卸载求解失败的训练容错

首轮 Reward V2 五小时训练在 1,699,840 transition 处遇到一次 SciPy BVLS 内部 `SVD did not converge`。这是单个姿态下解析肌肉卸载最小二乘的数值失败，不应杀死整个 `SubprocVecEnv` 和全部 PPO worker。

容错数据流固定为：

```text
BVLS 输入非有限 / LinAlgError / 求解未成功
                    ↓
回退冻结 Kinesis 的名义肌肉 excitation
                    ↓
撤销尚未积分的外骨骼力矩并保留最后有限状态
                    ↓
terminated=True, reason=muscle_solver_failure, reward=-10
                    ↓
VecEnv 自动 reset；其余 worker 和 PPO 继续训练
```

失败回退不能产生 effort、tracking 或其他正奖励，只产生异常终止惩罚，防止策略主动寻找求解器失败状态。TensorBoard 使用 `system/muscle_solver_failure_rate` 记录每个 rollout 的失败 transition 比例；正常情况应为 0，偶发极低值允许继续训练，若持续升高则必须检查动作幅值、人体状态和求解矩阵条件数。

该修复不改变 Observation、Action、Reward 权重、力矩边界或 PPO 超参数，因此可以从崩溃前最近的 150 万步 checkpoint 继续。为避免新的 `EvalCallback` 覆盖原目录中的 25 万步最佳模型，续训写入独立输出目录：

```bash
cd ~/HK_hackthon/G-Exo
conda activate kinesis
export PYTHONNOUSERSITE=1
export PYTHONPATH="$PWD:$PWD/../third_party/Kinesis"

python -m RL.runners.train_kinesis_exo \
  --baseline-dir RL/outputs/kinesis_baseline_v2 \
  --resume RL/outputs/kinesis_exo_ppo_reward_v2_5h/checkpoints/gexo_ppo_1500000_steps.zip \
  --hours 3.4 \
  --total-timesteps 100000000 \
  --num-envs 8 \
  --device cpu \
  --seed 42 \
  --output RL/outputs/kinesis_exo_ppo_reward_v2_5h_resume
```

`--hours 3.4` 表示本次续训再运行约 3.4 小时，与已完成的 1.62 小时合计约 5 小时；`--total-timesteps` 在 `reset_num_timesteps=False` 下作为额外安全上限，不会把模型总步数重置为 0。

修复验收包括：人为注入同样的 `LinAlgError` 后环境返回有限 Observation、`-10`、`terminated=True` 和 `muscle_solver_failure`；随后 reset 能正常步进；8-worker 从 1,500,000 续训 4096 transition 后到达 1,504,096，并成功保存模型，吞吐约 302 transition/s。

## 21. 2026-08-02 路线覆盖：冻结 Kinesis 不再承担生理 Reward 真值

本节覆盖第 20 节中“冻结 Kinesis + 肌肉 Reward 从零训练外骨骼 PPO”的执行顺序，
但不删除已经完成的 Kinesis、动态 URDF、TCN、PPO、基线和审计文件。

冻结 Kinesis 会读取受助力后的状态并继续追踪原动作，可能主动补偿外骨骼作用。
当前肌肉变化同时混合物理卸载、`MuscleLoadSharing` 重分配和 Kinesis 反馈补偿，
不能作为真人自然利用助力后的直接生理真值。人为删除反作用或从黑盒策略输出中
拆分“名义动作/纠偏动作”同样不可取，因为这会把设计规则写入肌肉 Reward。

当前短期主线固定为：

```text
Phase 1/2 与 Kinesis 参考运动
        -> 固定轨迹肌肉--外骨骼联合优化
        -> 四关节最优助力标签
        -> 冻结 TCN + 监督学习四输出 Actor
        -> Kinesis + 动态 URDF 只做稳定性、安全和渲染复核
        -> 可选的小幅 residual PPO
```

TCN 负责提供 100/200 ms 未来运动特征，不能修复肌肉 Reward 的物理因果性。
PPO 不再负责从冻结 Kinesis 的低信噪比 effort Reward 中发现完整助力规律，只能在
监督 Actor 周围做小残差稳定性修正。首个可展示版本预计 `6--12 h`；进入 Actor
训练前必须先用 3 条代表性 motion 完成固定轨迹优化 P0，并确认激活平方、逐肌肉
绝对力矩成本、求解残差和电机约束同时通过。

完整的有效性边界、已用/未用方案、否决理由、优化公式、验收条件和长期路线见：

```text
RL/PHYSICAL_PPO_AUDIT.md 第七至第九节
```
