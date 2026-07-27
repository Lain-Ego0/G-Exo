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
