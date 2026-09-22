# TCN 轨迹预测 + PD 阻抗仿真

## 1. 边界

本实验冻结所有已有环境、TCN、奖励、执行器和模型文件，只通过新增适配层接入：

```text
GexoMyoAssistEnv 的公开 observation160
                    ↓
TCNImpedanceController
                    ↓
四维归一化 action
                    ↓
GexoMyoAssistEnv.step(action)
```

新增代码：

```text
RL/controllers/tcn_impedance.py
RL/controllers/delayed_prediction_audit.py
RL/runners/evaluate_tcn_impedance.py
RL/tests/test_tcn_impedance.py
RL/tests/test_tcn_impedance_evaluator.py
```

当前仿真使用 MyoAssist 的四关节等效物理执行器，不加载完整外骨骼 URDF。它用于先判断控制方向、稳定性和肌肉指标；URDF 质量、惯量及绑缚结构属于下一阶段机械仿真。

## 2. 控制公式

公开观测最后 16 维为标准化后的 TCN 运动增量：

$$
z = \operatorname{clip}\left(\frac{\Delta-\mu}{\sigma},-c,c\right)
$$

在未达到裁剪边界时可以恢复：

$$
\Delta=z\sigma+\mu
$$

特征顺序为：

```text
delta_q(+5), delta_dq(+5), delta_q(+10), delta_dq(+10)
```

默认使用 $+5$ 步，也就是 50 Hz 下的 100 ms 预测，并只向前推进一个控制周期：

$$
\beta=\frac{1}{5}=0.2
$$

$$
q_{ref}=q_t+\beta\Delta q_{+5}
$$

$$
\dot q_{ref}=\dot q_t+\beta\Delta\dot q_{+5}
$$

$$
\tau=K_p(q_{ref}-q_t)+K_d(\dot q_{ref}-\dot q_t)
$$

请求力矩除以 `action_scale_nm` 后变成 `[-1, 1]` 动作。原环境中的 `TorqueActuator` 继续负责变化率限制和硬限矩。

选中 horizon 或当前 32 维传感器帧的标准化绝对值低于裁剪范围的 60% 时，控制置信度为 1；从 60% 到 100% 线性降到 0。这样不会在裁剪边界制造力矩跳变。默认还把进入 PD 的位置误差限制为 $\pm1$ rad、速度误差限制为 $\pm10$ rad/s。

公开的 160 维观测已经裁剪过 TCN 特征。未触边时可准确逆标准化；触边后原始幅值已经丢失，因此该预测在延迟 RMSE 中记为 `NaN`，并由 `feature_saturation_ratio` 单独计数。不能把裁剪边界值当成原始 TCN 预测来粉饰误差。

## 3. 环境

在项目根目录执行：

```bash
conda activate hackthon
cd ~/HK_hackthon/G-Exo

export PYTHONPATH="$PWD:$PWD/../third_party/myoassist"
export MPLCONFIGDIR=/tmp/gexo-matplotlib
export PYTHONDONTWRITEBYTECODE=1
```

验证控制器单元测试：

```bash
python -m unittest RL.tests.test_tcn_impedance -v
```

## 4. 冒烟测试

先用低力矩、单速度和单 seed 验证完整链路：

```bash
python -m RL.runners.evaluate_tcn_impedance \
  --speeds 0.8 \
  --seeds 0 \
  --steps 100 \
  --kp 4.0 \
  --kd 0.2 \
  --horizon-steps 5 \
  --action-scale-nm 2.0 \
  --ood-soft-ratio 0.6 \
  --prediction-position-delta-limit-rad 1.0 \
  --prediction-velocity-delta-limit-rad-s 10.0 \
  --device cpu \
  --output RL/outputs/tcn_impedance/smoke.json \
  --require-pass
```

`--require-pass` 只要求两组走满、速度和姿态安全，不要求第一次参数就实现生理指标改善。

## 5. 正式配对

先对三个已标定速度做零助力/TCN-PD严格配对：

```bash
python -m RL.runners.evaluate_tcn_impedance \
  --speeds 0.8,1.0,1.25 \
  --seeds 0 \
  --steps 500 \
  --kp 4.0 \
  --kd 0.2 \
  --horizon-steps 5 \
  --action-scale-nm 2.0 \
  --device cpu \
  --output RL/outputs/tcn_impedance/screen_guard_kp4_kd02.json \
  --require-pass
```

当前默认要求激活或人体力矩至少改善 1%，同时另一项不得恶化，才将一个配对标记为有效。只有在已经确认参数应满足该标准时，才添加 `--require-effective`。否则它会因为效果不达标返回退出码 2，这不是程序崩溃。

当前仿真关闭了域随机化、传感器噪声，并固定参考起点；因此不同 seed 会产生完全相同的轨迹，不属于独立样本。`--seeds 0,1,2` 只能用于检查确定性，不能当作三倍统计证据。报告中的 `independent_condition_count` 不会把这些重复 seed 计为独立条件。

`sensor_ood_ratio_max` 检查公开 160 维观测中最新一帧的 32 个传感器通道，不能替代完整 50 帧 TCN 内部标准化输入的分布审计。后者没有通过旧环境的公开观测接口暴露；在“旧文件零修改”约束下，本适配层不会假装已经获得该信息。

四个关节可以独立设置增益：

```bash
--kp 4.0,4.0,4.0,4.0 \
--kd 0.2,0.2,0.2,0.2
```

## 6. 渲染

必须在能访问桌面显示器的终端运行：

```bash
echo "$DISPLAY"

python -m RL.runners.evaluate_tcn_impedance \
  --speeds 0.8 \
  --seeds 0 \
  --steps 500 \
  --kp 4.0 \
  --kd 0.2 \
  --action-scale-nm 2.0 \
  --render \
  --output RL/outputs/tcn_impedance/render.json
```

评估先运行不渲染的 baseline，再渲染完全相同初态的 TCN-PD 回合。

## 7. 输出与判读

JSON 是汇总报告，同名 NPZ 保存逐步轨迹。核心指标：

```text
protocol_pass                         稳定性和运动协议是否通过
mean_activation_saving_fraction       肌肉激活平方积分下降比例
mean_human_torque_saving_fraction     人体关节力矩代价下降比例
mean_gross_load_saving_fraction       肌肉总负载下降比例
mean_closed_loop_tcn_q_rmse_rad       助力闭环中的TCN位置预测误差
mean_closed_loop_tcn_dq_rmse_rad_s    助力闭环中的TCN速度预测误差
feature_saturation_ratio              TCN特征越界比例
action_saturation_ratio               控制器动作饱和比例
error_limit_ratio                     预测误差触发物理上限的比例
feature_ood_ratio_max                 TCN特征所占标定裁剪范围的最大比例
sensor_ood_ratio_max                  公开32维传感器帧所占裁剪范围的最大比例
mean_absolute_exo_torque_nm           实际施加的平均绝对力矩
positive_exo_work_j                   外骨骼正功
negative_exo_work_j                   外骨骼负功
```

省力比例统一按配对积分计算：

$$
S=\frac{J_{baseline}-J_{tcn\_pd}}{J_{baseline}}
$$

$S>0$ 表示改善，$S<0$ 表示恶化。不能只看一项：至少同时检查激活、人体力矩、总负载、存活、速度、姿态、力矩和功率。

当前测试只回答“TCN轨迹预测驱动的低增益PD是否有效”。它没有使用TCN生物力矩头，也不能代替后续的力矩前馈实验和实机验证。

## 8. 当前验收结果

使用 `kp=4.0`、`kd=0.2`、100 ms horizon，在 0.8、1.0、1.25 m/s 各做一组 500 步严格配对，得到：

```text
protocol_pass                         True，3/3 稳定走满
effectiveness_pass                    False
mean_activation_saving_fraction       +0.142%
mean_human_torque_saving_fraction     -0.460%
mean_gross_load_saving_fraction       -0.002%
mean_closed_loop_tcn_q_rmse_rad        0.155 rad
mean_closed_loop_tcn_dq_rmse_rad_s     2.094 rad/s
```

报告位于 `RL/outputs/tcn_impedance/screen_guard_kp4_kd02.json`，逐步数据位于同名 `.npz`。三组均没有动作饱和，平均绝对助力力矩约为 0.22--0.27 Nm；这说明当前失败不是力矩限额卡死，而是“TCN 预测到 PD 助力”的映射尚未产生一致的生理减负。此结果只证明控制链路和稳定性协议可用，不证明控制方法有效。

下一项有判别力的实验是增加 `oracle_pd`：使用零助力配对轨迹的真实未来状态，但沿用完全相同的 PD 公式。若 oracle 有效而 TCN-PD 无效，应改预测器；若 oracle 也无效，应放弃当前 PD 映射，转向相位/生物力矩前馈或带小残差的策略，而不是继续盲调 `kp/kd`。
