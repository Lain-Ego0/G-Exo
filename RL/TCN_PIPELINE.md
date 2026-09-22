# TCN 训练与检测流水线

TCN 接入 Kinesis/PPO 的传感器适配、Actor 数据流和肌肉生理评价见
[`TCN_PHYSIOLOGY_DESIGN.md`](TCN_PHYSIOLOGY_DESIGN.md)。

这套流水线将 50 Hz 外骨骼编码器与四个 IMU 的历史观测映射为未来
100 ms、200 ms 的双腿髋膝角度、角速度和生物关节力矩。TCN 只负责预测，
其输出后续可作为 RL actor 的辅助特征，不直接等同于外骨骼控制力矩。

## 数据流

```text
Phase1/2 CSV
  -> dataset_manifest.py：按受试者划分训练集和验证集
  -> preprocess_tcn.py：200 Hz 转 50 Hz、单位转 SI、保存 NPZ
  -> tcn_dataset.py：生成 1 s 历史窗口和 100/200 ms 标签
  -> predictors/tcn.py：因果 TCN
  -> pretrain_tcn.py：仅用训练集更新参数
  -> check_tcn_pipeline.py：数据、梯度、因果性和检查点检查
  -> evaluate_tcn.py：与均值、保持不变两类基线比较
  -> aggregate_tcn_runs.py：汇总多个随机种子
```

## 设计约束

- 输入是 32 维：4 个编码器角度、4 个编码器滤波角速度、24 个 IMU 量。
- 历史长度是 50 帧，即 1 s；不是 132 或 144 帧。
- 预测目标是 12 维，预测时距是 5/10 帧，即 100/200 ms。
- 生物关节力矩标签单位是 `Nm/kg`；实际输出 `Nm` 时必须乘以使用者质量。
- 训练与验证按受试者隔离，BT15、BT16、BT17 仅用于验证。
- 数据集的 `velocity_filt` 未说明是否为在线因果滤波。部署前必须改用实机的
  在线角速度，或用明确的单向滤波器重建并重新训练。
- 数据集中的外骨骼传感器流已从约 55 Hz 对齐/升采样到 200 Hz；离线训练的
  50 Hz 块平均不应原样照搬到实机。实机侧应直接建立时间戳明确的 50 Hz 在线缓冲区。
- 离线零相位滤波角度、力矩和中心差分速度只作为监督标签，不进入策略观测。

## 完整 CUDA 实验

从工作区根目录运行：

```bash
cd ~/HK_hackthon
export GEXO_DATA_ROOT='<PROJECT_ROOT>'
bash G-Exo/RL/runners/run_tcn_multiseed.sh 42 43 44
```

脚本先验证 CUDA，再依次训练三个随机种子。每个运行目录都包含检查点、配置、
损失历史、TensorBoard 数据、流水线检查和验证集评估；最终汇总写入
`RL/outputs/tcn_runs/aggregate.json`。

训练期间可另开终端查看：

```bash
tensorboard --logdir ~/HK_hackthon/G-Exo/RL/outputs/tcn_runs --port 6006
```

## 单独复查

```bash
PYTHONPATH="$PWD/G-Exo" python -m RL.runners.check_tcn_pipeline \
  --checkpoint G-Exo/RL/outputs/tcn_runs/seed_42/best_model.pt \
  --output G-Exo/RL/outputs/tcn_runs/seed_42/pipeline_check.json

PYTHONPATH="$PWD/G-Exo" python -m RL.runners.evaluate_tcn \
  --device cuda \
  --checkpoint G-Exo/RL/outputs/tcn_runs/seed_42/best_model.pt
```

## Kinesis 坐标标定与留出验收

标定动作只使用训练动作，不能把留出动作 `64、82、99` 加入
`--motion-ids`：

```bash
cd ~/HK_hackthon/G-Exo
PYTHONPATH="$PWD:$PWD/../third_party/Kinesis" \
/mnt/kinesis-fast/kinesis/envs/kinesis/bin/python \
-m RL.runners.calibrate_kinesis_tcn \
  --phase-root '<PROJECT_ROOT>' \
  --motion-ids 2 8 9 11 16 38 43 52 \
  --steps 100 \
  --output RL/assets/tcn/kinesis_phase12_calibration.json
```

标定文件包含编码器正方向/零位、IMU 旋转、TCN 输出到 Kinesis 关节坐标的
尺度和偏置。留出检查命令如下，`--steps 80` 时每个动作至少保留 70 个未来
误差样本：

```bash
PYTHONPATH="$PWD:$PWD/../third_party/Kinesis" \
/mnt/kinesis-fast/kinesis/envs/kinesis/bin/python \
-m RL.runners.check_kinesis_tcn_adapter \
  --motion-id 82 \
  --seed 0 \
  --steps 80 \
  --calibration RL/assets/tcn/kinesis_phase12_explicit_calibration.json \
  --output RL/outputs/kinesis_tcn_adapter/motion_082_seed_0.json
```

验收必须同时比较 `prediction_error.tcn`、`hold` 和 `constant_velocity`。当前
九个留出 episode 的结论是：200 ms TCN 优于两类基线；100 ms 角度预测仍不如
恒速外推。300k TCN-PPO 筛选又显示 latent 接口存在明显的跨步态不稳定，因此
Actor 不再直接读取 64 维 latent。新的候选输入固定为 100/200 ms 两个时距的
`delta_q4 + delta_dq4`，合计 16 维；100 ms 分支只作为短期趋势候选，是否保留由
无 TCN / 显式 TCN 消融决定。生物力矩头仍只用于监督和诊断，不能直接作为电机控制量。

`aggregate.json` 会自动给出 `acceptance.ready_for_myo_rl_prototype`。只有以下条件
同时成立时才为 `true`：至少 3 个种子、每次请求至少 30 epoch、所有流水线检查
通过、TCN 在三个物理量组和两个时距上均优于两类基线、归一化验证 MSE 的
跨种子变异系数不超过 10%。该结论只允许进入 MyoSuite/RL 原型集成，不代表可上实机。

## Phase 3 冻结测试

Phase 3 只用于最终检测，不参与训练、归一化、早停、检查点选择或超参数调整。
严格测试集固定为未在 Phase 1/2 出现的 BT18 至 BT24，只包含标准
`normal_walk`，排除 shuffle 和 skip。执行：

```bash
cd ~/HK_hackthon
export GEXO_DATA_ROOT='<PROJECT_ROOT>'
export GEXO_PHASE3_CACHE="$GEXO_DATA_ROOT/processed/tcn50_phase3"
TCN_DEVICE=cuda bash G-Exo/RL/runners/run_tcn_phase3.sh
```

脚本会重新生成测试清单、同步处理缓存、分别评估 seed 42/43/44、与两类基线
比较并生成 `RL/outputs/tcn_phase3/aggregate.json`、`summary.json` 和 `report.md`。
若不指定 `TCN_DEVICE`，会自动选择 CUDA 或 CPU。

严格集成门槛还要求 Phase 3 按窗口加权的归一化 MSE 不超过原留出验证集的
1.5 倍。按受试者等权指标同时报告，用来解释 trial 数量不均衡，但不能替代
预先设定的严格门槛。
