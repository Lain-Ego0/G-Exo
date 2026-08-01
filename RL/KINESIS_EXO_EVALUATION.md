# Kinesis 外骨骼策略评估手册

本文档对应入口：`RL/runners/evaluate_kinesis_exo.py`。

## 1. 评估数据流

```text
model.zip
    -> 向上查找本次训练的 config.json
    -> 恢复 Observation 类型、TCN 资产、Baseline 和动作力矩尺度
    -> 相同 motion、相同 seed 分别执行 baseline 与 policy
    -> 保存逐 Episode 的 rows 和跨 Episode 的 summary
```

评估脚本会自动恢复以下训练契约：

- `action_torque_scale_nm`；
- 是否启用 TCN；
- TCN checkpoint 和 calibration；
- Baseline 数据目录；
- 策略 Observation 维数。

因此，评估正常训练产物时不要重复手写 `--use-tcn` 或
`--action-scale-nm`。脚本会检查策略输入维数与环境是否一致，避免用 144 维
环境错误评估 160 维策略，也避免把按 4 Nm 训练的策略误缩放成 0.5 Nm。

## 2. 终端准备

```bash
cd ~/HK_hackthon/G-Exo

export KINESIS_PY=/mnt/kinesis-fast/kinesis/envs/kinesis/bin/python
export PYTHONPATH="$PWD:$PWD/../third_party/Kinesis"
export MPLCONFIGDIR=/tmp/gexo-matplotlib
mkdir -p "$MPLCONFIGDIR"
```

直接使用 Kinesis 环境中的 Python，可以避免 Conda 找不到外置环境名称的问题。

## 3. 标准留出集评估

以下命令在三条留出 motion 上，使用相同 seed 配对比较零助力与确定性 PPO
策略：

```bash
RUN=RL/outputs/kinesis_exo_tcn_explicit_160_std1_1m

"$KINESIS_PY" -m RL.runners.evaluate_kinesis_exo \
  --model "$RUN/best_model/best_model.zip" \
  --motion-ids 64,82,99 \
  --modes baseline,policy \
  --episodes 3 \
  --first-seed 0 \
  --device cpu \
  --output "$RUN/holdout_best.json"
```

每条 motion 至少使用 3 个 seed。正式报告建议使用 5 至 10 个 seed。

## 4. 评估指定检查点

训练进行中应优先评估已经完整写入的 checkpoint，不要读取正在被更新的模型文件：

```bash
RUN=RL/outputs/kinesis_exo_tcn_explicit_160_std1_1m

"$KINESIS_PY" -m RL.runners.evaluate_kinesis_exo \
  --model "$RUN/checkpoints/gexo_ppo_500000_steps.zip" \
  --motion-ids 64,82,99 \
  --modes baseline,policy \
  --episodes 3 \
  --device cpu \
  --output "$RUN/holdout_500k.json"
```

把文件名中的 `500000` 换成实际 checkpoint 步数即可。

## 5. 渲染查看

渲染时只选择一条 motion 和一个 seed，baseline 与 policy 会依次播放：

```bash
RUN=RL/outputs/kinesis_exo_tcn_explicit_160_std1_1m

"$KINESIS_PY" -m RL.runners.evaluate_kinesis_exo \
  --model "$RUN/best_model/best_model.zip" \
  --motion-ids 82 \
  --modes baseline,policy \
  --episodes 1 \
  --render \
  --output "$RUN/render_motion_082.json"
```

渲染使用实时 50 Hz 播放，所以比无渲染评估慢。无图形界面或远程终端缺少
OpenGL/X11 时，不要使用 `--render`。

## 6. 可用模式

| 模式 | 含义 | 用途 |
|---|---|---|
| `baseline` | 外骨骼输出为零 | 所有省力指标的配对基线 |
| `policy` | PPO 确定性动作 | 正式策略评估 |
| `oracle` | 使用仿真特权肌肉力矩 | 验证助力方向，不可部署 |
| `positive_constant` | 固定正力矩 | 检查符号和剂量响应 |
| `negative_constant` | 固定负力矩 | 检查符号和剂量响应 |
| `velocity_assist` | 与关节速度同向 | 物理对照实验 |
| `velocity_resist` | 与关节速度反向 | 负面对照实验 |

测试模式可通过 `--test-torque-nm` 设置力矩；oracle 可通过
`--oracle-gain` 设置比例。

## 7. 指标符号

激活变化定义为：

$$
\Delta_a = 100\left(\frac{C_{a,\mathrm{policy}}}
{C_{a,\mathrm{baseline}}}-1\right)\%.
$$

肌肉力矩变化定义为：

$$
\Delta_\tau = 100\left(\frac{C_{\tau,\mathrm{policy}}}
{C_{\tau,\mathrm{baseline}}}-1\right)\%.
$$

因此这两个指标都是负数表示省力，正数表示人体负担增加。

重点读取 `summary` 中的以下字段：

| 字段 | 解释 | 趋势 |
|---|---|---|
| `success_rate` | 完整走完比例 | 越高越好 |
| `mean_mpjpe_mm` | 人体关节点跟踪误差 | 越低越好 |
| `pooled_activation_change_percent` | 按总时长汇总的激活变化 | 负数为省力 |
| `pooled_muscle_torque_change_percent` | 按总时长汇总的肌肉力矩变化 | 负数为省力 |
| `mean_absolute_exo_torque_nm` | 平均绝对电机力矩 | 只表示用力大小 |
| `mean_actual_balance_residual_ratio` | 实际力矩平衡残差 | 越低越好 |
| `mean_activation_overload_topk` | 最严重一组肌肉的过载 | 越低越好 |
| `rated_torque_exceed_ratio` | 超过 6 Nm 额定力矩的比例 | 应为零 |
| `positive_exo_work_j` | 外骨骼正机械功 | 结合省力一起判断 |
| `negative_exo_work_j` | 外骨骼负机械功 | 绝对值过大可能表示抵抗人体 |

跨不同长度的 motion 比较时，以 `pooled_*` 为主，而不是各 Episode 百分比的
简单平均。

## 8. 当前阶段判据

最低有效性要求：

1. `success_rate = 1.0`；
2. 两个 `pooled_*_change_percent` 都小于零；
3. Policy MPJPE 相对 Baseline 增量不超过 2 mm；
4. `rated_torque_exceed_ratio = 0`；
5. 省力不能以明显肌肉过载或力矩平衡恶化为代价。

当前项目候选策略目标高于最低要求：激活至少下降 5%，肌肉力矩至少下降 3%。
达不到该目标的模型只能用于验证流水线，不能宣称达到外骨骼助力要求。

## 9. 外部模型与手动覆盖

如果只复制了 `model.zip` 而没有一并保留训练目录中的 `config.json`，脚本无法知道
动作力矩尺度。此时必须显式给出环境契约：

```bash
"$KINESIS_PY" -m RL.runners.evaluate_kinesis_exo \
  --model /path/to/model.zip \
  --action-scale-nm 4.0 \
  --use-tcn \
  --tcn-checkpoint RL/outputs/tcn_runs/seed_43/best_model.pt \
  --tcn-calibration RL/assets/tcn/kinesis_phase12_explicit_calibration.json \
  --baseline-dir RL/outputs/kinesis_physical_baseline_v2 \
  --motion-ids 64,82,99 \
  --modes baseline,policy \
  --episodes 3 \
  --output RL/outputs/manual_holdout.json
```

144 维无 TCN 策略使用 `--no-tcn`。动作力矩尺度必须与训练时完全一致。

## 10. 接口验收记录

2026-07-31 使用当前 250k 最佳模型完成自动配置验收：

- 自动识别 Observation 为 160 维；
- 自动启用 TCN；
- 自动恢复动作尺度为 4 Nm；
- 三条留出 motion 均成功完成；
- 报告位于
  `RL/outputs/kinesis_exo_tcn_explicit_160_std1_1m/holdout_best_auto.json`。

