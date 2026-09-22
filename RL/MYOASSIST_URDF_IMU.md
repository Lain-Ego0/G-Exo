# MyoAssist URDF 与 IMU 接入

## 当前实现边界

主训练采用 `urdf_dynamic`，同时保留 `urdf_rigid` 作为载荷对照：

- `base_link` 刚性固定到人体 `pelvis`；
- 外骨骼左右髋膝保留四个独立铰链；
- 四个电机只驱动外骨骼铰链，不直接作用于人体关节；
- 左右大腿和小腿支撑通过四个柔性 point cuff 向人体传力；
- URDF 的五组质量、质心和惯性参与 MuJoCo 动力学；
- URDF 网格参与渲染，但首版不参与碰撞；
- 动态模型为 `nq=57, nv=57, nu=26, na=22`，策略动作仍是四维。

`urdf_rigid` 不增加自由度，仍把五个 URDF link 固定到人体段，四个理想力矩源直接
作用于人体髋膝。它只能用于分离“附加质量影响”，不能作为最终助力训练结论。

当前 point cuff 表示有顺应性的衬垫传力，不等价于完整绑带接触、间隙和软组织模型。

## IMU 安装协议

四个 IMU site 固定在外骨骼 link 上，而不是固定在人腿 body 上：

| IMU | URDF link | link 局部位置 / m |
| --- | --- | --- |
| `left_thigh` | `l_thigh` | `(0.0100, 0.0000, -0.1000)` |
| `left_shank` | `l_calf` | `(-0.0600, -0.0600, -0.0800)` |
| `right_thigh` | `r_thigh` | `(0.0100, 0.0000, -0.1000)` |
| `right_shank` | `r_calf` | `(-0.0600, 0.0600, -0.0800)` |

大腿位置位于髋轴下方约 100 mm 的上段结构件，小腿位置位于膝下的上段支撑板。
左右小腿的 `Y` 坐标镜像。标定时先用关节轴中心确定纵向距离，再以结构件平面确定
横向位置；不要以软绑带或人体皮肤作为测量基准。实物孔位确定后，只修改
`RL/env/myoassist/urdf_attachment.py` 中的 `URDF_IMU_MOUNTS`，并重新生成模型、
baseline 与 TCN 标定。

传感器坐标轴始终与对应 URDF link 坐标轴对齐；`urdf_dynamic` 会自动计算它相对
MuJoCo 动力学 body 的四元数。中立位下四套坐标轴均满足：

- `+X`：人体前方；
- `+Y`：人体左方；
- `+Z`：人体上方。

MuJoCo `gyro` 输出局部角速度，单位为 `rad/s`；`accelerometer` 输出局部比力，单位
为 `m/s^2`。传感器名称和 32 维输入顺序未改变，所以共享 TCN 与 Actor 结构无需改
维度，但必须针对新模型重新标定。

## 数据流

```text
URDF link 位姿
  -> 四组 gyro + accelerometer
  -> MyoAssistSensorAdapter
  -> [4 q, 4 dq, 4x3 gyro, 4x3 specific force] = 32 维
  -> 50 Hz 因果 TCN
  -> 144 维历史 + 16 维预测 = 160 维 Actor 输入
  -> 4 维归一化动作
  -> 统一限矩/限速层
  -> 四个外骨骼铰链电机
  -> 大腿/小腿连杆与四个 cuff
  -> 人体动力学
```

## 生成与检查

```bash
cd ~/HK_hackthon/G-Exo
source ~/anaconda3/etc/profile.d/conda.sh
conda activate hackthon
export PYTHONPATH="$PWD"

python -m RL.env.myoassist.model_builder --variant urdf_dynamic
python -m unittest RL.env.myoassist.tests.test_model_builder
```

生成文件：

```text
RL/assets/myoassist/myoLeg22_2D_GEXO_URDF_DYNAMIC.xml
```

## 进入训练前的顺序

旧人体策略在新增 `3.098348 kg` URDF 后，动态版本的 `0.8 m/s` 零助力测试在第 109
步因骨盆高度过低终止。第 50、80、100 步的实际速度依次约为 `0.141`、`-0.307`、
`-1.072 m/s`，说明速度和姿态在预热期内已经发散。
这表明旧人体闭环与新载荷/约束失配，不是把预热从 150 步缩回 50 步就能解决。
当前证据也不能证明肌肉最大力本身不足；必须先适配人体策略，再检查激活饱和率。

1. 先续训 22 肌肉人体策略，使其适应 URDF 质量和惯性。
2. 用适配后的人体策略和 URDF 模型重新采集零助力 baseline。
3. 用相同人体检查点和模型重新标定 TCN。
4. 最后用 `--model-variant urdf_dynamic` 启动外骨骼 PPO。

三个训练产物必须同时满足相同的物理模型哈希和 `urdf_enabled=true`，否则环境会在
训练开始前拒绝运行。
