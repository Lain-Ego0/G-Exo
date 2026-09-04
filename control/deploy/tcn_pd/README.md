# G-Exo TCN+PD Deploy

本目录是独立的纯 C++ ONNX Runtime TCN+PD 部署层。现有
`RL/deploy/` 的 TCN+Actor 版本保持不变；两个目录拥有不同命名空间、模型包和可执行
文件，可以分别演进。

这里只实现 Deploy 黑箱内部，不讨论控制有效性，也不包含 CAN、IMU 驱动、50 Hz
调度器、进程间通信或外部控制状态机。

## 1. 边界

Deploy 负责：

- 加载和校验一个 TCN ONNX 模型；
- 维护 50 帧 TCN 因果历史；
- 完成 TCN 输入标定、通道重排和归一化；
- 将 TCN 输出转换为选定 horizon 的关节位置/速度增量；
- 执行 OOD 置信度、预测误差限幅和 PD 计算；
- 输出目标力矩和归一化动作；
- 管理 `WARMUP / READY / FAULT / SHUTTING_DOWN` 内部状态；
- 对正常停止、信号停止和故障后的停止执行同一套幂等清理。

Deploy 不负责：

- 传感器采集、单位解码、时间同步或坐标系定义；
- CAN、RS02、电机使能或制动；
- 线程创建、周期调度、IPC 或外部状态机；
- 外部执行器的力矩变化率、滤波、硬限矩、限功率或急停；
- 在线调参、训练、评估、模型热切换或运行状态持久化。

## 2. 黑箱接口

公开头文件为 `include/gexo_tcn_pd_deploy.hpp`，命名空间为
`gexo::deploy_tcn_pd`：

```cpp
initialize(model_directory)
step(sensor32)
get_state()
get_error_code()
get_error_message()
valid_steps()
request_shutdown(reason)
```

每周期只输入：

```text
sensor32 = q4 + dq4 + gyro12 + specific_force12
```

关节顺序固定为：

```text
left_hip, left_knee, right_hip, right_knee
```

`step()` 返回：

```text
state
target_torque_nm[4]
action[4]
confidence
feature_ood_ratio
sensor_ood_ratio
feature_saturated
sensor_saturated
error_limited
action_saturated
error_code
```

`target_torque_nm` 是 PD 请求力矩，尚未经过外部执行器限制；`action` 为：

$$
a = \operatorname{clip}\left(\frac{\tau}{\tau_{scale}}, -1, 1\right)
$$

本地仿真应使用 `action`。后续硬件层若直接使用 `target_torque_nm`，仍需在 Deploy 外实现
电机级安全约束。`action_scale_nm` 冻结在模型配置中，不能让 Deploy 和外部执行器各自
维护一份不同的数值。

## 3. 内部数据流

```text
sensor32
   |
   +--> TCN 路径
   |      原始物理量
   |        -> 电机/IMU 标定
   |        -> IMU bank 排列转 interleaved 排列
   |        -> input mean/std
   |        -> 50 帧 [1, 32, 50]
   |        -> tcn.onnx [1, 2, 12]
   |        -> 输出反归一化和关节标定
   |        -> 与当前原始 q/dq 作差
   |        -> raw delta16
   |        -> feature normalize/clip
   |        -> decode clipped delta16
   |
   +--> PD/OOD 路径
          sensor32 / sensor_scale32
            -> clip [-5, 5]
            -> sensor OOD

selected delta(q,dq)
   -> physical delta limits
   -> reference(q,dq)
   -> feature/sensor confidence
   -> PD target_torque_nm
   -> action_scale_nm
   -> clip [-1, 1]
   -> action
```

两条传感器路径不能合并：TCN 使用训练时输入统计，PD 的 sensor OOD 使用 Actor
观测尺度。TCN 增量必须先执行 feature 裁剪，再反解给 PD；不能绕过裁剪直接使用未裁剪
的原始预测。

TCN 模型接口固定为：

```text
input:  sensor_history float32 [1, 32, 50]
output: prediction     float32 [1, 2, 12]
```

两个 horizon 为未来 5 和 10 个控制步，每个输出块顺序为：

```text
q4, dq4, biological_moment4
```

当前控制配置选用 `+5` 步。生物力矩预测头不参与本控制器输出。

## 4. 控制公式

TCN 特征先按训练统计归一化和裁剪：

$$
z = \operatorname{clip}\left(\frac{\Delta-\mu}{\sigma}, -c, c\right)
$$

PD 使用裁剪后可恢复的增量：

$$
\hat{\Delta}=z\sigma+\mu
$$

默认使用 5 步 horizon，并只向前推进一个控制周期：

$$
\beta=\frac{1}{5}=0.2
$$

进入控制律前，位置增量限制为 $\pm1$ rad，速度增量限制为
$\pm10$ rad/s：

$$
q_{ref}=q_t+\beta\operatorname{clip}(\hat{\Delta q})
$$

$$
\dot q_{ref}=\dot q_t+\beta\operatorname{clip}(\hat{\Delta\dot q})
$$

$$
\tau=\gamma\left[K_p(q_{ref}-q_t)+K_d(\dot q_{ref}-\dot q_t)\right]
$$

默认参数为：

```text
Kp = [4, 4, 4, 4] Nm/rad
Kd = [0.2, 0.2, 0.2, 0.2] Nm*s/rad
action_scale_nm = [2, 2, 2, 2]
ood_soft_ratio = 0.6
```

选中 horizon 的 8 个 feature 和当前 32 个 sensor 分别计算 OOD ratio。ratio 不大于
0.6 时置信度为 1，在 0.6 到 1 之间线性下降，达到 1 时为 0，最终取两者较小值。
未选 horizon 不参与 feature OOD gate。

OOD 降额、预测误差限幅和 action 裁剪都是 `READY` 中的正常控制事件，只设置诊断
标志，不进入 `FAULT`。

## 5. 状态机与时序

> 最终收敛的三状态目标设计见 [STATE_MACHINE.md](STATE_MACHINE.md)。本节仍描述当前
> C++ 实现；在代码完成下一轮状态机重构前，两者需要明确区分。

```text
进程启动并 initialize 成功
             |
             v
          WARMUP
             |
             | 第 151 个有效 sensor 已写入历史并完成推理
             v
           READY
             |
             | 内部错误
             v
           FAULT

WARMUP / READY / FAULT
             |
             | request_shutdown 或进程停止信号
             v
       SHUTTING_DOWN
             |
             | 统一清理完成
             v
          进程结束
```

与本地 TCN+PD 仿真严格对齐的调用时序是：

```text
step 1..150: WARMUP，target_torque_nm/action 严格全零
step 151:    写入第 151 帧，转入 READY，返回第一条命令
step 152+:   READY，返回后续连续命令
```

这与同目录 RL+TCN 的时序一致：第 150 帧仍为零，第 151 帧才输出首动作。

以下情况锁存 `FAULT`，且输出严格全零：

- 模型包、SHA-256、tensor 名称、dtype 或 shape 不匹配；
- 配置 schema、协议、统计参数或控制参数不合法；
- 输入包含 NaN/Inf；
- 预处理、中间预测或输出产生 NaN/Inf；
- ORT 推理或内部历史一致性失败。

首版不提供 `reset()`。恢复方式是结束进程并创建新的 Runtime。所有方法由同一个 owner
线程调用；信号处理器只置停止标志，不能在异步 signal handler 或其他线程中直接释放
ORT Session。

`request_shutdown()` 可重复调用，并清空：

- TCN 历史和计数器；
- 输入、输出和控制结果缓冲；
- ORT tensor、MemoryInfo、Session 和 Env；
- 已加载配置。

## 6. 模型包

```text
models/
  model_config.json
  tcn.onnx
```

配置冻结模型接口和 SHA-256、训练统计、标定参数、sensor scale、PD 参数、OOD 参数、
50 Hz 和 150 帧预热协议。替换 TCN checkpoint 时必须重新生成整个模型包和参考回放：

```bash
cd /home/lenovo/HK_hackthon/G-Exo
PYTHONDONTWRITEBYTECODE=1 \
  /home/lenovo/UniLab/.venv/bin/python \
  control/deploy/tcn_pd/tools/export_model_package.py
```

导出器会校验 PyTorch/ONNX Runtime 数值、固定 ONNX 接口和模型哈希，并生成
`tests/reference_replay.json`。该回放用训练期 `FrozenTCNRuntime +
ActorObservationBuilder + TCNImpedanceController` 产生第 150、151 帧参考结果。

## 7. 构建与验证

本机已有 x86-64 ONNX Runtime 1.23.0：

```bash
cd /home/lenovo/HK_hackthon/G-Exo/control/deploy/tcn_pd
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
cmake --build build --parallel
ctest --test-dir build --output-on-failure
./build/gexo_tcn_pd_smoke_test
```

`gexo_tcn_pd_smoke_test` 使用当前 `models/tcn.onnx` 回放
`tests/reference_replay.json` 的 151 帧，而不是全零伪输入。它依次验证：

- 模型、配置与参考回放的 SHA-256 绑定；
- 第 1 到 150 帧保持 `WARMUP` 且输出严格为零；
- 第 151 帧进入 `READY` 并产生首条参考动作；
- 第 151 帧的 action、目标力矩、置信度、OOD 和诊断标志；
- 用 50 帧相同输入稳定历史后，检查后续输出保持有限、范围合法且数值稳定；
- 打印本机初始化时间、无周期等待的 `step()` 调用耗时分位数及超过 20 ms 的调用数；
- 退出前执行两次统一清理，检查幂等性、内部帧计数和停止后的全零输出。

默认额外运行 500 个稳态推理步。也可以显式传入模型目录、回放文件和步数：

```bash
./build/gexo_tcn_pd_smoke_test models tests/reference_replay.json 1000
```

CTest 为缩短回归时间只测 20 个重复输入步，直接运行则默认测 500 步。该耗时不包含
50 Hz 定时等待、线程唤醒和调度抖动，因此不能解释为实时 deadline；它只用于观测本机
Runtime `step()` 开销，也不作为跨平台硬阈值。数值、状态、哈希或有限值不满足契约时
程序返回非零。原有 `gexo_tcn_pd_deploy_process models --smoke-test` 仍保留为全零输入的
进程生命周期检查，不替代上述参考回放 smoke。

若 SDK 不在默认位置，显式指定：

```bash
cmake -S . -B build \
  -DONNXRUNTIME_ROOT=/path/to/onnxruntime-sdk \
  -DCMAKE_BUILD_TYPE=Release
```

进程入口目前只实现生命周期、信号停止和 `--smoke-test`。实际 sensor 输入来源属于后续
IPC/调度层，不在本目录伪造。

## 8. K3 目标机

当前本机 SDK 是 x86-64，不能直接复制到 K3 使用。交叉编译时需提供 K3/RISC-V 对应的
工具链文件和目标架构 ONNX Runtime SDK：

```bash
cmake -S . -B build-k3 \
  -DCMAKE_TOOLCHAIN_FILE=/path/to/k3-toolchain.cmake \
  -DONNXRUNTIME_ROOT=/path/to/k3-onnxruntime-sdk \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build-k3 --parallel
```

C++ 接口、模型包 schema 和内部状态机不需要因平台改变；平台相关内容只应进入工具链、
ORT 库路径及未来的外部进程层。

## 9. 目录结构

```text
tcn_pd/
  CMakeLists.txt
  README.md
  include/gexo_tcn_pd_deploy.hpp
  src/gexo_tcn_pd_deploy.cpp
  src/main.cpp
  src/sha256.cpp
  src/sha256.hpp
  models/model_config.json
  models/tcn.onnx
  tests/reference_replay.json
  tests/runtime_test.cpp
  tools/export_model_package.py
  tools/smoke_test.cpp
```
