# RL 修改清单

本文件用于在暂不依赖 Git 的情况下追踪主线改动。每次记录改动日期、文件、原因、实现目标和验证证据。

## 2026-07-29：平地人体基线启动

### `RL/frame.md`

- 追加第 19 节，明确 Phase 1/2 只提供参考运动和聚合动力学标签，不能直接保证 MyoSuite 人体稳定。
- 将人体控制主线固定为“Phase 生物力矩 + PD + 12 维 PPO 平衡残差 - 外骨骼力矩，再经 BVLS 转为 80 维肌肉动作”。
- 记录平地优先、多地形课程、数据划分、heightfield 地形生成方式、CPU/CUDA 训练指令和一晚训练验收标准。
- 将今晚的参数迁移测试命名为 `sim2sim-lite`，与后续严格第二模型 Sim2Sim 区分。

### `RL/env/myosuite/muscle_controller.py`

- `compute()` 新增可选 `residual_torque` 输入。
- 目标人体力矩由原来的“Phase + PD - 外骨骼”扩展为“Phase + PD + 平衡残差 - 外骨骼”。
- 保持旧调用兼容：不提供残差时自动使用 12 维零向量。

### `RL/train.py`

- `train()` 新增独立 `eval_env_factory`，训练环境和留出受试者验证环境不再混用。
- `train()` 新增 `device` 参数，可显式选择 `cpu` 或 `cuda`。
- TensorBoard 回调新增 `human/mean_muscle_activation`。
- `train()` 新增 `resume_from`；断点模型通过 `PPO.load(..., env=train_env)` 恢复，并使用 `reset_num_timesteps=False` 继续累计步数。

### `RL/env/myosuite/human_balance_env.py`

- 新增 74 维平地人体观测和 12 维关节残差动作环境。
- 训练仅使用 Phase 1/2 `off` 参考中的 0.6、1.2 m/s；BT11、BT12 只用于验证。
- 每个 episode 随机选择 trial 和参考起点，Phase 力矩、PD、PPO 残差经现有 BVLS 转为 80 路肌肉动作。
- 修正 MyoSuite 双 `MjData`：Phase 初态从观测数据同步到 `Robot.step()` 的积分数据；骨盆 `qfrc_applied` 直接写入积分数据。
- 将支撑比例改为明确的体重补偿比例：`1.0` 补偿全部体重，`0.0` 完全不补偿，并保留位置和姿态弹簧。
- 支持质量、惯量、阻尼和摩擦缩放，供参数迁移评估使用。

### `RL/runners/train_human_balance.py`

- 新增平地人体 PPO 入口，默认 1000 万步、8 个并行环境。
- 训练环境使用 5 s episode 和 0.5～1.0 支撑课程；验证环境固定半体重支撑并使用 10 s episode。
- 复用 `RL/train.py` 的 checkpoint、独立验证环境和 TensorBoard。
- 新增 `--resume` 参数，允许从已有 zip 模型继续训练。

### `RL/runners/evaluate_human_sim2sim.py`

- 新增冻结 PPO 的名义参数和参数扰动评估。
- 参数扰动固定为质量 `1.05`、阻尼 `1.10`、摩擦 `0.90`、支撑 `0.35`。
- 修复循环计数器 `_` 被 `model.predict()` 策略状态覆盖的问题。
- 报告平均关节 RMSE、肌肉饱和率，并在提供模型时自动运行零残差基线和计算长度提升倍率。
- `--require-pass` 按 frame 第 19.7 节门槛返回成功或非零状态。
- 报告新增 `trained_timesteps` 和五项 gate 的逐项结果。
- 新增 `--play nominal/shifted`、`--play-mode policy/zero/both` 和 `--show-muscles`，可用 MuJoCo viewer 顺序观察相同验证起点的零残差与策略表现。

### 当前验证状态

- `py_compile`：上述环境、控制器、训练入口和评估入口通过。
- Gymnasium/SB3 `check_env`：通过，Observation `(74,)`，Action `(12,)`。
- 动力学同步：相同 seed 下重置后两份 `qpos` 最大差为 `0.0`；支撑 0、0.5、1.0 已产生不同存活结果。
- PPO 冒烟：2 环境、2048 步完成，模型成功保存并重新加载。
- 今晚配置基准：8 环境、8192 步完成，实测约 680～725 steps/s。
- 10 万步 pilot：耗时 2 min 40 s，模型、最佳模型、TensorBoard 和验证结果均已生成。
- 10 种子对照：名义平均长度由 78.8 提高到 184.0 步；参数扰动由 59.1 提高到 175.5 步。
- 当前 pilot 尚未通过最终门槛：名义与扰动环境 1000 步成功率仍为 0，需继续今晚长训练。
- 断点续训 smoke：从 102400 步恢复后正确到达 110592 步，优化更新次数从 120 延续到 130。
- 被中断的 50 万步试跑实际到达 TensorBoard step 245760；仅保存 step 202400 的 best model，没有 final model，不作为已完成训练。
- 更新后的 sim2sim-lite 数值入口通过 2-episode smoke；GUI播放分支需在本机桌面会话中人工确认画面。

### 证据文件

- `RL/outputs/human_balance_smoke/final_model.zip`
- `RL/outputs/human_balance_pilot_100k/final_model.zip`
- `RL/outputs/human_balance_pilot_100k/best_model/best_model.zip`
- `RL/outputs/human_balance_pilot_100k/combined_sim2sim_report.json`
- `RL/outputs/human_balance_pilot_100k/tensorboard/`

## 2026-07-30：冻结 Kinesis 人体上的四关节外骨骼 PPO

### 路线和文档

- `RL/frame.md` 新增第 20 节，固定“冻结 Kinesis 人体策略 + 固定解析肌肉卸力层 + 四输出 PPO”的首版平地主线。
- 固定 50 Hz、4 帧历史、144 维可部署观测和 4 维归一化力矩动作。
- 固定训练 motion `2,8,9,11,16,38,43,52`，留出验证 motion `64,82,99`。
- 明确 TCN 暂不接入 V0，先验通 PPO 动态助力，再以相同评估口径接入 TCN latent。

### `RL/env/kinesis/teacher.py`

- 从脉冲测试脚本中迁出 `KinesisPolicy` 和 `make_agent()`，形成环境层可复用的冻结人体策略加载模块。
- 每个 PPO worker 只加载一个 motion，并强制 Kinesis 教师策略运行在 CPU。
- 支持 `headless` 训练和 GUI 播放两种创建方式。

### `RL/env/kinesis/assist_backend.py`

- 状态回传新增实际 `muscle_activation` 和无助力反事实 `shadow_activation`。
- 继续复用已验证的 `MuscleLoadSharing`、四关节力矩执行器、$\pm2\,\mathrm{Nm}$ 峰值和 $50\,\mathrm{Nm/s}$ 变化率硬限制。

### `RL/env/kinesis/exo_env.py`

- 新增最小 Gymnasium 外骨骼环境，冻结 Kinesis 的 86 维人体肌肉策略，只训练四关节外骨骼动作。
- 单帧由四电机位置/速度、四个刚体 IMU 角速度/比力和上一动作组成；4 帧拼接为 144 维 Observation。
- IMU 使用 Kinesis 已有 `framelinvel`/`frameangvel` 传感器，线速度差分后减重力并转至刚体局部坐标系。
- Reward 集中在文件顶部 `REWARD_WEIGHTS` 与 `_compute_reward()`；肌肉和参考信息只进入 Critic 训练目标所依赖的 reward/info，不进入 Actor Observation。
- TensorBoard 可追踪跟踪、直立、激活卸载、肌肉力矩卸载、力矩、平滑、负功、平衡误差和终止项。

### `RL/train.py`

- 通用训练器支持“每个 worker 使用不同 factory”，从而让 8 个进程固定覆盖 8 条训练 motion。
- 新增 `WallClockStopCallback`；到达指定墙钟时间后正常结束 `learn()` 并保存最终模型。
- TensorBoard 新增实际/影子肌肉激活、MPJPE 和外骨骼功率。
- 修正 `SubprocVecEnv` 参数名为 `start_method`，保留旧 MyoSuite 训练入口兼容性。

### `RL/runners/train_kinesis_exo.py`

- 新增 Kinesis 外骨骼 PPO 训练入口，复用 `RL/train.py`，不复制 PPO 实现。
- 默认网络沿用通用训练器的 Actor/Critic `[128, 64]`，本入口覆盖为 `n_steps=512`、`batch_size=256`、`n_epochs=5`、`learning_rate=3e-4`。
- 训练前写出 `config.json`，记录步态划分、频率、观测/动作维度、力矩约束和 Reward 权重。

### `RL/runners/evaluate_kinesis_exo.py`

- 新增 `baseline`、`oracle` 和 `policy` 三种统一评估/播放模式。
- `oracle` 使用 2.5% 仿真生物力矩，只是特权上界和方向检查，不作为部署策略。
- 输出成功率、MPJPE、实际/影子激活平方、人体肌肉力矩、外骨骼力矩、力矩平衡误差和正负机械功。
- `--render` 与数值评估使用同一环境和控制路径，以 50 Hz 实时播放。

### Kinesis 第三方兼容补丁

- `third_party/Kinesis/src/KinesisCore/kinesis_core.py` 原本在单 motion 加载时也无条件创建 `multiprocessing.Manager`。
- SB3 的 daemon worker 不能创建子进程，因此改为仅在动作加载包含多个并行 job 时创建 Manager/Queue。
- 当前每 worker 单 motion 走串行加载；Kinesis 原有多 motion 并行路径不变。

### 环境依赖

- 在现有 `kinesis` 环境中安装 `stable-baselines3==2.4.1` 和 `tensorboard==2.13.0` 及其缺失依赖。
- `PYTHONNOUSERSITE=1 python -m pip check` 返回 `No broken requirements found.`。

### 验证证据

- 语法检查：新增/修改的 Kinesis 环境、训练和评估入口均通过。
- Gymnasium `check_env`：通过，Observation `(144,)`，Action `(4,)`。
- 动力学 smoke：零动作和随机动作各 100 步，状态与 Reward 均为有限值。
- 2-worker PPO：8192 transition 完成，模型保存并可在留出 motion 64 加载评估。
- 8-worker PPO：8 条训练 motion 全部成功加载，首轮吞吐约 445 transition/s。
- 墙钟停止：3.6 秒上限测试在 1024 transition 后正常退出并保存模型。
- 训练前配对：motion 8 的 baseline MPJPE 为 41.26 mm；2.5% oracle MPJPE 为 40.99 mm，激活平方变化为 -0.28%，人体肌肉力矩变化为 -0.48%。
- 8192 步 smoke 策略在留出 motion 64 上成功走完，但 MPJPE 55.24 mm、平均外骨骼力矩 0.06 Nm；该结果仅证明接口贯通，不代表收敛。

### 证据文件

- `RL/outputs/kinesis_exo_evaluation/pretrain_smoke.json`
- `RL/outputs/kinesis_exo_spawn_smoke/final_model.zip`
- `RL/outputs/kinesis_exo_smoke/final_model.zip`
- `RL/outputs/kinesis_exo_smoke/evaluation_smoke.json`
- `RL/outputs/kinesis_exo_8env_benchmark/final_model.zip`
- `RL/outputs/kinesis_exo_wallclock_smoke/final_model.zip`

### 2026-07-30 补充：Kinesis 渲染接入 G-Exo URDF

#### `RL/env/myosuite/exo_overlay.py`

- 直接复用原 `GExoMocapDriver`、URDF link/joint 解析和已校正的外骨骼安装变换。
- 将 `str.removeprefix()` 改为 Python 3.8 可用的等价切片，兼容 Kinesis 环境。
- 为没有 `MjSpec` 的 MuJoCo 3.1.2 增加 XML fallback：通过 `mj_saveLastXML` 展开 Kinesis 嵌套 include，修正编译资源目录，再插入五个 URDF mocap link。
- 新增 `_validate_overlay_model()`，生成后强制验证 `nq/nv/nu` 不变且 `nmocap=5`。
- 新增 `GExoOverlayViewer`，把原始动力学模型的 `qpos/qvel/act/ctrl` 复制到显示模型，并在每帧更新 URDF 正运动学。

#### `RL/env/kinesis/exo_env.py`

- Kinesis 教师继续加载原始人体模型，避免五个显示 body 改变预训练策略 Observation。
- `render_mode="human"` 时创建 `GExoOverlayViewer`；headless PPO 不生成或加载显示模型。
- `render()` 改为同步带完整 G-Exo URDF 的显示模型，`close()` 同时关闭独立 MuJoCo viewer。

#### 验证证据

- Kinesis 原动力学模型：`nq=38, nv=37, nu=86`。
- Kinesis+G-Exo 显示模型：`nq=38, nv=37, nu=86, nmocap=5`。
- motion 8 reset 后 Observation 仍为 `(144,)`，五个 URDF mocap 位姿均为有限值。
- 带 GUI 的 baseline 完整运行 217 步，成功结束，MPJPE 为 41.26 mm，与接入前结果一致。
- 离屏截图确认背板、左右髋膝电机及大腿/小腿连杆方向和人体贴合关系正确。
- 生成模型：`RL/output/demo_7_27/generated/kinesis_gexo.xml`。
- GUI 报告：`RL/outputs/kinesis_exo_evaluation/urdf_render_smoke.json`。
- 验证截图：`RL/outputs/kinesis_exo_evaluation/urdf_render_smoke.png`。

## 2026-07-30：Kinesis 外骨骼 Reward V2

### 设计结论

- 跟踪由优化目标改为相对零助力 baseline 的铰链约束；阈值内不产生梯度。
- 人体减负只使用同 motion、seed、仿真时间的真实零助力激活平方，不再用同状态 `shadow_activation` 冒充反事实真值。
- 激活省力为唯一主目标；增力按两倍负值惩罚，且负 effort 永远不受门控隐藏。
- 正 effort 同时经过 tracking 与解析肌肉卸载可行性门控。
- 删除 `muscle_torque_saving` 和 `balance_cost` Reward；二者只保留为诊断。
- 平滑代价改为力矩二阶差分；功率改为逐关节正功阈值，避免关节间正负功抵消。
- 直立项改为安全铰链，正常自然前倾不参与优化；只有明显失稳才产生代价。
- 动作峰值固定为灵足 2 峰值 $17\,\mathrm{Nm}$，$6\,\mathrm{Nm}$ 额定值只用于归一化和超限统计，变化率仍由执行器硬限制实现。

### `RL/env/kinesis/baseline_reference.py`

- 新增 baseline 文件命名、合法性检查、成功 seed 映射和连续仿真时间插值。
- tracking 统一使用仿真时间映射到 Kinesis 参考帧，消除 50 Hz 外骨骼控制与 30 Hz motion 帧率错位。

### `RL/runners/collect_kinesis_baseline.py`

- 新增 50 Hz 零助力 baseline 采集，保存激活平方 EMA、tracking MSE、MPJPE 和时间轴。
- 只接受完整成功 rollout；每条 motion 默认保存 4 个成功 seed。
- 修正 Kinesis 进程级 motion 缓存污染：多 motion 请求由父进程逐条启动独立 Python 子进程。

### `RL/env/kinesis/teacher.py`

- `KinesisPolicy.reset()` 同时固定 Python、NumPy 和 Torch 随机种子，使 baseline 与助力 rollout 可配对复现。

### `RL/env/kinesis/assist_backend.py`

- 肌肉卸载求解由只允许降激活的 NNLS 改为 $[0,1]$ 有界最小二乘，允许受外力后必要的协同肌肉增激活。
- 四个目标自由度使用高权重，其余自由度使用低权重，同时保留名义激活与低 effort 正则。
- 回传求解目标激活的预测 balance 残差、积分后实际 balance 残差和逐关节外骨骼功率。
- 零力矩严格旁路求解器，保证 baseline 与原 Kinesis 人体一致。

### `RL/env/kinesis/exo_env.py`

- 接入 `BaselineReference`，每个 episode 只从对应 motion 已成功缓存的 seed 中选择。
- 动作映射改为 $[-17,17]$ Nm，额定 $6$ Nm 用于 torque/jerk 归一化。
- 实现真实激活平方 effort、相对 tracking hinge、正 effort 双门控、二阶 jerk、逐关节正功阈值和异常终止。
- 新增低骨盆、过大躯干倾角、非有限状态等明确异常检查；正常 motion 完成不扣终止惩罚。
- `info` 同时输出 baseline、门控、预测/实际平衡残差、逐关节功率和额定力矩超限比例。

### `RL/train.py`

- TensorBoard 增加真实/baseline 激活平方、raw/valid effort、tracking excess、两道 gate、预测/实际 balance 残差、二阶 jerk、逐关节正功和额定力矩超限比例。

### `RL/runners/train_kinesis_exo.py`

- 启动 worker 前检查全部训练和留出 motion 的 baseline 是否完整。
- `config.json` 保存 baseline 绝对路径、Reward 权重/阈值、17 Nm 峰值、6 Nm 额定值和 50 Nm/s 变化率。
- 保持现有 PPO 实现和 8 个 motion-worker 分工，不复制训练算法。

### `RL/runners/evaluate_kinesis_exo.py`

- baseline、oracle、policy 使用同 seed 和同一套真实 baseline 指标。
- 报告逐关节正功 P95/P99/max、正负机械功、预测/实际 balance 残差、激活平方和 tracking 对照。
- 多 motion 评估与采集器一样使用进程隔离，避免 Kinesis 全局 motion 缓存串扰。

### 验证证据

- baseline 缓存：`RL/outputs/kinesis_baseline_v2/`，共 11 条 motion、44 个成功 rollout。
- 全 motion 复现：`RL/outputs/kinesis_baseline_v2/reproducibility_report.json`，seed 0 全部成功且激活变化为 0。
- 训练前对照：`RL/outputs/kinesis_exo_evaluation/reward_v2_pretrain_smoke.json`。
- motion 8 oracle：MPJPE 42.45 mm，激活平方降低 5.13%，肌肉力矩降低 2.26%，平均外骨骼力矩 1.19 Nm。
- Gymnasium 门禁：`check_env` 通过，随机动作 100 步无 NaN/Inf。
- 8-worker PPO smoke：`RL/outputs/kinesis_exo_reward_v2_8env_smoke/final_model.zip`，4096 transition、约 299 transition/s。
- 留出加载评估：`RL/outputs/kinesis_exo_reward_v2_8env_smoke/holdout_motion64.json`，baseline 和 smoke policy 均完整运行。

### 运行入口

- 完整命令、顺序、GUI 渲染和长训练验收规则统一记录在 `RL/frame.md` 第 20.10 节。
- Reward V2 必须从头训练，禁止恢复旧 Reward 或旧 $\pm2\,\mathrm{Nm}$ checkpoint。

## 2026-07-30：肌肉卸载 SVD 失败容错

### 故障

- Reward V2 五小时训练在 1,699,840 transition、1.62 小时时，`scipy.optimize.lsq_linear(method="bvls")` 内部抛出 `LinAlgError: SVD did not converge`。
- 一个 Kinesis worker 异常退出后，整个 `SubprocVecEnv` 无法继续；最近 checkpoint 为 1,500,000 步。

### `RL/env/kinesis/assist_backend.py`

- 求解前检查矩阵和目标是否全部有限。
- 捕获 `LinAlgError`、非法输入和 `result.success=False`，不再向 PPO worker 抛出异常。
- 失败时回退 Kinesis 名义 excitation、撤销尚未积分的外骨骼力矩、保留最后有限状态并回传失败原因。
- 失败 transition 的诊断数组保持有限，避免 NaN/Inf 进入 SB3 rollout buffer。

### `RL/env/kinesis/exo_env.py`

- 将 backend 失败转换为 `terminated=True`、`termination_reason=muscle_solver_failure` 和固定 `-10`。
- 失败步不计算 effort 等正奖励，不能被策略利用。
- 正常和失败 info 均输出 `muscle_solver_failed` 0/1 指标。

### `RL/train.py`

- TensorBoard 新增 `system/muscle_solver_failure_rate`，按整个 rollout 的 transition 求均值。

### `RL/runners/train_kinesis_exo.py`

- `config.json` 新增 `resume_from` 绝对路径，保证续训来源可以追溯。

### 验证证据

- 故障注入：强制 `lsq_linear()` 抛出相同 `LinAlgError`，环境正确返回 `-10`、异常终止、有限 Observation 和完整失败原因。
- 恢复测试：故障 episode 后 reset 成功，零动作正常步进。
- 断点续训：8-worker 从 1,500,000 步 checkpoint 额外训练 4096 transition，正确到达 1,504,096 步。
- 续训 smoke：`RL/outputs/kinesis_exo_solver_resume_smoke/final_model.zip`，吞吐约 302 transition/s，失败率为 0。
- 正式续训命令与独立输出目录记录在 `RL/frame.md` 第 20.11 节。
