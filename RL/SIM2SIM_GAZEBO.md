# Gazebo机械Sim2Sim审计

## 作用与边界

该审计在Gazebo Classic 11的ODE物理引擎中加载真实G-Exo URDF，使用MyoAssist
零助力步态周期驱动四个髋膝关节，并冻结运行现有TCN和PPO Actor。

数据流固定为：

```text
Gazebo四关节和四连杆状态
  -> 32维统一传感器帧
  -> 50Hz因果TCN
  -> 144维历史 + 16维显式预测
  -> 冻结PPO Actor
  -> 8Nm限矩、20Nm/s限速
  -> Gazebo四关节外骨骼力矩
```

它验证跨物理引擎的力矩方向、策略稳定性和机械负载分担，不计算肌肉激活或代谢率，
也不等价于自由行走、落足和平衡测试。

## 指标

同一参考周期分别运行零助力`baseline`和冻结策略`policy`。等效人体驱动器为：

$$
\tau_{driver}=K_p(q_{ref}-q)+K_d(\dot q_{ref}-\dot q)
$$

驱动力矩平方卸载率为：

$$
S_\tau=1-\frac{\int \|\tau_{driver,policy}\|^2dt}
{\int \|\tau_{driver,baseline}\|^2dt}
$$

只有在轨迹RMSE未超过门槛时，正的$S_\tau$才算有效卸载。报告同时记录外骨骼
正负功、动作饱和率、逐关节RMSE和逐关节驱动力矩。

## 运行

```bash
source ~/anaconda3/etc/profile.d/conda.sh
conda activate hackthon
cd ~/HK_hackthon/G-Exo

python -m RL.runners.evaluate_gazebo_sim2sim \
  --steps 250 \
  --output RL/outputs/gazebo_sim2sim/full_250.json
```

查看渲染时增加`--render`：

```bash
python -m RL.runners.evaluate_gazebo_sim2sim \
  --steps 500 \
  --render \
  --output RL/outputs/gazebo_sim2sim/render_500.json
```

程序会自动启动并关闭独立ROS master、`gzserver`和可选的`gzclient`，不要求提前运行
ROS。JSON保存汇总结果，同名NPZ保存逐帧轨迹。

## 当前审计结论

固定1m/s策略在三组预先声明的人体等效阻抗下表现不同：

| 驱动增益 | 结果 | 驱动力矩平方变化 | 轨迹结果 |
|---|---|---:|---|
| Kp=15, Kd=1.5 | 失败 | -31.17% | 明显退化 |
| Kp=20, Kd=2.0 | 失败 | +28.72%卸载 | RMSE 0.1065 -> 0.1483 rad |
| Kp=25, Kd=2.5 | 通过 | +2.20%卸载 | RMSE 0.1159 -> 0.1165 rad |

因此当前策略能够跨引擎产生有限的机械卸载，但效果依赖人体等效阻抗，不能据此宣称
已经获得稳健Sim2Sim策略。中等增益下的较高“卸载”部分来自运动轨迹偏移，已被轨迹
门槛正确拒绝。
