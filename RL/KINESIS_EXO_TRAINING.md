# Kinesis 外骨骼 PPO 训练手册

本文档对应训练入口：`RL/runners/train_kinesis_exo.py`。

当前推荐版本为：

```text
160维 Observation = 144维传感器历史 + 16维显式 TCN 预测
4维 Action
动作尺度 ±6 Nm
log_std_init = -2.0
8个并行环境
1M transitions
Reward：同状态零助力对照；离线 rollout 仅用于跟踪与验收
```

## 1. 数据流

```text
命令行参数
    -> 8个 KinesisExoEnv worker
    -> 144维传感器历史 + 冻结 TCN 的16维预测
    -> PPO Actor 输出4维归一化动作
    -> 乘以6 Nm动作尺度
    -> 力矩限速、URDF与肌肉负载分担
    -> 同状态零助力肌肉解与实际肌肉解配对
    -> Reward、TensorBoard、checkpoint和验证结果
```

## 2. Reward 数据流

训练的主要目标是目标肌群激活平方的相对下降：

$$
s_a = \frac{A_0(s_t)-A(s_t,\tau_t)}
{\max(A_0(s_t),\epsilon)}.
$$

其中 $A_0(s_t)$ 是同一物理状态 $s_t$ 下的零助力肌肉解，
$A(s_t,\tau_t)$ 是外骨骼施加力矩后的肌肉解。两者共享状态，因此动作造成的局部
卸载不会被步态相位漂移混淆。Reward 使用最近15步，即0.3秒的滑动均值。

肌肉绝对力矩负担只作单边约束，不再和激活省力重复计奖。令 $s_\tau$ 为同状态
肌肉负载省力率，则：

$$
c_\tau = \min\left[
\left(\frac{\max(-s_\tau-0.01,0)}{0.05}\right)^2,
4
\right].
$$

这表示1%以内视为求解噪声；超过后才二次惩罚。安全 gate 同时乘到正、负激活
省力上，避免噪声经过非对称 gate 后产生系统性负偏差。`balance_gate` 也使用
同状态肌肉力矩加实测外骨骼交互力矩计算；旧 shadow 残差只保留为
`control/legacy_shadow_balance_residual_ratio` 诊断项。

磁盘中的零助力 rollout 仍有三个用途：跟踪阈值、TensorBoard 漂移诊断和最终
checkpoint 配对评估。它不参与逐步 effort reward，因为助力会改变步态相位，按
墙钟时间取样会把相位差误判成省力或增力。

## 3. 每个终端先执行

```bash
cd ~/HK_hackthon/G-Exo

export KINESIS_PY=/mnt/kinesis-fast/kinesis/envs/kinesis/bin/python
export PYTHONPATH="$PWD:$PWD/../third_party/Kinesis"
export MPLCONFIGDIR=/tmp/gexo-matplotlib
mkdir -p "$MPLCONFIGDIR"
```

直接调用外置 Kinesis 环境中的 Python，不依赖 Conda 能否发现该环境。

## 4. 当前版本的正式训练命令

如果旧训练仍在当前终端运行，先按 `Ctrl+C` 停止。然后执行：

```bash
RUN="$PWD/RL/outputs/kinesis_exo_tcn160_scale6_std2_seed42_$(date +%Y%m%d_%H%M%S)"
LATEST="$PWD/RL/outputs/latest_kinesis_exo"
ln -sfn "$RUN" "$LATEST"
echo "output: $RUN"

"$KINESIS_PY" -m RL.runners.train_kinesis_exo \
  --output "$RUN" \
  --total-timesteps 1000000 \
  --num-envs 8 \
  --action-scale-nm 6.0 \
  --use-tcn \
  --tcn-device cpu \
  --device cpu \
  --seed 42
```

时间戳确保每次启动都生成新目录，`latest_kinesis_exo` 始终指向最近启动的正式
训练。不要手工填写时间戳，也不要把不同训练写进同一目录。按当前约 175 FPS
估算，1M transitions 需要约 1.6 小时，外加验证时间。

## 5. 为什么使用这些参数

当前 `log_std_init=-2.0`，归一化动作标准差为：

$$
\sigma_a=e^{-2}\approx0.1353.
$$

动作尺度为 6 Nm，因此初始力矩探索标准差为：

$$
\sigma_\tau=6e^{-2}\approx0.812\ \mathrm{Nm}.
$$

它低于上一轮 `scale=4, log_std=-1` 的约 1.47 Nm，保留了明显探索，但减少了
随机力矩主导训练的风险。`--device cpu` 是因为 SB3 的小型 MLP PPO 通常由环境
仿真而非网络计算限制速度；8个 worker 也不应各自在 GPU 上复制一份 TCN。

## 6. 先跑冒烟测试

修改环境、Observation、Reward 或 TCN 后，先执行两次 PPO 更新：

```bash
RUN="RL/outputs/smoke_tcn160_scale6_std2_$(date +%Y%m%d_%H%M%S)"

"$KINESIS_PY" -m RL.runners.train_kinesis_exo \
  --output "$RUN" \
  --total-timesteps 8192 \
  --num-envs 8 \
  --action-scale-nm 6.0 \
  --use-tcn \
  --tcn-device cpu \
  --device cpu \
  --seed 42
```

冒烟测试只检查环境、并行采样和 PPO 更新能否完成，不用于判断策略效果。

## 7. TensorBoard

在新终端重复第3节环境准备，然后直接使用固定的 `latest_kinesis_exo` 软链接：

```bash
RUN="$PWD/RL/outputs/latest_kinesis_exo"

"$KINESIS_PY" -m tensorboard.main \
  --logdir "$RUN/tensorboard" \
  --host 127.0.0.1 \
  --port 6006
```

浏览器打开：

```text
http://127.0.0.1:6006
```

优先观察：

```text
rollout/ep_rew_mean
eval/mean_reward
effort/activation_saving_window
effort/muscle_torque_saving_window
offline/activation_saving
offline/muscle_torque_saving
cost/torque_deterioration
control/mean_abs_exo_torque
tracking/mpjpe_mm
physiology/activation_overload_topk
control/actual_balance_residual_ratio
control/rated_torque_exceed_ratio
train/std
train/approx_kl
train/clip_fraction
train/explained_variance
```

`effort/*` 是 PPO 实际使用的同状态指标；`offline/*` 只用于判断相位漂移和最终
物理效果。另有 `motion_002/*`、`motion_008/*` 等逐动作面板，必须检查是否出现
“少数动作改善、其他动作恶化”的平均数掩盖问题。

训练态指标包含探索噪声，不能代替 checkpoint 的确定性配对评估。

## 8. 当前实际 PPO 超参数

| 参数 | 生效值 |
|---|---:|
| learning rate | `1e-4` |
| rollout steps / env | `512` |
| 并行环境 | `8` |
| transitions / rollout | `4096` |
| batch size | `256` |
| optimization epochs | `5` |
| gamma | `0.99` |
| GAE lambda | `0.95` |
| clip range | `0.2` |
| entropy coefficient | `1e-3` |
| value coefficient | `0.5` |
| max gradient norm | `0.5` |
| Actor | `128, 64, ReLU` |
| Critic | `128, 64, ReLU` |
| log std init | `-2.0` |
| checkpoint interval | `500k` |
| evaluation interval | `250k` |
| evaluation episodes | `9` |

命令行可以设置输出目录、总步数、时间上限、环境数量、动作尺度、随机种子、TCN
和设备。学习率、网络结构、`log_std_init` 等仍由以下代码控制：

```text
RL/train.py
RL/runners/train_kinesis_exo.py
```

启动前可快速确认：

```bash
rg -n "log_std_init|learning_rate|n_steps|batch_size|n_epochs|gae_lambda|ent_coef" \
  RL/train.py RL/runners/train_kinesis_exo.py
```

## 9. 训练产物

```text
$RUN/config.json                 环境、数据和Reward配置
$RUN/tensorboard/                TensorBoard事件
$RUN/checkpoints/                固定间隔模型
$RUN/best_model/best_model.zip   内部验证奖励最佳模型
$RUN/evaluation/evaluations.npz  内部验证结果
$RUN/final_model.zip             正常完成后的最终模型
```

`best_model.zip` 只是内部 Reward 最优。项目最终模型必须通过物理省力配对评估。

## 10. 评估500k检查点

```bash
RUN="$PWD/RL/outputs/latest_kinesis_exo"

"$KINESIS_PY" -m RL.runners.evaluate_kinesis_exo \
  --model "$RUN/checkpoints/gexo_ppo_500000_steps.zip" \
  --motion-ids 64,82,99 \
  --modes baseline,policy \
  --episodes 3 \
  --device cpu \
  --output "$RUN/holdout_500k.json"
```

评估脚本会从同一训练目录的 `config.json` 自动恢复 160维 TCN环境和6 Nm动作
尺度。详细指标解释见 `RL/KINESIS_EXO_EVALUATION.md`。

## 11. 断点续训

断点续训也必须写入新目录，保留原始实验：

```bash
OLD=RL/outputs/原训练目录
RUN="RL/outputs/kinesis_exo_resume_$(date +%Y%m%d_%H%M%S)"

"$KINESIS_PY" -m RL.runners.train_kinesis_exo \
  --output "$RUN" \
  --resume "$OLD/checkpoints/gexo_ppo_500000_steps.zip" \
  --total-timesteps 500000 \
  --num-envs 8 \
  --action-scale-nm 6.0 \
  --use-tcn \
  --tcn-device cpu \
  --device cpu \
  --seed 42
```

这里的500k表示继续增加约500k transitions。断点续训保留模型已有的策略标准差，
不会重新应用 `log_std_init`。

## 12. 按墙钟时间训练

例如最多训练8小时，同时用一个很大的 transition 上限防止提前停止：

```bash
RUN="RL/outputs/kinesis_exo_8h_$(date +%Y%m%d_%H%M%S)"

"$KINESIS_PY" -m RL.runners.train_kinesis_exo \
  --output "$RUN" \
  --hours 8 \
  --total-timesteps 100000000 \
  --num-envs 8 \
  --action-scale-nm 6.0 \
  --use-tcn \
  --tcn-device cpu \
  --device cpu \
  --seed 42
```

## 13. 实验管理规则

1. 一次训练对应一个全新的 `$RUN` 目录。
2. 目录名必须写明 TCN、动作尺度、初始标准差和 seed。
3. 不要在旧目录中重新启动训练。
4. 不要用新的 `config.json` 评估旧模型。
5. 训练命令和代码提交状态应与报告一起保留。
6. 先做8192步冒烟，再启动正式训练。
7. 250k只做早期筛选，500k必须执行确定性物理评估。
8. 如果500k相对250k在激活、肌肉力矩和MPJPE上同时退化，应停止该轮。
