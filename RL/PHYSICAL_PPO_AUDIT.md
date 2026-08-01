# 动态外骨骼 PPO 复审记录

更新时间：2026-07-31

本文记录动态 URDF、Kinesis 人体、肌肉负载分担和 PPO 链路的第二轮复审结果。

本文不把“相位对齐”列为当前问题。当前所有训练动作使用固定参考动作和固定仿真时间，现阶段首先要解决的是物理传力、肌肉指标和 PPO 探索稳定性。

## 一、已经确认的内容

### 1. 动态模型可以运行

- 动态模型维度：`nq=46, nv=45, nu=90`。
- 人体原有肌肉执行器：`86` 个。
- 外骨骼新增电机：`4` 个。
- 外骨骼质量：约 `3.098 kg`，与 URDF 质量一致。
- 电机通过大腿、小腿绑带约束向人体传力，不再直接给人体关节写入外力矩。
- 绑带力可以通过同一状态下的“电机开/关差值”提取。

### 2. 基线数据已经补齐

当前动态零电机基线为：

```text
11 个动作 × 3 个 seed = 33 个成功 rollout
```

评估模式已经改为严格 seed 模式。缺失 seed 时直接报错，不再自动映射到其他 seed。

### 3. Kinesis 冷启动已经处理

Kinesis 第一次 reset 与后续 reset 存在一次性差异。现在 `AssistBackend.reset()` 会在每个新 backend 的第一次 reset 时预热一次。

同一 motion、同一 seed 的连续测试已经达到完全一致：

```text
activation、muscle torque、MPJPE 的最大差值 = 0
```

## 二、必须优先修正的问题

> 2026-07-31 修复状态：以下四项 P0 已落实。Balance residual 不再终止
> episode；PPO 动作幅值与 `17 Nm` 硬限额解耦，pilot 默认使用 `0.5 Nm`
> 且 `log_std_init=-3`；激活成本只统计跨越四个目标关节的肌肉；力矩
> 省力项改为逐肌肉绝对力矩贡献。新的 33 份基线位于
> `RL/outputs/kinesis_physical_baseline_v2`。以下内容保留为修复依据。

### P0-1：不能用 balance residual 直接终止 episode

原逻辑位于：

```text
RL/env/kinesis/exo_env.py::_abnormal_termination_reason()
```

`balance residual` 表示肌肉层预测力矩与动力学后验力矩之间的不一致，不等价于人体摔倒。

因此以下逻辑不应作为人体失败条件：

```python
if balance_ratio > MAX_BALANCE_RESIDUAL_RATIO:
    return "excessive_muscle_balance_error"
```

它会把正常的探索动作提前截断，导致 PPO 学习“不要探索”，而不是学习如何助力。

真正的 episode 终止条件应只包括：

- pelvis 高度过低；
- 躯干倾角过大；
- Kinesis 原生 tracking failure；
- 肌肉求解器失败；
- NaN/Inf 或其他数值异常。

Balance residual 可以保留为 TensorBoard 指标和软惩罚，但不应直接终止 episode。

### P0-2：训练探索范围不能直接使用 `±17 Nm`

`17 Nm` 是 URDF 给出的硬限制，不应该成为 PPO 初始探索范围。

当前动作近似为：

$$
\tau_t = 17 a_t, \qquad a_t\in[-1,1]
$$

随机策略经过 rate limiter 后，仍可能在数个控制周期内产生较大的力矩，破坏原始步态。

训练应该使用独立的动作课程：

$$
\tau_t = \tau_{\text{train},k}a_t
$$

推荐阶段：

```text
阶段 1：±0.25 或 ±0.5 Nm
阶段 2：±1 Nm
阶段 3：±2 Nm
阶段 4：±4 Nm
阶段 5：±6 Nm
```

`±17 Nm` 只保留为最后的硬安全边界。

同时应使用较小的初始策略方差，例如 `log_std_init=-3`，避免刚开始就输出大幅随机力矩。

### P0-3：激活奖励不应统计全部 86 块肌肉

当前激活成本类似于：

```python
np.mean(np.square(state["muscle_activation"]))
```

这会把上身和不跨越目标关节的肌肉也纳入外骨骼省力奖励。

正确的目标肌肉集合应定义为：

$$
\mathcal{M}_{target}
=
\left\{i\mid \exists j\in\{hip_l,knee_l,hip_r,knee_r\},\ |r_{ij}|>\epsilon\right\}
$$

其中 $r_{ij}$ 是肌肉 $i$ 对目标关节 $j$ 的力矩臂。

之后需要同步修改：

- `AssistBackend` 的目标肌肉 mask；
- `collect_kinesis_baseline.py` 的保存字段；
- `BaselineReference` 的读取字段；
- `exo_env.py` 的 activation reward；
- 33 个基线文件。

### P0-4：净关节力矩不能单独代表肌肉负担

当前关节力矩是：

$$
\tau_j=\sum_i r_{ij}f_i
$$

拮抗肌可能互相抵消，使净关节力矩变小，但肌肉本身仍然很用力。

因此需要同时记录两个量：

1. `net_joint_torque`：用于动力学和平衡；
2. `muscle_effort_torque`：用于省力奖励。

推荐肌肉力矩成本为：

$$
C_{muscle}
=
\frac{1}{|\mathcal{M}_{target}|}
\sum_{i\in\mathcal{M}_{target}}
\sum_{j\in\mathcal{J}}
|r_{ij}f_i|
$$

这样才能区分“净关节力矩下降”和“肌肉真正省力”。

## 三、当前物理模型风险

### 1. 绑带约束仍需校准

目前测得：

- 四个绑带平均位移误差约 `2.1 cm`；
- 峰值约 `3.4 cm`；
- 部分情况下约束力峰值超过 `500 N`。

这说明动态模型已经能够传力，但还不能称为高精度穿戴模型。

需要继续检查：

- 绑带锚点局部坐标；
- `solref` 和 `solimp`；
- 大腿/小腿几何位置；
- 约束力峰值；
- 是否需要有限宽度的绑带接触几何，而不是单点 `connect` 约束。

### 2. 预测 residual 与实际 residual 仍需分开记录

当前应同时保留：

- `pre_step_predicted_balance_residual`：求解器在当前状态的预测误差；
- `post_step_measured_balance_residual`：动力学积分后的实测误差。

二者不能混成一个指标，也不能把后者直接当作摔倒判断。

## 四、剂量响应测试结论

旧测试脚本：

```text
RL/runners/validate_kinesis_dose_response.py
```

移除错误终止并更换目标肌肉口径后，motion 82、三个 seed 的速度同向
助力结果为：

| 助力上限 | 成功率 | 激活省力 | 逐肌肉力矩省力 | MPJPE 变化 |
|---|---:|---:|---:|---:|
| `0 Nm` | `3/3` | `0.00%` | `0.00%` | `0.00 mm` |
| `0.25 Nm` | `3/3` | `-0.18%` | `-1.94%` | `+2.17 mm` |
| `0.5 Nm` | `3/3` | `-0.34%` | `-3.22%` | `+2.50 mm` |
| `1 Nm` | `3/3` | `-2.70%` | `-3.85%` | `+3.75 mm` |
| `2 Nm` | `3/3` | `-5.06%` | `-6.08%` | `+3.31 mm` |
| `4 Nm` | `3/3` | `-17.28%` | `-13.89%` | `+10.27 mm` |

负值表示人体负担增加。该结果证明物理模型可以完成 `2/4 Nm` 测试，旧失败
确实来自人工终止；同时也证明固定速度同向助力不是有效控制律，PPO 必须从低力矩
范围学习何时、向哪个方向助力。完整报告位于
`RL/outputs/kinesis_dose_response/p0_fixed_motion_082.json`。

## 五、重新进入 PPO 前的顺序

1. ~~删除 balance residual 的硬终止。~~ 已完成。
2. ~~加入动作幅值课程和较小初始策略方差。~~ 已完成初始 `0.5 Nm` 阶段；
   后续通过 `--action-scale-nm` 分阶段扩大。
3. ~~修改激活成本，只统计目标下肢肌肉。~~ 已完成。
4. ~~增加逐肌肉力矩成本，保留净关节力矩作为动力学指标。~~ 已完成。
5. ~~重新生成 33 个带新字段的物理基线。~~ 已完成。
6. ~~重跑 `0/0.25/0.5/1/2/4 Nm` 剂量响应。~~ 已完成 motion 82 基线。
7. 从零开始跑 `200k` pilot，而不是从旧模型 resume。
8. 使用多动作、多 seed 的配对指标选择 checkpoint。
9. 只有低力矩阶段稳定后，才扩大动作范围并进入 `1M` 训练。

## 六、PPO 阶段验收标准

短期 pilot 至少需要满足：

- 所有留出动作完成率接近 `100%`；
- 激活成本和逐肌肉力矩成本均下降，而不是只下降净关节力矩；
- MPJPE 不明显恶化；
- balance residual 只作为监控和软惩罚，不作为普通探索的终止条件；
- 绑带约束误差和峰值力保持在可解释范围；
- PPO 的 reward 提升必须和真实配对省力指标同步。

当前不足 `5%` 激活卸载或不足 `3%` 肌肉力矩卸载的结果，不能视为最终达标结果。
