# Oracle Phase Reward Audit

本审计只回答三个问题：相位计算是否正确、外骨骼动作是否真实改变整周期负担、候选 Reward 的动作信号是否大于不同 seed 的状态差异。它不修改 PPO Reward。当前版本同时测试离线 oracle phase 和只读取历史电机/IMU 的 causal Phase-TCN。

## 文件职责

- `RL/env/kinesis/oracle_phase.py`：足底接触去抖、离线 oracle phase、周期积分和相位成本曲线。
- `RL/env/kinesis/causal_phase.py`：32 维电机/IMU 输入的因果 Phase-TCN、训练和推理。
- `RL/runners/collect_oracle_phase_rollouts.py`：采集同 motion、同 seed 的零助力和相位脉冲轨迹。
- `RL/runners/train_kinesis_phase_tcn.py`：仅使用零助力轨迹训练留一 seed 模型和全量部署模型。
- `RL/runners/analyze_oracle_phase_reward.py`：重新计算各类 Reward，输出排序、符号、基线噪声和动作/seed 方差比。
- `RL/tests/test_oracle_phase.py`、`RL/tests/test_causal_phase.py`：纯计算一致性、因果性和上下文隔离测试。

数据流：

```text
Kinesis/MuJoCo逐帧状态
        -> 32维电机/IMU -> 只读历史的Phase-TCN -> causal phase/rate
        -> 四路足底触觉 -> oracle phase + cycle id（只用于离线标签/评价）
        -> motion + reference seed + reference cycle + phase baseline
        -> Reward排序与动作/seed方差分析
```

oracle phase 使用下一次初始接触来归一化当前周期，因此只能用于离线审计，不能输入 Actor。因果推理不读取触地传感器、未来帧或 oracle phase。审计计算整周期真实省力时仍使用 oracle cycle mask 选择评价区间；该 mask 不参与候选逐步 Reward。

基线有两个层次：

- `exact context` 按 `(motion, reference seed, reference cycle ordinal, phase)` 读取，是训练时已有配对 baseline 的上界。
- `leave-one-seed context` 固定 motion 和 reference cycle ordinal，但从其他 seed 聚合，用于检验跨初始状态泛化，不能包含被评价 seed。

候选逐步期望成本遵循 $c_t^0=e^0(\phi_t)\dot\phi_t$。禁止在看完整个周期后再次把期望成本缩放到已知 baseline 总能量；这种缩放会使任意 phase 都得到相同整周期答案，掩盖相位估计误差。

## 运行

先运行不依赖 Kinesis 的测试：

```bash
cd ~/HK_hackthon
PYTHONPATH="$PWD/G-Exo" \
python -m unittest discover -s G-Exo/RL/tests -v
```

在 Kinesis 环境中采集一个 motion。`KPY` 应指向实际的 Kinesis Python：

```bash
cd ~/HK_hackthon/G-Exo
KPY=/path/to/kinesis/envs/kinesis/bin/python

PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH="$PWD:$PWD/../third_party/Kinesis" \
"$KPY" -m RL.runners.collect_oracle_phase_rollouts \
  --motion-id 8 \
  --seeds 0,1,2 \
  --phases 0.25,0.75 \
  --joints 0,1,2,3 \
  --pulse-nm 1.0,2.0 \
  --pulse-steps 4 \
  --output RL/outputs/oracle_phase_audit/causal_motion_008_traces
```

训练留一 seed Phase-TCN：

```bash
cd ~/HK_hackthon
PYTHONPATH="$PWD/G-Exo" \
python -m RL.runners.train_kinesis_phase_tcn \
  --traces G-Exo/RL/outputs/oracle_phase_audit/causal_motion_008_traces \
  --output G-Exo/RL/outputs/oracle_phase_audit/causal_motion_008_phase_tcn \
  --epochs 500 \
  --device cpu
```

分析不依赖 Kinesis 环境：

```bash
cd ~/HK_hackthon/G-Exo
PYTHONPATH="$PWD" \
python -m RL.runners.analyze_oracle_phase_reward \
  --traces RL/outputs/oracle_phase_audit/causal_motion_008_traces \
  --phase-model-dir RL/outputs/oracle_phase_audit/causal_motion_008_phase_tcn \
  --output RL/outputs/oracle_phase_audit/causal_motion_008_report.json
```

## 三种相位指标

`phase_aligned_score` 使用同 seed、同周期的完整零助力曲线。它是离线 oracle 恒等检查，接近整周期真实省力是设计结果，不能直接证明训练可行。

`pooled_phase_aligned_score` 只按 motion 和 phase 汇总所有周期。它用于证明“相位一致但上下文不同”的混叠风险，不推荐作为训练 Reward。

`context_phase_aligned_score` 使用离线 actual phase 和留一 seed context。

`causal_exact_context_score` 使用因果 Phase-TCN 和同 seed、同参考周期 baseline。

`causal_loso_context_score` 同时使用因果 Phase-TCN 和留一 seed context，是最严格的候选指标，也是当前 PPO 放行判断所使用的指标。

## 当前 motion 8 结果（2026-08-01）

弱脉冲报告使用 3 个 seed、2 个相位、4 个关节、正负 1/2 Nm、80 ms，共 96 条成功轨迹：

- 脉冲参考相位最大误差约 `0.0043 cycle`。
- 当前 same-state Reward 与真实整周期省力的 Spearman 约 `-0.077`。
- 纯时间对齐 Spearman 约 `0.419`。
- 不带上下文的 pooled phase Spearman 约 `0.487`，基线噪声约 `17.8% RMS`。
- Phase-TCN 留一 seed 平均相位误差约 `0.0151 cycle`，最差 fold 的 P95 约 `0.0636 cycle`。
- 64-bin oracle exact-context Spearman 约 `0.998`，符号一致率 `100%`，证明相位成本公式本身成立。
- causal leave-one-seed context Spearman 约 `0.213`，符号一致率约 `35.6%`，未通过。
- 真实动作/seed 方差比约 `0.262`，causal Reward 动作/seed 方差比约 `0.137`，均小于 1。

为区分结构失败和辨识动作过弱，另测试正负 4/6 Nm、160 ms，共 96 条成功轨迹：

- causal leave-one-seed context Spearman 约 `0.391`，符号一致率约 `35.5%`，仍未通过。
- 真实动作/seed 方差比提高到约 `0.459`，但仍小于 1。
- 留一 seed 状态条件探针 $R^2<0$，未发现稳定的跨 seed 映射。

因此当前结论是：相位可由部署信号因果估计，reference cycle/context 也显著降低了 baseline 噪声；但现有单 motion、3 seed 数据下，动作导致的真实省力变化仍小于状态差异，因果 Reward 不能可靠排序动作。`ready_for_short_ppo_ab=False`，不得把该 Reward 接入长程 PPO。

下一步不是继续调 Reward 权重，而是增加零助力 baseline 的 seed 和 motion 覆盖，并用持续一个完整周期的结构化关节动作做系统辨识。只有 causal Reward 达到 Spearman $\ge 0.6$、符号一致率 $\ge 70\%$、动作/seed 方差比 $\ge 1$，才进入短程 PPO A/B。
