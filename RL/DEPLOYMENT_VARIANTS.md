# G-Exo 部署包沿革与区别

项目在赶工期间同时维护了训练侧和控制侧两条部署路线。它们共享模型接口和
部分 ONNX 文件，但职责、目录布局和校准配置并不完全相同。这里保留两条路线，
便于理解开发过程和选择运行入口。

## `RL/deploy`

这是训练侧的独立 RL 部署包，采用 `src/` 与 `include/` 分离布局。它主要用于：

- 加载 TCN 与 Actor ONNX；
- 检查模型配置、哈希和输入输出契约；
- 执行 50 Hz 推理和 150 帧预热；
- 通过 C++ runtime test 和 reference replay 做离线验证。

它不直接读取 IMU，不访问 CAN，也不负责电机使能、限矩和外部控制状态机。

## `control/deploy`

这是控制集成侧的部署包，面向 `control/main.cpp` 和后续实机控制流程。其核心
`gexo_deploy` 源码、模型和回放文件与 `RL/deploy` 当前一致，但目录布局不同，
并额外提供：

- `policy_runtime.*`，用于控制侧统一选择策略；
- 与 MotorBridge、ROS2 Main 的集成边界；
- 嵌套的 `control/deploy/tcn_pd` 保险策略目录。

因此建议把 `control/deploy` 视为控制集成主线，把 `RL/deploy` 视为训练侧独立
部署和兼容参考。两者不能在不修改 CMake、测试路径和调用代码的情况下简单删除
其中一个。

## `RL/deploy_tcn_pd`

这是较早形成的独立 TCN+PD 部署版本。它只使用 TCN 预测结果和 PD 控制器，
不包含 RL Actor。该版本使用带 `preroll150` 的 TCN 校准配置，适合单独检查：

- TCN 因果历史；
- 预测增量到关节目标的转换；
- PD 力矩计算；
- WARMUP、READY、FAULT 生命周期。

## `control/deploy/tcn_pd`

这是控制侧的 TCN+PD 适配版本，作为控制流程中的可手动选择保险策略。它使用
另一套动态外骨骼校准文件，因而特征均值、标准差、电机偏置、目标缩放和动作符号
与 `RL/deploy_tcn_pd` 不完全相同。

两个 TCN+PD 版本还存在一个时序差异：一个版本使用 `valid_steps < warmup_steps`，
另一个使用 `valid_steps <= warmup_steps`，因此首个有效输出帧相差一帧。

## 模型文件为什么有多个副本

`actor.onnx` 和 `tcn.onnx` 在多个部署目录中可能具有相同 SHA-256。这些副本是
有意保留的自包含模型包，避免某个部署目录依赖另一个目录的相对路径。真正不同的
内容在于：

- C++ 调用入口；
- 模型配置中的校准和来源信息；
- TCN+PD 的动作符号与 warmup 时序；
- 控制侧的安全和集成边界。

因此，模型文件相同不等于部署包相同。替换模型时，应只替换目标部署包的完整
`models/` 和对应 reference replay，并重新运行该包的测试。

## 路径和可移植性

部署 CMake 不再使用作者机器的固定 路径。构建者必须通过
`ONNXRUNTIME_ROOT` 环境变量或 `-DONNXRUNTIME_ROOT=...` 指定本机 SDK。

配置 JSON 中的 `source.path`、`checkpoint` 和 `phase_root` 是历史实验 provenance，
主要用于追溯，并不代表部署运行时必须访问这些路径。运行时加载的是各部署目录
下的 `models/actor.onnx`、`models/tcn.onnx` 以及同目录配置。

## 版本状态

这是一次赶工形成的工程快照。不同目录保留了开发阶段的路线差异，不能视为经过
完整产品化整理的唯一部署方案，也不能仅凭离线回放把它表述为已经完成 sim2real。
如果希望复刻并且部署，请务必自己搭建对应环境并使用个人电机配置，进行sim2sim测试后再尝试进行sim2real。
