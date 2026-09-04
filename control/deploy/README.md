# G-Exo Control Deploy 自包含模块

当前目录已经包含可构建的首版实现。随目录附带的 Actor 来自当前选定的 URDF dynamic
1 m/s PPO checkpoint；后续完善版保持相同接口时，只需重新生成 `models/` 模型包，无需
修改 Deploy 数据流或状态机。本目录只讨论部署框架，不对策略有效性作结论。

本目录是 Main 唯一需要调用的 Deploy 包。运行时使用到的全部自写 C++ 头文件、源文件、
模型包和测试都位于本目录内，不再引用其他目录中的自写 Deploy 文件。目录外依赖只有
系统/第三方的 C++ ONNX Runtime 和 JsonCpp。

## 1. 目标

本目录用于实现 G-Exo 的纯部署层。Deploy 作为一个独立黑箱，只负责：

- 使用 C++ ONNX Runtime 加载和运行 TCN 与 RL Actor；
- 维护 TCN 和 Actor 所需的历史缓冲；
- 将固定格式的输入转换为 Actor 的 160 维 Observation；
- 输出四维归一化 RL 动作；
- 管理自身内部状态机；
- 支持重复运行所需的 `reset()` 和程序退出时的 `close()`。

Deploy 不感知外部电机、CAN、IMU、控制状态机或进程间通信实现。

## 2. 固定边界

### 2.1 Deploy 负责

- TCN 和 Actor 的 `Ort::Session` 生命周期；
- 模型接口、配置和统计参数校验；
- 输入标定、通道转换和归一化；
- 50 帧 TCN 历史；
- 4 帧 Actor 历史；
- TCN 推理、`delta16` 构造和 Actor 推理；
- 输出有限值检查和 `[-1, 1]` 裁剪；
- `WARMUP / READY / FAULT` 内部状态；
- 内部故障锁存和统一清理。

### 2.2 Deploy 不负责

- CAN、RS02 或 IMU 驱动；
- 传感器读取、时间同步和数据传输；
- 50 Hz 调度器或实时线程创建；
- 进程间通信协议；
- 电机使能、停止和外部安全状态机；
- 动作到物理力矩的缩放；
- 力矩变化率、滤波、限矩或限功率；
- TCN+PD 控制；
- 训练、评估和在线模型更新；
- 模型热切换和运行状态持久化。

## 3. 黑箱接口

Deploy 每个推理周期接收：

```text
sensor32[32]
previous_applied_action[4]
```

Deploy 返回：

```text
state
action[4]
error_code
```

其中：

- `sensor32` 使用约定的关节顺序和物理单位；
- `previous_applied_action` 是外部上一周期实际采用的归一化动作；
- `action` 是四维归一化动作，范围为 `[-1, 1]`；
- 非 `READY` 状态下，`action` 必须严格为全零；
- Deploy 不输出物理力矩。

Deploy 的逻辑操作只有：

```text
initialize(model_directory)
step(sensor32, previous_applied_action)
state()
reset()
close()
```

Main 直接使用 `gexo::deploy::Runtime`，只需包含本目录的 `gexo_deploy.hpp` 并链接
CMake 目标 `gexo_deploy`。不再设置额外的控制层包装类或第二个静态库。

主工程的最小 CMake 调用为：

```cmake
add_subdirectory(control/deploy)
target_link_libraries(gexo_main PRIVATE gexo_deploy)
```

`reset()` 清除本轮历史但保留已加载模型和 ONNX Runtime Session，供同一进程重复启动
RL 控制；`close()` 最终释放全部部署资源，调用后只能销毁对象，不能重新初始化。
只读诊断计数 `inference_steps()` 用于验证当前运行实际进入了多少次 TCN+Actor 推理，
不参与控制输出。

## 4. 数据契约

### 4.1 关节顺序

```text
left_hip
left_knee
right_hip
right_knee
```

### 4.2 Sensor32

```text
q4
dq4
gyro12
specific_force12
```

总维度为 32。Deploy 接收的 `sensor32` 应已经完成物理量解码，并遵守固定的关节、
IMU 和坐标顺序。与训练统计相关的缩放、旋转、偏置和归一化由 Deploy 根据模型配置
执行。

### 4.3 TCN 输入输出

```text
tcn.onnx
  input:  float32 [1, 32, 50]
  output: float32 [1, 2, 12]
```

50 帧对应 1 秒的 50 Hz 因果历史。两个输出 horizon 分别对应未来 5 和 10 个控制步。
每个 horizon 的 12 维顺序为：

```text
q4, dq4, biological_moment4
```

Deploy 只使用 `q4` 和 `dq4` 构造：

```text
delta_q(+5)
delta_dq(+5)
delta_q(+10)
delta_dq(+10)
```

合计得到标准化后的 `delta16`。生物力矩头不直接参与动作输出。

### 4.4 Actor 输入输出

每个 Actor 历史帧为：

```text
sensor32 + previous_applied_action4 = frame36
```

最近 4 帧组成：

```text
4 * frame36 = history144
```

最终 Observation 为：

```text
history144 + delta16 = observation160
```

Actor ONNX 接口固定为：

```text
actor.onnx
  input:  float32 [1, 160]
  output: float32 [1, 4]
```

Actor 必须是确定性策略输出，不包含随机采样，也不需要导出 Critic 或 Value Head。

## 5. 内部数据流

```text
sensor32 + previous_applied_action4
              |
              +--> 更新 50 帧 TCN 历史
              |        |
              |        +--> TCN ONNX
              |              |
              |              +--> 反归一化与输出标定
              |              +--> delta16
              |
              +--> 更新 4 帧 Actor 历史
                       |
                       +--> history144 + delta16
                                  |
                                  +--> observation160
                                             |
                                             +--> Actor ONNX
                                                        |
                                                        +--> finite 检查
                                                        +--> clip [-1, 1]
                                                        +--> action4
```

Deploy 不把自己的上一帧预测动作写入下一帧历史。进入 `READY` 后，历史中的动作只
能来自调用方传入的 `previous_applied_action`，以保持“实际采用动作”的语义。

## 6. 模块与状态机生命周期

Deploy 是由 Main 持有的普通 C++ 模块，不要求独立进程。初始化成功后进入 `WARMUP`；
正常结束一轮控制通过 `reset()` 回到全新的 `WARMUP`，无需重新加载模型。

```text
对象未初始化
    |
    | initialize成功
    v
 WARMUP
    |
    | 前150次step只积累历史
    | 第151次step首次推理成功
    v
  READY
    |   |
    |   | reset
    |   +--------------------> WARMUP
    |
    | 内部错误
    v
  FAULT

WARMUP / READY / FAULT
    |
    | close
    v
对象关闭，资源已释放
```

模型或配置初始化失败时，Deploy 记录初始化错误并进入锁存 `FAULT`。`reset()` 不从
`FAULT` 恢复；调用方应零输出、记录根因并退出，下一次运行创建新的 Deploy 对象。

## 7. 状态定义

### 7.1 WARMUP

`WARMUP` 用于建立与训练一致的因果历史。固定的
`gexo_zero_assist_preroll150_v1` 协议要求 `warmup_steps` 必须等于 150。

每个有效输入执行：

1. 检查 `sensor32` 和 `previous_applied_action` 是否全部为有限值；
2. 更新 50 帧 TCN 环形缓冲；
3. 更新 4 帧 Actor 环形缓冲；
4. Actor 历史中的动作通道固定写入全零；
5. 前 150 帧不调用 TCN 或 Actor 的 `Session::Run()`；
6. 前 150 帧始终保持 `WARMUP` 并返回严格全零动作；
7. 第 151 帧写入调用方传入的 `previous_applied_action`，首次运行 TCN 和 Actor；
8. 第 151 帧推理成功后转入 `READY` 并返回第一个有效 RL 动作。

`WARMUP` 中的输入或预处理错误进入 `FAULT`。由于前 150 帧不推理，该阶段不会产生
ONNX Runtime 执行错误。

### 7.2 READY

`READY` 中每次 `step()` 按以下顺序运行：

1. 校验输入；
2. 更新 TCN 历史；
3. 使用本次传入的 `previous_applied_action` 更新 Actor 历史；
4. 运行 TCN；
5. 反归一化并构造 `delta16`；
6. 构造 `observation160`；
7. 运行确定性 Actor；
8. 校验所有中间结果和输出均为有限值；
9. 将 Actor 输出裁剪到 `[-1, 1]`；
10. 返回四维动作。

Deploy 只保证一次调用内部运算顺序正确，不负责保证调用间隔为 20 ms。

### 7.3 FAULT

以下情况进入 `FAULT`：

- 输入维度或模型接口不匹配；
- 输入包含 `NaN` 或 `Inf`；
- ONNX Runtime 执行失败；
- TCN 输出、`delta16`、Observation 或 Actor 输出包含非有限值；
- 历史缓冲状态不一致；
- 配置缺失或统计参数非法。

`FAULT` 是锁存状态：

- 不再更新任何历史；
- 不再执行 TCN 或 Actor；
- 每次调用都返回全零动作和固定错误码；
- `reset()` 返回 `false` 并保留原错误码和诊断文本；
- 通过结束程序并创建新对象恢复，不在同一对象内自动恢复。

## 8. reset 与 close

### 8.1 reset

`reset()` 用于正常结束一轮 RL 控制并准备下一轮。它清除 50 帧 TCN 历史、4 帧 Actor
历史、有效帧计数、中间张量内容和最近动作，然后回到 `WARMUP`。它保留模型配置、两个
`Ort::Session`、ORT 环境、张量绑定和预分配内存，所以不会在每轮启动时重新加载模型。

`reset()` 可以在 `WARMUP` 或 `READY` 重复调用且结果相同。未初始化、已关闭或锁存
`FAULT` 时返回 `false`。

### 8.2 close

`close()` 只用于整个程序退出。正常退出、系统停止、`SIGINT`、`SIGTERM` 和主循环主动
结束最终都由 Main 的所有者线程调用同一个 `close()`；信号处理器本身只设置退出标志。

信号处理逻辑只设置停止标志，不在信号处理上下文中调用 ONNX Runtime、释放资源或
执行复杂析构。

`Runtime` 的全部方法都由同一个所有者线程调用，不支持一个线程执行 `step()`、另一个
线程同时执行 `close()`。所有者线程只在当前一次 `step()` 返回后关闭，因此资源释放时
不存在仍在执行的 ORT 推理。`close()` 按以下顺序清理：

1. 禁止新的有效 `step()`；
2. 清零运行历史、计数、中间数组和最近动作；
3. 解绑输入输出 `Ort::Value`；
4. 释放 Actor 与 TCN 的 `Ort::Session`；
5. 释放 ONNX Runtime 环境和模型配置。

清理流程必须满足：

- 幂等，多次调用只执行一次有效清理；
- 支持只完成部分初始化的对象；
- 不产生新的推理；
- 不保存任何运行时历史；
- 关闭后的 `step()` 返回 `FAULT` 和严格全零动作；
- 关闭后的对象不能 `reset()` 或重新初始化。

`SIGKILL`、突然断电或内核直接终止进程无法执行用户态清理代码。这些不可捕获事件
不属于 Deploy 能够实现的统一清理范围，由操作系统回收进程资源。

## 9. 模型包

Deploy 从一个模型目录加载：

```text
models/
  tcn.onnx
  actor.onnx
  model_config.json
```

`model_config.json` 至少包含：

- Schema 版本；
- TCN 和 Actor 的输入输出名称、shape 和 dtype；
- TCN 输入、输出的 mean/std；
- 电机位置、速度和 IMU 坐标标定；
- `delta16` 的 mean/std/clip；
- 关节和特征顺序；
- `warmup_steps`，固定为 150；
- 模型文件哈希。

初始化在创建任何 `Ort::Session` 前重新计算两个 ONNX 文件的 SHA-256，并与配置比较。
模型文件与配置中声明的模型哈希不一致时会以 `MODEL_INTEGRITY` 拒绝启动。

完善版模型可以直接替换三个模型包文件，但必须继续遵守本文固定的输入输出契约。

## 10. C++ ONNX Runtime 约束

首版只使用原生 C++ ONNX Runtime API：

- 不依赖 Python；
- 使用两个静态 `Ort::Session`；
- Batch 固定为 1；
- 输入输出 shape 固定；
- 初始化时完成模型和接口检查；
- 运行时复用预分配缓冲；
- 单实例、单所有者线程调用，不提供并发 `step()` 或并发关闭；
- ONNX 异常在 Deploy 内部捕获，不跨黑箱边界抛出；
- 首版使用 `CPUExecutionProvider`，不在接口中暴露执行后端细节。

## 11. 实现目录

```text
deploy/
  .gitignore
  README.md
  CMakeLists.txt
  gexo_deploy.hpp
  gexo_deploy.cpp
  sha256.hpp
  sha256.cpp
  runtime_test.cpp
  reference_replay.json
  models/
    tcn.onnx
    actor.onnx
    model_config.json
```

外部状态机、传感器进程、进程间通信和电机控制仍在 Deploy 之外单独设计。

## 12. 首版验收条件

- 模型接口不匹配时拒绝进入 `WARMUP`；
- 启动后前 150 个有效输入始终输出全零；
- 第 151 个有效输入开始确定性输出 Actor 动作；
- 相同初始状态和输入序列得到逐元素一致的输出；
- `previous_applied_action` 的历史语义正确；
- 任意非有限输入或模型输出使状态锁存为 `FAULT`；
- `FAULT` 和关闭后的误调用始终输出全零；
- `reset()` 保留 Session，并使第二轮重新完成 150 帧预热；
- `FAULT` 拒绝 `reset()` 且保留根因；
- `close()` 可重复调用且不会重复释放资源。

## 13. 构建与验证

### 13.1 本机构建

本机已有的 ONNX Runtime C++ SDK 位于：

```text
/home/lenovo/third_party/onnxruntime-linux-x64-1.23.0
```

构建命令：

```bash
cd /home/lenovo/HK_hackthon/G-Exo/control/deploy
cmake -S . -B build -G Ninja \
  -DONNXRUNTIME_ROOT=/home/lenovo/third_party/onnxruntime-linux-x64-1.23.0 \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
ctest --test-dir build --output-on-failure
```

正式 Demo 不启动独立 Deploy 进程，Main 直接在同一进程调用 `Runtime::step()`。

### 13.2 C++ 调用关系

```cpp
#include "gexo_deploy.hpp"

gexo::deploy::Runtime deploy;
std::string error;
if (!deploy.initialize(model_directory, &error)) {
  // 初始化失败已经锁存为 FAULT；外层记录 error 后结束进程。
}

const auto result = deploy.step(sensor32, previous_applied_action4);
// 只有 result.state == State::kReady 时 action 才可能非零。

deploy.reset();  // 正常结束一轮，保留模型和Session。
deploy.close();  // 整个程序退出时最终释放资源。
```

`Runtime` 是单实例、单所有者线程黑箱。公开头文件通过 PImpl 隐藏 ONNX Runtime
类型；运行库还使用 JsonCpp 读取模型配置，但推理后端只有 C++ ONNX Runtime。

### 13.3 当前测试覆盖

- 模型包加载和静态 ONNX 名称、dtype、shape 检查；
- 前 150 帧保持 `WARMUP` 并严格零输出；
- 第 151 帧首次推理、`READY` 动作、范围和确定性；
- `NaN` 输入触发并锁存 `FAULT`；
- 有限大数在预处理中的溢出触发 `NON_FINITE`，不会被裁剪掩盖；
- 篡改模型触发 `MODEL_INTEGRITY`，错误 warmup 配置被拒绝；
- 正常 `reset()`、部分预热 `reset()`、重复 `reset()` 和第二轮确定性；
- `FAULT` 拒绝 reset 并保留根因；
- `close()` 终止使用、资源清理和重复关闭；
- 151 帧 Python 参考回放与 C++ 输出对齐。

参考回放前 150 帧故意传入非零 `previous_applied_action`。正确实现必须忽略这些值并在
Actor warmup 历史中写零；第 151 帧才采用调用方传入的上一周期实际动作。因此该回放
同时检查了历史动作语义，而不只是检查 ONNX 能否运行。

## 14. 替换完善版模型

离线训练和模型导出不属于控制模块的调用依赖。新模型导出完成后，只替换本目录中的：

```text
models/tcn.onnx
models/actor.onnx
models/model_config.json
```

若需要同步更新数值回放，再替换 `reference_replay.json` 并运行本目录 CTest。

Actor 结构或输入输出契约发生变化时，不应直接替换模型文件，而应先更新本文协议和
Deploy 版本。只有权重变化且接口保持不变时，才属于无代码模型替换。

## 15. K3 构建边界

本机 SDK 是 x86_64 ONNX Runtime 1.23.0，只能用于 PC 侧开发验证，不能复制到 K3
运行。K3 上应使用目标板匹配的 ONNX Runtime/SpacemiT SDK 和工具链，并在配置 CMake
时将 `ONNXRUNTIME_ROOT` 指向该 SDK。当前 CMake 不使用发行包内可能错误的 pkg-config
路径，而是直接从 `${ONNXRUNTIME_ROOT}/include` 与 `lib` 或 `lib64` 查找头文件和库。

首版明确使用 CPU Execution Provider。当前工作区没有 K3 SDK 或目标板环境，因此已
完成的是本机 C++ 构建和数值回放，尚未完成 K3 交叉编译、目标板算子兼容性和延迟验证。
