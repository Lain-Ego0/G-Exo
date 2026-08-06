# MyoAssist / G-Exo PPO 实施变更日志

状态：追加式工程账本，2026-08-03 建立。

本日志记录从 22 肌肉 MyoAssist 基座推进到正式四髋膝外骨骼 PPO 训练前的每一项
修改、独立 review 和测试证据。架构边界以
`RL/MYOASSIST_GEXO_BOUNDARY.md` 为准。

## 1. 日志规则

- 只追加新记录，不删除、改写或合并已经完成的历史记录；
- 每个记录只对应一个小变更单元；
- B-P0--B-P7 可连续开发，每个步骤都必须自检并追加证据，不等待逐步骤 reviewer；
- 历史 `PASS` / `REWORK` 记录保持原样，不据此覆盖或删除失败证据；
- 任何第三方修改、共享协议变化或用户选择都要单独记录；
- 命令必须记录工作目录、环境、退出码和关键结果；
- 生成文件、checkpoint 和数据报告必须记录路径及哈希；
- 最终整体 review 必须由此前未参与编辑的更新 agent 查看实际文件并独立运行测试。

## 2. 统一记录字段

后续每个变更使用以下模板：

```text
### [记录 ID] 标题

- 时间：
- 阶段：P0--P8
- 状态：PLANNED / EDITED / PASS / REWORK / BLOCKED
- 编辑 agent：
- 独立 review agent：
- 用户决定或授权：
- 目标：
- 非目标：
- 修改前数据流：
- 修改后数据流：
- 允许修改文件：
- 实际修改文件：
- 明确未修改文件：
- 修改前哈希：
- 修改后哈希：
- 兼容性影响：
- 自检命令与结果：
- reviewer 检查范围：
- reviewer 独立命令与结果：
- review 结论：
- 证据或报告路径：
- 已知限制：
- 回退方法：
- 下一步：
```

## 3. 2026-08-03 开工基线

### 3.1 工作区状态

根目录 `/home/lenovo/HK_hackthon` 的 Git 状态把以下目录整体显示为未跟踪：

```text
?? G-Exo/
?? third_party/
```

因此 Git 不能证明目录内部文件是否由用户修改。本路线从开工起将所有既有文件视为
用户所有；只有某一记录明确列出的文件才允许该步骤编辑。

任务外的 `.vscode/`、媒体、历史输出、移动硬盘数据及其他未跟踪内容全部不触碰。

### 3.2 关键只读基线哈希

以下 SHA-256 用于发现并行分支或用户在实施期间对共享文件的变化，不代表文件已被
Git 跟踪：

| 文件 | 2026-08-03 SHA-256 |
|---|---|
| `RL/data/dataset_manifest.py` | `ebc856f54212c86c4093e01c00a4a2435aa72997143c2d9713144ff1906e0945` |
| `RL/data/preprocess_tcn.py` | `54a081d116c39814a6650aaf349b91717379c43b999308f3015751fd5596333f` |
| `RL/data/tcn_dataset.py` | `949ef3d975a6cab50ba6b55d70ace0aa335b130d3f9d443436620c273365009f` |
| `RL/runners/predictors/tcn.py` | `0000700e7917a8e57c6dd7a850c7840c73aaa13d918b8121736aaf555d59f5df` |
| `RL/env/sensors.py` | `e61dda0554b8a73792efc50a3e27fcaf8adc73d67889375812e173caa57c1682` |
| `RL/env/torque.py` | `e4e02a9432818ab7192e85ca52ca10dc84c0d8ce1cb42ec5ffd00c347b61820a` |
| `RL/env/kinesis/physiology_metrics.py` | `da03a80b19b39e9f32aaea05e0e042c58e5901a898c77b0abe480c120d17c358` |
| `third_party/myoassist/rl_train/envs/myoassist_leg_base.py` | `8ad93991f21ab9835237a2ae7f64df8d596fdacf61a502b8e01294f9a7d6d844` |
| `third_party/myoassist/rl_train/envs/myoassist_leg_imitation.py` | `31f067bdf2662c653deb1486adf99351e23cb04760cb6b77e501effa3d426cce` |
| `third_party/myoassist/rl_train/envs/myoassist_leg_imitation_exo.py` | `f9923e2af5eb1a5f5de5c7f9eba8b9013ddc25bae0c5ec5931601e41e630bcce` |

若后续开始某一步前哈希发生变化，编辑 agent 必须重新阅读文件并在新记录说明来源，
不能把并行修改覆盖回本表版本。

### 3.3 当前事实

- 用户已运行 MyoAssist setup verification，13/13 项通过；
- MVP 选择 22 肌肉二维人体策略；
- MyoAssist speed-control 配置为 30 Hz 控制、1200 Hz 物理；
- 项目 TCN 和外骨骼部署协议固定为 50 Hz；
- 现有 MyoAssist speed-control 模型包含 22 肌肉和 2 个踝部外骨骼动作；
- `myoassist_leg_imitation_exo.py` 仍是空壳，不能作为四髋膝环境；
- `myoassist_leg_base.py` 的随机速度初始化位置参数顺序与函数签名不一致；
- 项目运行时 SensorReader 与 Phase 1/2 数据的 IMU 32 维排列不同；
- 当前没有 `RL/env/myoassist/` 的 G-Exo adapter；
- 当前阶段不接 URDF，不开域随机化。

## 4. 阶段状态

| 阶段 | 内容 | 状态 | 编辑者 | 独立 reviewer | 证据 |
|---|---|---|---|---|---|
| P0 | 边界文档与实施日志 | EDITED，待独立 review | `boundary_docs_editor` | 待分配 | 本文件与边界文档 |
| P1 | 中立协议、指标、兼容重新导出 | PLANNED | - | - | - |
| P2 | 22 肌肉 + 四理想髋膝执行器模型 | PLANNED | - | - | - |
| P3 | 冻结人体策略、重复 reset 与统一 50 Hz | PLANNED | - | - | - |
| P4 | MyoAssist 统一 32 维传感器 adapter | PLANNED | - | - | - |
| P5 | 50 Hz TCN 与 160 维 Observation | PLANNED | - | - | - |
| P6 | 肌肉 adapter、奖励与统一评估 | PLANNED | - | - | - |
| P7 | PPO 工厂、并行 smoke 和保存恢复 | PLANNED | - | - | - |
| P8 | 新 agent 整体 review 和训练前审计 | PLANNED | - | - | - |

## 5. 变更记录

### P0-001 建立 MyoAssist / G-Exo 分界与归档制度

- 时间：2026-08-03
- 阶段：P0
- 状态：EDITED，待独立 review
- 编辑 agent：`boundary_docs_editor`
- 独立 review agent：待父任务分配，必须不同于编辑 agent
- 用户决定或授权：直接修改；复用现有文件；仅四髋膝理想执行器；暂不上 URDF；
  暂不开域随机化；每步由不同 agent review，最终由更新 agent 整体 review
- 目标：冻结共享/后端边界、数据协议、脏工作区规则、分阶段验收和日志字段
- 非目标：不写运行代码，不改环境，不运行 PPO，不改变第三方文件
- 修改前数据流：规则散落在对话和多个历史文档中，没有 MyoAssist 专用强制边界
- 修改后数据流：由 `MYOASSIST_GEXO_BOUNDARY.md` 固定 32/144/16/160 维协议和
  MyoAssist/Kinesis/共享目录所有权
- 允许修改文件：仅新增本文件和 `RL/MYOASSIST_GEXO_BOUNDARY.md`
- 实际修改文件：
  - `RL/MYOASSIST_GEXO_BOUNDARY.md`
  - `RL/MYOASSIST_PPO_IMPLEMENTATION_LOG.md`
- 明确未修改文件：所有既有代码、配置、资产、checkpoint 和历史文档
- 修改前哈希：新文件，不适用
- 修改后哈希：边界文档
  `4602f311b96dc6e5ecd2eb11d07d3e602dce0110878e061714c5e879afea0b42`；
  本日志为追加式文件，其哈希会随 review 记录变化
- 兼容性影响：无运行时影响
- 自检命令与结果：
  - `wc -l -w`：边界文档 348 行，实施日志初稿 177 行；退出码 0
  - `rg` 检查固定协议、32 维冲突、第三方边界、P0--P8 和 review 规则：命中完整；
    退出码 0
  - `test -f` 检查文档引用的十个关键既有文件：全部存在；退出码 0
  - `git status --short -- <两个新文件>`：只显示两个新增未跟踪文档；未修改既有文件
- reviewer 检查范围：与当前代码事实的一致性、协议是否无歧义、文件边界是否能阻止
  两分支污染、阶段门是否覆盖正式训练前要求
- reviewer 独立命令与结果：待记录
- review 结论：待记录
- 证据或报告路径：本文件与 `RL/MYOASSIST_GEXO_BOUNDARY.md`
- 已知限制：Git 无法区分 `G-Exo/` 和 `third_party/` 内部历史脏改；通过只读默认和
  哈希基线缓解
- 回退方法：删除两个新增文档即可；不得因此修改其他文件
- 下一步：独立 agent review P0；只有 PASS 后开始 P1

## 6. 训练前整体审计占位

P8 reviewer 必须逐项给出证据，不能用“测试没有报错”代替覆盖说明：

| 验收项 | 权威证据 | 状态 |
|---|---|---|
| 共享与后端 import 边界 | import 审计和源码 review | PENDING |
| 32 维逐索引协议 | 单元测试和样本报告 | PENDING |
| 50 帧 TCN 因果性 | 因果遮挡/未来扰动测试 | PENDING |
| 144 + 16 = 160 Observation | shape、排列、metadata 测试 | PENDING |
| 四髋膝执行器顺序和符号 | 正负脉冲报告 | PENDING |
| 零助力严格为 0 Nm | actuator/physics 状态测试 | PENDING |
| 冻结 22 肌肉人体稳定性 | 多速度、多 seed 配对报告 | PENDING |
| 统一 50 Hz 与重复 reset 正确 | 时间戳、状态清理和连续 episode 测试 | PENDING |
| 生理指标物理含义 | 人工样例、零值和剂量响应 | PENDING |
| PPO 只更新四输出 Actor | 参数 hash 前后对比 | PENDING |
| 安全层位于动作与物理之间 | 边界、限速和滤波测试 | PENDING |
| 并行环境与保存恢复 | 8-worker smoke 和 reload 报告 | PENDING |
| baseline/teacher/Actor 可配对 | 同 seed 统一评估报告 | PENDING |
| 无 URDF、无域随机化 | 配置和模型审计 | PENDING |
| 每阶段独立 review 完整 | P0--P7 日志记录 | PENDING |

只有本表全部为 `PASS`，才能把“已到正式训练前”标记为完成。

## 6.1 共享监督流水线计划归档

### P0-003 建立共享监督助力与训练前正式计划

- 时间：2026-08-03
- 阶段：P0
- 状态：EDITED，待独立 review
- 编辑 agent：`plan_document_editor`
- 独立 review agent：待父任务分配，必须不同于编辑 agent
- 用户决定或授权：先把已确认思路写成随时可参考的正式计划；后续严格按共享、
  MyoAssist、Kinesis 和 `third_party` 边界推进；每个小步骤由不同 agent review，
  全部完成后由新的 agent 整体 review
- 目标：把固定轨迹教师优化、共享 TCN/AssistActor、MyoAssist 正式训练前流水线、
  文件所有权、数学目标、阶段门、review 制度和真实教师数据依赖合并为单一执行计划
- 非目标：不修改代码、第三方文件、现有业务逻辑、模型资产、checkpoint 或历史输出
- 修改前数据流：科学路线位于 `FIXED_TRAJECTORY_MULTITASK_PLAN.md`，隔离规则位于
  `MYOASSIST_GEXO_BOUNDARY.md`，尚无一份把两者映射到确切文件和统一阶段门的正式计划
- 修改后数据流：`SHARED_SUPERVISED_PIPELINE_PLAN.md` 明确离线教师、监督 Actor、
  MyoAssist 运行和 Kinesis 复核四条数据流及其汇合点
- 允许修改文件：
  - 新增 `RL/SHARED_SUPERVISED_PIPELINE_PLAN.md`
  - 向本追加式实施日志增加本记录
- 实际修改文件：
  - `RL/SHARED_SUPERVISED_PIPELINE_PLAN.md`
  - `RL/MYOASSIST_PPO_IMPLEMENTATION_LOG.md`
- 明确未修改文件：所有 Python、配置、资产、checkpoint、历史输出、
  `third_party/myoassist/**`、`RL/env/kinesis/**` 以及既有计划/边界文档
- 修改前哈希：
  - `RL/FIXED_TRAJECTORY_MULTITASK_PLAN.md`：
    `d769746f3e7feaaa299b47178c9938525dbf0a2437e308e7cb284e5643066ab4`
  - `RL/MYOASSIST_GEXO_BOUNDARY.md`：
    `4602f311b96dc6e5ecd2eb11d07d3e602dce0110878e061714c5e879afea0b42`
  - `RL/MYOASSIST_PPO_IMPLEMENTATION_LOG.md`：
    `c9357d37dd30fd5a11e28bfb962282e74d125ceb9a54de241b71b7ad2b3d1d08`
  - `third_party/myoassist/rl_train/envs/myoassist_leg_imitation.py`：
    `31f067bdf2662c653deb1486adf99351e23cb04760cb6b77e501effa3d426cce`
- 并发基线变化：本步骤自检期间，另一编辑 agent 按同一父任务更新了边界文档、
  新增 `RL/MYOASSIST_GEXO_PPO_PLAN.md` 并追加其 P0-002 记录。边界哈希从上述值变为
  `7be332f3ddf4001210355e470427e726dd6feab97617199728b2e38d707f691a`；新 PPO
  计划哈希为 `40620df8985fc01e43b3a4e2d8805f57386d4ea62cf26c6cb31ac0ab36be37de`。
  本步骤重新读取当前文件，并将统一50 Hz默认、重复reset阻塞和30/50 Hz回退同步
  到共享监督计划，没有覆盖该 agent 的内容
- 修改后哈希：
  - `RL/SHARED_SUPERVISED_PIPELINE_PLAN.md`：
    `b69c1e54d7b892b513e1322a4f39616f4d527712be2b22850835afebdd114019`
  - 本日志为追加式文件，其哈希会随 review 记录继续变化
- 兼容性影响：无运行时影响；新计划明确后续共享文件只能通过兼容测试最小修改
- 自检命令与结果：
  - `wc -l -w RL/SHARED_SUPERVISED_PIPELINE_PLAN.md`：667 行、1908 词；退出码 0
  - `sha256sum`：计划文档哈希与本记录一致；退出码 0
  - `rg` 检查目标/非目标、32/160维、文件边界、教师公式、P0--P8、review、归档、
    训练前清单和 `muscle_adapter` 阻塞：全部命中；退出码 0
  - `git status --short -- G-Exo/RL third_party/myoassist`：仍只显示两个顶层目录整体
    未跟踪，未提供内部 diff 能力；退出码 0
- reviewer 检查范围：计划与两个权威文档和当前源码是否一致；是否错误承诺已有文件；
  是否遗漏数据泄漏、30/50 Hz、32维顺序冲突、教师约束、第三方保护或最终 review 门
- reviewer 独立命令与结果：待记录
- review 结论：待记录
- 证据或报告路径：
  - `RL/SHARED_SUPERVISED_PIPELINE_PLAN.md`
  - 本记录
- 已知限制：真实教师数据仍依赖另一分支提供并通过 review 的
  `RL/env/myoassist/muscle_adapter.py`；固定轨迹求解器还需要用户决定是否允许
  CVXPY/凸求解器依赖，或接受经严格重放审计的 SciPy 分步近似；在这两个阻塞解决
  前只能完成共享层的合成测试
- 回退方法：删除新增计划并移除本条未 review 的日志记录；不得回退任何代码或
  并行分支变化
- 下一步：由未参与编辑的 agent 独立 review P0-003，并与另一 agent 的 P0-002
  联合检查文档一致性；PASS 后才开始 P1A

## 8. MyoAssist 四髋膝 PPO 计划归档

### P0-002-MYOASSIST-PPO 增加 PPO 执行计划并更新 50 Hz 决定

- 时间：2026-08-03
- 阶段：P0
- 状态：EDITED，待独立 review
- 编辑 agent：`boundary_docs_editor`
- 独立 review agent：待父任务分配，必须不同于编辑 agent
- 用户决定或授权：新增可持续执行 plan；按严格测试更新频率结论；只允许修改三个
  P0 文档，不修改代码
- 目标：记录 22 肌肉冻结人体、四髋膝理想力矩、32 -> TCN -> 160 -> 4 数据流、
  奖励、P0--P8、验收门、工时和失败回退；纠正多速率默认决定
- 非目标：不实现环境、模型、reset、TCN、reward 或 PPO；不修改第三方和既有代码
- 修改前数据流：边界文档误把 30 Hz 人体 / 50 Hz 外骨骼作为默认方案
- 修改后数据流：人体、外骨骼、传感器、TCN 默认统一 50 Hz；只有正确 reset 后
  回归失败才启用 30/50 Hz 多速率回退
- 允许修改文件：
  - `RL/MYOASSIST_GEXO_BOUNDARY.md`
  - `RL/MYOASSIST_GEXO_PPO_PLAN.md`
  - `RL/MYOASSIST_PPO_IMPLEMENTATION_LOG.md`
- 实际修改文件：同允许列表
- 明确未修改文件：所有代码、配置、第三方文件、资产、checkpoint 和历史输出
- 修改前哈希：
  - boundary：`4602f311b96dc6e5ecd2eb11d07d3e602dce0110878e061714c5e879afea0b42`
  - implementation log：`c9357d37dd30fd5a11e28bfb962282e74d125ceb9a54de241b71b7ad2b3d1d08`
  - plan：新增文件，不适用
- 修改后哈希：
  - boundary：`7be332f3ddf4001210355e470427e726dd6feab97617199728b2e38d707f691a`
  - plan：`40620df8985fc01e43b3a4e2d8805f57386d4ea62cf26c6cb31ac0ab36be37de`
  - implementation log：追加式文件，哈希会因本记录和 review 继续变化
- 兼容性影响：无运行时影响；P0-002 的频率决定覆盖 P0-001 中尚未验证的多速率默认
- 已纳入的严格测试证据：
  - 旧踝原始 `ctrlrange=[-1,0]`，归一化 `+1` 对应物理 `0 Nm`；
  - 50 Hz、0.8 m/s、零踝助力：3/3 episode 走满 1000 步；
  - 50 Hz、1.25 m/s、零踝助力：3/3 episode 走满 1000 步；
  - 当前未解决的是同一环境实例重复 reset 的确定性
- 自检命令与结果：
  - `wc -l -w`：boundary 354 行、plan 502 行、日志自检前 301 行；退出码 0
  - `rg` 检查 ctrlrange、统一 50 Hz、重复 reset、直接/抽取/新增、metadata、
    reward 公式、P0--P8、T0--T2、工时与回退：全部命中；退出码 0
  - 检查三份文档 Markdown fenced code block 数量为偶数：通过；退出码 0
  - `test -f` 检查九个直接复用的代码文件：全部存在；退出码 0
  - `git status --short -- <三个 P0 文件>`：只显示三个新增/更新文档；退出码 0
- reviewer 检查范围：三份文档频率结论一致；plan 覆盖范围、数据流、reward、文件
  顺序、验收、工时和回退；不存在代码修改
- reviewer 独立命令与结果：待记录
- review 结论：待记录
- 证据或报告路径：三份 P0 文档；原始严格测试报告路径由父任务 reviewer 补录
- 已知限制：严格测试只覆盖 0.8 和 1.25 m/s 的独立 episode，不能证明全部速度或
  重复 reset
- 归档编号说明：并行分支先追加了另一个 `P0-002`；本记录使用命名空间后缀，
  不改写或重排对方的追加记录
- 回退方法：仅回退本记录对应的三个文档 diff，不触碰其他文件
- 下一步：独立 agent 联合 review P0-001、P0-002-MYOASSIST-PPO 和并行 P0-003；
  `PASS` 后进入 P1

## 9. P0-003 返工记录

### P0-003-REWORK-FIX-001 明确 TCN delta、教师动作时序和 Observation 职责

- 时间：2026-08-03
- 阶段：P0
- 状态：REWORK-FIX 已编辑，待另一 agent re-review
- 编辑 agent：`plan_document_editor`，与 P0-003 原编辑者相同
- 原 review 结论：`REWORK`，由父任务转发；要求修正 TCN deployment feature、
  requested/applied 动作时序以及 `sensors.py`/`actor_observation.py` 职责重叠
- re-review agent：待父任务分配，必须未参与本次编辑
- 目标：只消除原 reviewer 指出的三项协议歧义，不扩大代码或第三方修改范围
- 非目标：不实现任何接口，不修改 Python、配置、资产、checkpoint、第三方代码或
  P0-003/P0-002 的历史记录
- 允许修改文件：
  - `RL/SHARED_SUPERVISED_PIPELINE_PLAN.md`
  - 向本追加式日志增加本返工记录
- 实际修改文件：同允许列表
- 明确未修改文件：
  - `RL/env/sensors.py`
  - `RL/env/kinesis/**`
  - `third_party/myoassist/**`
  - 所有其他代码、文档、配置、资产和输出
- 修改前哈希：
  - `RL/SHARED_SUPERVISED_PIPELINE_PLAN.md`：
    `b69c1e54d7b892b513e1322a4f39616f4d527712be2b22850835afebdd114019`
  - `RL/MYOASSIST_PPO_IMPLEMENTATION_LOG.md`：
    `c70f0ab1e9dcc2f433e0f00a22200b6492cf25556278b809a2d5764eb070ed17`
  - `RL/env/sensors.py`：
    `e61dda0554b8a73792efc50a3e27fcaf8adc73d67889375812e173caa57c1682`
  - `third_party/myoassist/rl_train/envs/myoassist_leg_imitation.py`：
    `31f067bdf2662c653deb1486adf99351e23cb04760cb6b77e501effa3d426cce`
- 修改后哈希：
  - `RL/SHARED_SUPERVISED_PIPELINE_PLAN.md`：
    `8bb2dd752c4ee20311005fbd65ee2354f42fc8ada134cc619f9f1c97ad56e3b4`
  - 本日志为追加式文件，哈希随本记录和 re-review 继续变化
- 返工内容：
  1. TCN deployment feature 固定为
     `[delta_q(+5), delta_dq(+5), delta_q(+10), delta_dq(+10)]`，delta 相对当前
     q/dq，并只使用 checkpoint/calibration 固定 mean/std/clip；
  2. 教师 NPZ 明确 requested torque、requested action、applied torque 和
     previous-applied action；第一帧 previous 为0，Observation 禁止当前动作，超出
     action scale 的标签由优化约束阻止或直接拒绝，禁止静默 clip；
  3. `SensorReader` 只拥有 runtime32 采集/检查/噪声/裁剪；
     `actor_observation.py` 唯一拥有36/144/160、缩放、TCN通道转换与delta16；P1A
     允许兼容新增 `read_runtime32()`，legacy `read()` 委托共享 builder，Kinesis
     修改前后必须逐元素完全相等。
- 兼容性影响：仅修正文档；未来 P1A 被明确允许最小兼容修改 `sensors.py`，但本步骤
  没有执行该修改
- 自检命令与结果：
  - `wc -l -w RL/SHARED_SUPERVISED_PIPELINE_PLAN.md`：773 行、2184 词；退出码0
  - Markdown fence markers 14、math markers 46，均为偶数；退出码0
  - `rg` 检查四段 delta 顺序、固定 mean/std/clip 和160维公式：全部命中；退出码0
  - `rg` 检查四个教师动作字段、首帧0、上一时刻、标签泄漏和禁止 clip：全部命中；
    退出码0
  - `rg` 检查 `read_runtime32`、legacy委托、唯一builder、P1A和Kinesis逐元素门：
    全部命中；退出码0
  - `sha256sum`：计划文档、`sensors.py` 和受保护第三方文件与本记录一致；退出码0
- reviewer 检查范围：
  - delta16 的顺序、当前状态差分和固定统计是否贯穿数据流、NPZ、metadata、阶段表
    和验收清单；
  - Observation 的每一帧是否只包含上一时刻 applied action，是否仍有当前标签泄漏；
  - requested torque/action 与 action scale 是否无歧义，是否明确拒绝超范围标签；
  - `SensorReader` 和 `actor_observation.py` 是否各有唯一职责，legacy Kinesis 门是否
    可执行；
  - 本次是否只修改两份允许的 Markdown。
- reviewer 独立命令与结果：待记录
- review 结论：待 re-review
- 证据路径：
  - `RL/SHARED_SUPERVISED_PIPELINE_PLAN.md`
  - 本记录
- 已知限制：本步骤仍是计划层，不证明未来实现符合协议；必须由 P1A/P1C/P1E 测试
  分别提供运行时证据
- 回退方法：只回退计划文档中本返工的三组文字并追加回退记录；不修改既有历史记录
- 下一步：父任务分配未参与本次编辑的 agent re-review；只有 `PASS` 后才能开始 P1A

## 10. P0-003 独立返工复审

### P0-003-REVIEW-002 协议、现有实现与跨文档一致性复审

- 时间：2026-08-03
- 阶段：P0
- 状态：REWORK
- 被审修改 agent：`plan_document_editor`
- 独立 review agent：`p0_boundary_reviewer`，未参与 P0-003 或
  P0-003-REWORK-FIX-001 的编辑
- review 权限：只读审查全部计划、边界和现有实现；仅允许向本日志追加本记录
- review 目标：验证原三项返工是否真正消除协议歧义，并额外检查 reset/warmup、
  动作力矩缩放、硬件硬限矩和监督损失是否已达到可直接实施的程度
- review 前哈希：
  - `RL/SHARED_SUPERVISED_PIPELINE_PLAN.md`：
    `8bb2dd752c4ee20311005fbd65ee2354f42fc8ada134cc619f9f1c97ad56e3b4`
  - `RL/MYOASSIST_GEXO_BOUNDARY.md`：
    `7be332f3ddf4001210355e470427e726dd6feab97617199728b2e38d707f691a`
  - `RL/FIXED_TRAJECTORY_MULTITASK_PLAN.md`：
    `d769746f3e7feaaa299b47178c9938525dbf0a2437e308e7cb284e5643066ab4`
  - `RL/MYOASSIST_GEXO_PPO_PLAN.md`：
    `40620df8985fc01e43b3a4e2d8805f57386d4ea62cf26c6cb31ac0ab36be37de`
  - `RL/MYOASSIST_PPO_IMPLEMENTATION_LOG.md`：
    `27f3fa95f20f484563017676b9888872ea5aced83ac8127a5d8be4e6bd39e07d`
  - `RL/env/sensors.py`：
    `e61dda0554b8a73792efc50a3e27fcaf8adc73d67889375812e173caa57c1682`
  - `RL/env/torque.py`：
    `e4e02a9432818ab7192e85ca52ca10dc84c0d8ce1cb42ec5ffd00c347b61820a`
  - `RL/env/kinesis/tcn_adapter.py`：
    `edb2da3577e841ce2efd1b1c893a7e47b28d0a4aa1b428d1688385d4a4d703a8`
  - `RL/env/kinesis/exo_env.py`：
    `3c374f6c4a08bfbd85a5b0c34c54f5a2fa14d7aba949e82e91d30df50fd69811`
- 受保护第三方证据：
  - `third_party/myoassist/**` 共 2425 个文件的有序逐文件 SHA-256 聚合哈希：
    `0c11c7c9a83b2e2169446a84cfe0d1e14b433db823c368a8c7a8151ee3e95f10`
  - `third_party/myoassist/rl_train/envs/myoassist_leg_imitation.py`：
    `31f067bdf2662c653deb1486adf99351e23cb04760cb6b77e501effa3d426cce`
- 原三项返工复审结果：
  1. `PASS`：TCN deployment feature 已在数据流、协议、NPZ、监督 Actor、阶段表和
     验收清单中统一为
     `[delta_q(+5), delta_dq(+5), delta_q(+10), delta_dq(+10)]`；delta 相对当前
     q/dq，并使用 checkpoint/calibration 的固定 mean/std/clip。该定义与现有
     `tcn_adapter.py::raw_deployment_features()` 和 `deployment_features()` 一致；
  2. `PASS`：requested torque、requested normalized action、applied torque 和
     previous-applied action 已分成四个字段；首帧 previous 为0，后续只读取
     $t-1$ 实际施加力矩，当前 requested/applied 不进入 Observation；
  3. `PASS`：`SensorReader` 与 `actor_observation.py` 的唯一职责已拆清；P1A 明确
     `read_runtime32()`、legacy `read()` 兼容委托以及 Kinesis 逐元素零误差门。
- 新发现，按严重性排序：
  1. `HIGH`，动作缩放与硬限矩仍不能按现有实现落地。计划同时定义逐关节
     `action_torque_scale_nm[4]` 和独立硬力矩上限，但没有明确逐项关系
     $0 < action\_torque\_scale_j \le torque\_limit_j$。更关键的是现有
     `TorqueActuator.process()` 固定执行
     `target_torque = normalized_action * torque_limit_nm`，没有独立 action scale。
     因而计划中的
     `torque_actuator(teacher_requested_action)` 在 scale 小于硬限矩时会施加错误力矩。
     返工必须明确兼容 API：`TorqueActuator` 新增可选逐关节
     `action_torque_scale_nm`，默认等于 `torque_limit_nm` 以保持旧调用逐元素等价；
     动作先乘 scale，变化率/滤波后再由 hard limit 最终裁剪。应把 `torque.py`、
     全部调用者审计和旧行为等价测试列为 P1A 的子步骤或独立的前置步骤；
  2. `HIGH`，reset/warmup 仍只有“必须唯一实现”的要求，没有选择具体算法。
     `observation[0]` 无法仅靠 `state[0:0]` 构造四帧/50帧历史。实现前必须固定：
     是填零、重复首帧，还是让冻结人体做真实零助力预滚动；预滚动是否计入 episode
     时间、reference index、reward 和教师标签；离线 trial 前49帧是拒绝还是填充。
     现有 Kinesis 在启用 TCN 时会把 warmup 至少提高到50步，真实执行零助力步进，
     用最后4个真实帧组成 Actor history；共享计划若采用该语义，应明确“reset 后
     先执行50个50 Hz零助力真实预滚动步，TCN取50帧、Actor取最后4帧、动作历史
     全为0，预滚动不作为训练标签/episode回报”，并要求离线数据只在同一 trial
     内历史和 `+10` horizon 都有效时生成样本，绝不跨 reset 填充；若不采用，必须
     明确另一唯一规则及 train/runtime 一致性测试；
  3. `MEDIUM`，监督损失公式仍写成
     $\|\hat\tau-\tau^*\|_1$，但已锁定的网络输出和 `label[t]` 都是归一化 action。
     必须改成归一化动作损失
     $\|\hat a-a^*\|_1+\lambda_s\|\Delta^2\hat a\|_2^2$，或明确将预测和标签同时
     乘逐关节 action scale 后在 Nm 中计算；不得混用 action 与 torque；
  4. `MEDIUM`，权威边界和并行 PPO 计划仍把16维直接描述为“未来 q/dq”，并把36维
     描述为“上一步归一化动作”，没有注明 deployment 输入是固定归一化 delta 和
     previous-applied action。网络原始输出可以是绝对 q/dq，但进入 Actor 前的转换
     必须一致。为防另一分支按旧语义实施，至少应在
     `MYOASSIST_GEXO_BOUNDARY.md` 和 `MYOASSIST_GEXO_PPO_PLAN.md` 加一条权威引用或
     同步这两个部署语义；不得形成两个都自称正式的160维协议。
- 已通过的其余边界：
  - 共享、MyoAssist、Kinesis 和 `third_party` 文件归属没有越界；
  - `actor_observation.py` 命名在当前共享计划内一致；
  - 二阶差分明确只沿同一 trial 的连续 sequence 计算，不跨 reset 或无效区间；
  - P1D 明确在开始前由用户选择 CVXPY/同等级凸求解器或接受 SciPy 分步近似，
    没有静默增加依赖；
  - Markdown 共有14个 fence marker、46个 `$$` marker，均成对；13个编号主节完整。
- reviewer 独立命令与结果：
  - `sha256sum <四份计划/边界/日志及四份现有实现>`：与上列哈希一致；退出码0；
  - `find third_party/myoassist -type f -print0 | sort -z | xargs -0 sha256sum |
    sha256sum`：得到上列受保护树哈希；退出码0；
  - `awk` 统计 Markdown fence/math marker：14/46，均为偶数；退出码0；
  - `rg` 审计 delta、固定统计、previous-applied、action scale、reset/warmup、二阶
    sequence、P1A、P1D 和目录边界：全部目标条目已人工逐行复核；退出码0；
  - `nl -ba` 对照 `sensors.py`、`torque.py`、`tcn_adapter.py`、`exo_env.py`：确认
    TCN delta 实现一致；确认现有 TorqueActuator 缺少独立 action scale；确认 Kinesis
    TCN reset 使用真实零助力 warmup；退出码0；
  - `git status --short -- G-Exo/RL third_party/myoassist`：根仓库仍只显示两个顶层
    目录整体未跟踪，不能提供细粒度 diff；退出码0。
- 独立测试说明：本步骤只修改 Markdown，未运行运行时单元测试；review 使用源码和
  协议一致性审计。P1A 仍必须提供冻结输入的运行时等价测试，不能用本审查代替。
- review 结论：`REWORK`。原三项返工均通过，但以上两个 HIGH 项会导致实现选择不同
  或施加错误物理力矩，P0-003 暂不能 PASS，P1A 暂不能开始。
- 实际修改文件：仅向 `RL/MYOASSIST_PPO_IMPLEMENTATION_LOG.md` 追加本记录；未修改
  计划、Python、配置、资产、checkpoint、历史输出或 `third_party/myoassist/**`
- 回退方法：不得改写历史 review；如本记录本身记载错误，只能追加勘误记录
- 下一步：由文档编辑 agent 同步修复上述四项并追加 REWORK-FIX-002；随后再由未参与
  该修复的 agent 独立复审。固定轨迹求解器依赖选择仍可等待用户决定，但不得阻塞
  文档层先把 action scale 和 warmup 语义写死。

## 11. P0 跨文档协议收口

### P0-003-REWORK-FIX-002 写死动作尺度、预滚动和监督损失

- 时间：2026-08-03
- 阶段：P0
- 状态：REWORK-FIX 已编辑，待不同 agent 独立复审
- 编辑 agent：`root`；未参与 `P0-003-REVIEW-002`
- 独立 review agent：待父任务分配，必须未参与本次编辑
- 用户授权：按共享、MyoAssist、Kinesis、第三方分界直接推进；所有修改追加归档，
  每个步骤由不同 agent review 和测试
- 目标：消除第二轮 reviewer 提出的四项剩余歧义，使三份权威文档能够直接指导
  P1A 实现
- 非目标：不修改任何 Python、第三方文件、模型、配置、checkpoint 或历史输出；
  不选择 P1D 的凸求解器依赖
- 允许修改文件：
  - `RL/MYOASSIST_GEXO_BOUNDARY.md`
  - `RL/MYOASSIST_GEXO_PPO_PLAN.md`
  - `RL/SHARED_SUPERVISED_PIPELINE_PLAN.md`
  - 向本追加式日志增加本记录
- 实际修改文件：同允许列表
- 修改前哈希：
  - boundary：`7be332f3ddf4001210355e470427e726dd6feab97617199728b2e38d707f691a`
  - MyoAssist PPO plan：`40620df8985fc01e43b3a4e2d8805f57386d4ea62cf26c6cb31ac0ab36be37de`
  - shared plan：`8bb2dd752c4ee20311005fbd65ee2354f42fc8ada134cc619f9f1c97ad56e3b4`
  - implementation log：`ae4eca1280684a666b7fb271edfb822c8d55701a8120536ac487a5daaf7ccd64`
- 修改后哈希：
  - boundary：`9442b4c3929ab2a93b320a4b59c077e54611309caf7c05e3913edc13bbc38653`
  - MyoAssist PPO plan：`f0343e93fe3d8ab36e8804f1bba318797cfc9056121c257d445a3f8529c269a4`
  - shared plan：`9ce4c34dda85f202164256d4ba634474d74218726d1975872b61b0706a77a8a3`
  - 本日志为追加式文件，哈希随本记录和后续review继续变化
- 协议收口：
  1. 三份文档统一 delta16 顺序、固定mean/std/clip和previous-applied action语义；
  2. 逐关节固定 $0 < action\_torque\_scale\_nm \le torque\_limit\_nm$；规划
     `TorqueActuator` 可选scale，默认等于hard limit以保持旧行为；
  3. reset固定为 `gexo_zero_assist_preroll50_v1`：真实零助力预滚动50步，TCN取
     50帧、Actor取最后4帧，动作历史为0，预滚动不计episode/reward/标签；
  4. 离线trial首尾无效样本拒绝，不跨trial/reset填充；
  5. 监督损失统一在归一化action空间计算，物理评估才乘scale报告Nm。
- 数据流变化：从存在四种可选解释的160维/动作协议，收口为唯一可测试路径：
  `runtime32 -> preroll50/history -> normalized delta16 -> observation160 -> normalized
  action -> action scale -> rate/filter -> hard limit -> applied torque`
- 明确未修改且哈希保持：
  - `RL/env/torque.py`：
    `e4e02a9432818ab7192e85ca52ca10dc84c0d8ce1cb42ec5ffd00c347b61820a`
  - `RL/env/sensors.py`：
    `e61dda0554b8a73792efc50a3e27fcaf8adc73d67889375812e173caa57c1682`
  - `third_party/myoassist/rl_train/envs/myoassist_leg_imitation.py`：
    `31f067bdf2662c653deb1486adf99351e23cb04760cb6b77e501effa3d426cce`
  - `third_party/myoassist/**` 2425文件有序聚合哈希：
    `0c11c7c9a83b2e2169446a84cfe0d1e14b433db823c368a8c7a8151ee3e95f10`
- 自检命令与结果：
  - `awk` 分别检查三份Markdown fence/math marker：`6/2`、`6/34`、`14/48`，
    全部成对；退出码0
  - 对三份文档分别 `rg` 检查delta16完整顺序、action scale、preroll50：全部PASS；
    退出码0
  - `rg` 反向检查旧的绝对deployment/模糊上一动作/torque-loss文本：无命中；退出码0
  - `sha256sum` 检查三份文档和受保护代码/第三方关键文件：与本记录一致；退出码0
  - 首次从 `G-Exo` 工作目录检查第三方关键文件时误用相对路径
    `third_party/...`，命令退出码1；改为父目录执行后哈希正确。该命令未写文件
- 兼容性影响：当前只修改文档；P1A获得修改 `sensors.py`、`torque.py` 的明确许可，
  但必须以默认参数旧输出逐元素相等作为进入下一步的门
- 回退方法：不得改写本记录；若协议被否决，仅回退本步骤三份文档diff并追加勘误
- 下一步：由未参与本次编辑的 agent 独立复审三份当前文档和现有代码；只有PASS后
  才开始P1A

## 12. P0 跨路线职责与科学指标返工

### P0-004-REWORK-FIX-001 权威层级、阶段命名与 reward/teacher 对齐

- 时间：2026-08-03
- 阶段：P0
- 状态：REWORK-FIX 已编辑，待不同 agent 独立复审
- 编辑 agent：`root`
- 目标：消除并行路线的阶段编号冲突、第三方 Kinesis 边界遗漏、`RL/train.py`
  复用能力误述、50 Hz 证据过度结论，以及监督教师与 PPO 生理指标分叉
- 非目标：不修改 Python、第三方文件、模型、配置、checkpoint 或历史输出；不启动
  PPO；不选择固定轨迹求解器依赖
- 允许并实际修改：
  - `RL/MYOASSIST_GEXO_BOUNDARY.md`
  - `RL/MYOASSIST_GEXO_PPO_PLAN.md`
  - `RL/SHARED_SUPERVISED_PIPELINE_PLAN.md`
  - 向本日志追加本记录
- 本轮编辑起点：在 `P0-003-REWORK-FIX-002` 当前文档基础上继续；本轮开始时三份
  文档分别处于 boundary `bdaa9976...`、PPO plan `f0343e93...`、shared plan
  `bb3fc6b6...` 的并行更新状态。完整前序哈希链见上一记录，未覆盖任何历史内容
- 修改后哈希：
  - boundary：`9442b4c3929ab2a93b320a4b59c077e54611309caf7c05e3913edc13bbc38653`
  - MyoAssist PPO plan：`1aba109310df41a5d9ceb314faad695c353d66efea3e0d7c37cdf8dddc57bac7`
  - shared plan：`760fe028f9fab0baeb7b8b10981ec11cffb2822cb4aa8bfb70b1de1a570dfbde`
  - 本日志为追加式文件，哈希随本记录和后续 review 变化
- 修改内容：
  1. 权威层级固定为 boundary > 路线局部计划；路线 A 使用 `S-P*`，路线 B 使用
     `B-P*`，相同数字不再被误解为同一阶段；
  2. `third_party/myoassist/**` 与 `third_party/Kinesis/**` 均明确只读；
  3. 明确 `RL/train.py` 可复用 PPO/并行/checkpoint/TB/resume，但当前没有监督
     AssistActor 注入钩子；`resume_from` 不得冒充监督初始化；
  4. 50 Hz 保留为默认候选，但交互式 6 个 episode 结果在 runner、报告、配置哈希
     和 repeated-reset 证据完成前不算正式通过；
  5. fresh PPO 只可用于路线 B 工程 smoke；路线 A 正式训练仍要求监督初始化或有界
     residual，两类结论不得混用；
  6. 禁止按未锁定的 reference index 逐帧减 baseline。在线 reward 只用训练速度条件
     的零助力统计做固定中心化/尺度化；省力百分比只由同 seed、速度和初态的整段
     配对 rollout 计算；
  7. 两条路线统一指标职责：激活平方是主要生理代价，人体净关节力矩是主要机械
     卸载量，非抵消 gross 负载用于阻止共收缩和局部负担转移；教师与 PPO 都不得
     用其中单项替代其余量。
- 明确未修改且当前哈希：
  - `RL/env/torque.py`：
    `e4e02a9432818ab7192e85ca52ca10dc84c0d8ce1cb42ec5ffd00c347b61820a`
  - `RL/env/sensors.py`：
    `e61dda0554b8a73792efc50a3e27fcaf8adc73d67889375812e173caa57c1682`
- 自检：三份 Markdown fence 数分别为 `6/6/14`，均为偶数；`rg` 已检查遗留裸
  `P0--P8`、旧 `B_m/C_m/s_m` 和 `third_party/Kinesis` 边界；未运行运行时代码
- 已知限制：速度条件 baseline 的统计方法、容差和权重仍必须在 B-P6 用训练集审计
  固定；文档不能代替 action-sensitivity 与配对 rollout 实验
- reviewer：必须未参与本轮编辑，独立核对当前三份文档、现有 `RL/train.py`、
  `RL/env/torque.py` 和 50 Hz/reset 事实；结论只能为 `PASS`、`REWORK` 或 `BLOCKED`
- 回退：不得改写本记录；如发现错误，只能修正文档并追加新记录
- 下一步：P0-004 独立复审通过后才开始共享 S-P1A 或 MyoAssist B-P2/B-P3 代码

### P0-004-REVIEW-001 独立复审

- 时间：2026-08-03
- 阶段：P0
- 状态：REWORK
- reviewer：`/root/inspect_eval`；未参与 `P0-004-REWORK-FIX-001` 编辑
- 复审范围：三份当前设计文档、`RL/train.py`、`RL/env/sensors.py`、
  `RL/env/torque.py`、`RL/env/kinesis/tcn_adapter.py`、MyoAssist 原模型和运行时基线
- 复审输入哈希：
  - boundary：`9442b4c3929ab2a93b320a4b59c077e54611309caf7c05e3913edc13bbc38653`
  - MyoAssist PPO plan：`1aba109310df41a5d9ceb314faad695c353d66efea3e0d7c37cdf8dddc57bac7`
  - shared plan：`760fe028f9fab0baeb7b8b10981ec11cffb2822cb4aa8bfb70b1de1a570dfbde`
  - 本日志（追加前）：`d67f757c94a5adfe71af0a2612e40583c6114749aa955bc0bbb842c41137ff63`
- 已通过的机械和源码事实检查：
  1. authority 固定为 boundary > 路线局部计划，`S-P*`/`B-P*` 命名已经分离；
  2. `third_party/myoassist/**` 和 `third_party/Kinesis/**` 均明确只读；
  3. `RL/train.py` 当前只支持 fresh PPO 或完整 PPO resume，三份文档已明确监督
     AssistActor 注入钩子尚不存在，`resume_from` 不能冒充监督初始化；
  4. 50 Hz 已降为候选并要求 repeated-reset/runner/report/hash 验收，没有再写成正式通过；
  5. `sensor32 + previous_applied_action4 = frame36`、四帧 `144`、TCN delta16 和
     Actor160 一致；TCN delta 顺序、preroll50、上一实际施加动作和动作 scale/硬限矩
     关系一致；
  6. 教师与 PPO 都以 $J_{act}$ 为主要生理代价、$J_{net}$ 为主要机械卸载量，并以
     $J_{gross}$ 防共收缩和负担转移；
  7. baseline 已禁止按未锁定 reference frame 逐帧相减，改为训练速度条件统计，最终
     省力只由同 seed、速度和初态的成对整段 rollout 计算；
  8. 三份 Markdown fence/math marker 配对，文档直接引用的既有源文件均存在，计划中
     尚未创建的文件均按未来产物描述。
- 独立运行时证据：
  1. `hackthon` 环境、禁用 bytecode 后运行上游 `test_setup.py`，13/13 通过；当前无
     display/GPU 的 reviewer 进程只产生 GLFW/GPU 环境限制，不改变 CPU 功能结论；
  2. 使用官方 MyoAssist 加载路径、冻结人体策略、旧两路踝动作固定为归一化 `+1`
     （物理控制 0）、50 Hz，在新建环境的 0.8/1.25 m/s、各 3 seeds 上均走满
     1000 steps，支持“50 Hz 候选”而非正式通过；
  3. 同一实例连续 reset 的首 Observation hash 不同，步数为 `1000/1000/995`；更严格
     的固定初态复核发现后续 reset 可在 `136/102` 步终止，初态相对第一次 reset 的
     `max|dqpos|=1.545`、`max|dqvel|=2.058`。因此 repeated-reset 阻塞真实存在，正式
     PPO 尚不可开始。
- HIGH-1，跨路线文件所有权仍冲突：boundary 明确 shared plan 只拥有路线 A/共享
  基础设施、PPO plan 只拥有路线 B；但 shared plan 的 `S-P2--S-P7` 仍声明实施
  MyoAssist 四髋膝模型、冻结人体/reset、sensor、TCN、`muscle_adapter.py` 和 PPO
  factory，与 PPO plan 的 `B-P2--B-P7` 重复拥有同一资产和文件。仅改阶段前缀没有
  消除并行覆盖风险；shared plan 的 `S-P6A` 自称拥有 `muscle_adapter.py`，其后又说
  `S-P6B` 等待“另一分支”提供同一文件，也形成内部依赖矛盾。
- HIGH-1 修复门：必须选定唯一 owner。可由 `B-P2--B-P6` 独占 MyoAssist 后端资产，
  `S-P*` 仅消费写明哈希与验收状态的具体产物；或由 `S-P*` 独占这些产物而 `B-P*`
  只引用。两份计划必须列出同一张不重叠的文件 owner/dependency 表。
- HIGH-2，正式 PPO 初始化门仍不一致：shared plan 要求正式 PPO 必须从监督 Actor
  初始化或学习有界 residual；PPO plan 只写“正式长训优先加载”监督 Actor。这允许
  路线 B 把 fresh PPO 从 smoke 升级为正式结果，与共享协议冲突。PPO plan 应把
  “优先”改成“必须”；若保留 fresh PPO，只能明确标为环境/奖励 smoke，不能作为
  有效助力证据。
- MEDIUM：PPO plan 只声明 $g\in[0,1]$ 和 $C_{upright}$，尚未固定它们的测量量、
  组合公式或明确由 B-P6 产出。允许在 B-P6 标定，但计划应写清该阶段的产物和不变量，
  避免两个实现各自解释 gate。
- 决定：本轮不能进入 `S-P1A`、`B-P2` 或正式 RL。先修复 HIGH-1/HIGH-2 并由新的
  reviewer 复审；之后仍须完成 `B-P3` 的同实例 repeated-reset 门。当前仅证明安装、
  新建环境的干净零助力基线和 50 Hz 候选可用，不足以证明 PPO episode 独立。
- 实际修改：仅向本追加式日志加入本记录；未修改三份计划、Python、第三方文件、
  checkpoint 或输出。

### P0-004-REWORK-FIX-002 唯一 owner、分路线 PPO 门与无相位 gate

- 时间：2026-08-03
- 阶段：P0
- 状态：REWORK-FIX 已编辑，待不同 agent 独立复审
- 编辑 agent：`root`；未参与 `P0-004-REVIEW-001`
- 目标：修复 reviewer 的两个 HIGH 和一个 MEDIUM 文档问题，同时把 repeated-reset
  明确归入 B-P3 运行时缺陷而不是伪装成已解决
- 非目标：不修改 Python、第三方、模型、配置、checkpoint 或输出；不启动 PPO
- 修改前哈希：
  - boundary：`9442b4c3929ab2a93b320a4b59c077e54611309caf7c05e3913edc13bbc38653`
  - MyoAssist PPO plan：`1aba109310df41a5d9ceb314faad695c353d66efea3e0d7c37cdf8dddc57bac7`
  - shared plan：`760fe028f9fab0baeb7b8b10981ec11cffb2822cb4aa8bfb70b1de1a570dfbde`
  - implementation log（review追加后）：
    `de226059bdf95e1ed759520ded70ceb602d0c45d1f088d835d4b72a3607bd28c`
- 修改后哈希：
  - boundary：`864b1cd0ef2b604f7f711de0dc4e57a8e70fb7c2ad5f00cf36a5821f982e8b84`
  - MyoAssist PPO plan：`5488f0258a3631e7b9a5dbafc7f55fbc860bdd97662c85887732fc05891bbc42`
  - shared plan：`5e5c2882618591b321fdd745a1c89e956bd9f522eedc5dc4c82cc7ec1a5c60a1`
  - 本日志为追加式文件，哈希随本记录和后续 review 变化
- 修复内容：
  1. boundary 增加唯一 owner 表：共享基础设施归路线 A，`RL/env/myoassist/**`、
     MyoAssist 资产和 runner 仅归路线 B，Kinesis 专属文件归 Kinesis 分支，上游
     third_party 只读；消费者只能记录输入哈希，不得重复声明修改权；
  2. shared plan 删除对 MyoAssist 模型、adapter、sensor、muscle adapter 和 PPO
     runner 的实施阶段所有权；S-P2--S-P5 只负责教师、监督 Actor、通用监督初始化
     钩子与中立配对评估；
  3. 路线 A 正式 PPO 继续强制监督初始化/有界 residual；路线 B 的 fresh PPO 是独立
     的最快首轮，必须先过 B-P6 action-sensitivity 和 B-P8 审计，不能作为路线 A
     证据；监督 warm start 后续由 S-P4 提供对照；
  4. B-P6 gate 固定为目标速度与无相位站立包络，不读取 reference index。包络仅含
     骨盆高度、躯干俯仰和四关节限位余量；公式固定 $g=g_vg_u$，正 saving 被 gate，
     负 saving 始终保留；
  5. repeated-reset 已由 reviewer 证明异常，明确为 B-P3 首要实现与验收目标；它继续
     阻塞 B-P7 和正式训练，但不应阻止开始 B-P2/B-P3 修复代码。
- 自检：阶段表不再含 shared-owned MyoAssist backend 文件；PPO plan 不再含 reference
  tracking reward；三份文档继续保持 `S-P*`/`B-P*` 分离和 third-party 只读边界
- reviewer：必须未参与本次编辑，核对唯一 owner 表、两条 PPO 证据边界、gate 公式，
  并确认 repeated-reset 被正确留作 B-P3 阻塞而非 P0 已通过事实
- 回退：不得改写历史；如复审失败，只追加下一次 REWORK 记录
- 下一步：独立复审 PASS 后开始 B-P2 四执行器模型；随后 B-P3 必须修复 repeated reset

### P0-004-REVIEW-002 独立复审

- 时间：2026-08-03
- 阶段：P0
- 状态：REWORK
- reviewer：`/root/p0_boundary_reviewer`；未参与
  `P0-004-REWORK-FIX-002` 编辑
- 复审范围：当前三份设计文档、实施日志、`RL/train.py`、
  `RL/env/sensors.py`、`RL/env/torque.py`、
  `RL/env/kinesis/tcn_adapter.py` 和 `RL/env/kinesis/exo_env.py`
- 复审输入哈希：
  - boundary：`864b1cd0ef2b604f7f711de0dc4e57a8e70fb7c2ad5f00cf36a5821f982e8b84`
  - MyoAssist PPO plan：`5488f0258a3631e7b9a5dbafc7f55fbc860bdd97662c85887732fc05891bbc42`
  - shared plan：`5e5c2882618591b321fdd745a1c89e956bd9f522eedc5dc4c82cc7ec1a5c60a1`
  - implementation log（追加前）：
    `90142b92dff8f0dc9e26aced24c48ae51c3e9116f83320caa62a37ab44d50f53`
  - `RL/train.py`：
    `bfa3c33eec5bd0c34512345e21db808282c6d7b6ad021cff6ec2f187a471941c`
  - `RL/env/sensors.py`：
    `e61dda0554b8a73792efc50a3e27fcaf8adc73d67889375812e173caa57c1682`
  - `RL/env/torque.py`：
    `e4e02a9432818ab7192e85ca52ca10dc84c0d8ce1cb42ec5ffd00c347b61820a`
  - `RL/env/kinesis/tcn_adapter.py`：
    `edb2da3577e841ce2efd1b1c893a7e47b28d0a4aa1b428d1688385d4a4d703a8`
  - `RL/env/kinesis/exo_env.py`：
    `3c374f6c4a08bfbd85a5b0c34c54f5a2fa14d7aba949e82e91d30df50fd69811`
- 已通过的独立检查：
  1. boundary 已固定权威层级，阶段前缀已分为 `S-P*` 和 `B-P*`；
  2. `third_party/myoassist/**` 和 `third_party/Kinesis/**` 均明确只读；前者
     2425 文件有序聚合哈希为
     `0c11c7c9a83b2e2169446a84cfe0d1e14b433db823c368a8c7a8151ee3e95f10`，
     后者 879 文件有序聚合哈希为
     `116c021f79abed993325290fae1e8a80a2f31da2a8afa6f2d16c2a6d0e166380`；
  3. 源码确认 `RL/train.py` 只有 `PPO(...)` fresh 创建和 `PPO.load(...)` 完整恢复，
     不存在监督 AssistActor 注入或参数映射；文档正确声明 `resume_from` 不等于监督
     初始化；
  4. 50 Hz 六个 episode 仍只写作候选证据，并继续要求 runner、报告、配置哈希和
     repeated-reset 验收；
  5. 路线 A 的正式 PPO 已硬性要求监督 Actor 初始化或有界 residual；
  6. PPO plan 已把 baseline 限定为训练速度条件统计，把最终省力限定为同 seed、速度、
     初态的整段配对 rollout，并明确 $C_a$、$C_h$、$C_g$ 的生理/机械职责；速度与
     无相位站立 gate 的测量量、铰链和组合公式已经可直接实现；
  7. 三份文档对 delta16 顺序、固定 mean/std/clip、上一实际施加动作、requested /
     applied 时序、逐关节 action scale / hard limit、真实零助力 preroll50 和
     normalized-action 监督损失一致；现有 TCN adapter 的 delta 和固定归一化实现与
     计划一致，现有 `TorqueActuator` 尚无独立 action scale，已被正确列为 S-P1A 的
     未来兼容修改而非现有能力。
- HIGH-1，唯一 owner 仍被 `B-P1` 破坏：boundary 的 owner 表把
  `RL/optimization/**`、`RL/metrics/**` 和共享兼容层交给路线 A，但 boundary 的阶段表
  仍将 B-P1 写成“中立协议、指标与兼容重新导出”，PPO plan 的 B-P1 还明确要求新增
  `RL/optimization/contracts.py`、`RL/metrics/physiology.py` 并修改 Kinesis 兼容导出；
  shared plan 的 S-P1A/S-P1B 同时拥有这些文件。按当前顺序执行会由两条路线修改同一
  共享文件。
- HIGH-1 修复门：B-P1 必须改成只消费并验证已 PASS 的 S-P1A/S-P1B 版本化产物，
  或从 B 路线删除；boundary 阶段表、PPO plan 和 shared stage table 必须指向同一个
  owner/dependency，不得让 B-P1 实施共享文件。
- HIGH-2，shared plan 第 6.5 节仍要求完成不存在的 `S-P6B` 教师审计，但修订后的阶段
  表只有 S-P2 真实教师，且其依赖 B-P6 `MuscleSnapshot`。该陈旧阶段名会使实施门无法
  判定。应明确改为“B-P6 adapter PASS 后执行 S-P2 教师审计”。
- MEDIUM，路线 B fresh PPO 的证据级别仍有术语冲突：boundary 和 PPO plan 允许在
  B-P8 后执行“正式首轮/长程”fresh PPO，而 shared plan 把路线 B fresh PPO 全部描述为
  工程 smoke 且不能据此声称有效助力。应明确区分“不能替代路线 A 监督证据”和“路线 B
  自身在成对 holdout 门通过后可形成何种结论”，避免训练 runner 对正式结果资格作出
  相反解释。
- 已正确保留的运行时阻塞：同一实例 repeated-reset 异常仍归 B-P3 修复与验收，文档
  没有把它写成 P0 已解决事实。
- 独立命令与结果：
  - 三份计划和日志的 Markdown fence/display-math 数分别为 `6/2`、`6/40`、
    `14/48`、`4/0`，全部成对，退出码 0；
  - `rg` 检查裸 `P*` 阶段名无命中，退出码 1 表示无匹配；检查旧阶段名时命中
    `S-P6B`；
  - 本机 `rg` 不支持 PCRE2，首次负向前瞻检查退出码 2；改用 POSIX 上下文表达式后
    完成同一只读检查；
  - `sha256sum`、第三方有序聚合哈希和源码定位命令均退出码 0。
- 决定：本轮不能 PASS。先修复 HIGH-1/HIGH-2，并收口路线 B fresh PPO 的证据术语，
  再由新的 reviewer 基于稳定哈希复审；在此之前不得开始会修改共享文件的 B-P1 或
  S-P1A，也不得把 fresh PPO 长训当作已授权的有效助力结果。
- 实际修改：仅向本追加式日志加入本记录；未修改三份计划、Python、第三方、模型、
  checkpoint 或输出。

### P0-004-REWORK-FIX-003 共享依赖消费与 fresh PPO 证据等级收口

- 时间：2026-08-03
- 阶段：P0
- 状态：REWORK-FIX 已编辑，待新的独立 reviewer
- 编辑 agent：`root`；未参与 `P0-004-REVIEW-002`
- 目标：修复 REVIEW-002 的两个 HIGH 和一个 MEDIUM 文档问题
- 非目标：不修改 Python、第三方、资产、checkpoint 或输出；不修复 repeated reset
- 修改前哈希：
  - boundary：`864b1cd0ef2b604f7f711de0dc4e57a8e70fb7c2ad5f00cf36a5821f982e8b84`
  - PPO plan：`5488f0258a3631e7b9a5dbafc7f55fbc860bdd97662c85887732fc05891bbc42`
  - shared plan：`5e5c2882618591b321fdd745a1c89e956bd9f522eedc5dc4c82cc7ec1a5c60a1`
  - log：`9475b8a4bcefb107c1965b9aa299a3aafaaaed3a9fbfad22280cf05ddc1f779b`
- 修改后哈希：
  - boundary：`22433b7024fb5b1e0b1fd92a860a014ef1b903f7035ae01669e02ab518d42869`
  - PPO plan：`5109ce9bea48ccda13d55d9548d3917174ef950eeb7bf0d1b72604d544f8d71e`
  - shared plan：`248a6fdde27a106166aad41084197359bc82cdada000e3c004db4a6ab56e02b5`
  - 本日志为追加式，哈希随本记录变化
- 修复内容：
  1. B-P1 改为只消费并验证已 PASS 的 S-P1A/S-P1B 文件哈希、schema 和接口，明确
     路线 B 不新增或修改 `RL/optimization/**`、`RL/metrics/**` 或 Kinesis 兼容层；
  2. B-P2/B-P3 可在等待共享产物时独立推进，但 B-P4/B-P6 不得复制共享实现绕过依赖；
  3. shared 第 6.5 节旧 `S-P6B` 改为“B-P6 adapter PASS 后执行 S-P2 教师审计”；
  4. fresh PPO 的证据等级固定：smoke 本身无助力结论；B-P8 后只有在预注册配对
     holdout 同时满足激活/净关节力矩改善、gross 不恶化、速度和站立合格，才可声称
     “当前 MyoAssist 二维模型中有效”，不得替代路线 A 或外推真人/URDF/转向/楼梯。
- 自检：`rg` 检查 B-P1 不再拥有共享文件、旧 `S-P6B` 无命中、三份计划对 fresh PPO
  结论边界一致；Markdown fence 与 display math 仍成对
- reviewer：必须是未参与本次编辑的新 agent；独立读取稳定哈希并追加 PASS/REWORK
- 下一步：P0 PASS 后可开始 B-P2；repeated-reset 仍由 B-P3 修复且阻塞 B-P7/正式训练

### P0-005-REWORK-FIX-001 Kinesis 只读所有权与候选训练术语收口

- 时间：2026-08-03
- 阶段：P0
- 状态：REWORK-FIX 已编辑，待新的独立 reviewer
- 编辑 agent：`root`；未参与 `P0-004-REVIEW-002`
- 目标：在 `P0-004-REWORK-FIX-003` 基础上进一步消除路线 A 阶段表对 Kinesis
  专属文件的隐含修改权，并把路线 B fresh PPO 的证据术语统一为“候选训练”
- 非目标：不修改 Python、第三方、MyoAssist/Kinesis 后端、资产、checkpoint 或输出
- 修改前哈希：
  - boundary：`22433b7024fb5b1e0b1fd92a860a014ef1b903f7035ae01669e02ab518d42869`
  - PPO plan：`5109ce9bea48ccda13d55d9548d3917174ef950eeb7bf0d1b72604d544f8d71e`
  - shared plan：`248a6fdde27a106166aad41084197359bc82cdada000e3c004db4a6ab56e02b5`
  - implementation log：
    `371ac3ec58857a8cd4c5f2353e088e914901515f415e87cefbbba3fc3cb996a6`
- 修改后哈希：
  - boundary：`b893a6c8c407829f313f63fdf185acf547522c64b7bb880eb5299cd95474ded7`
  - PPO plan：`6ad599325206e748834615da0b52fa9f1680b1231b728fcf82c0030afc6ca2f7`
  - shared plan：`04f02222a5e042963a31ec7746022cb5203887a9c427f35f47212f3fd62e2e27`
  - 本日志为追加式，哈希随本记录和后续 review 变化
- 修复内容：
  1. 路线 A 只新增中立 physiology/TCN/Observation 实现，并以只读方式对现有
     Kinesis 公式和推理做数值等价测试；不修改 `RL/env/kinesis/**`；
  2. 任何 Kinesis 兼容重新导出或共享 runtime 接入均明确归 Kinesis 分支单独实施；
  3. shared 阶段表的 S-P1B/S-P1C 不再把“旧兼容文件”或“Kinesis adapter”列入
     修改文件，只列共享实现和共享测试；
  4. 路线 B 在 B-P8 后执行的是 fresh PPO 候选训练，训练回报上升不构成有效性；
     仅当预注册成对 holdout 通过时，才允许形成“当前 MyoAssist 二维模型内有效”的
     有限结论，且不得替代路线 A 监督证据或外推实机。
- 数据流不变：本轮只收紧文件 owner 和证据措辞，没有改变 sensor32、delta16、
  Observation160、动作尺度、preroll50 或 reward 公式
- 自检：旧 `S-P6B`、B-P1 共享文件所有权、`最快正式首轮`、`正式首轮训练前` 和
  `首轮正式训练` 均无命中；S-P1B/S-P1C 明确只读 Kinesis 等价审计
- 回退：不得改写本记录；复审失败时只追加新的修正记录
- 下一步：由未参与本次编辑的新 agent 基于当前稳定哈希复审；PASS 前不修改 Python

### P0-005-REVIEW-001 当前边界、依赖图与源码事实独立复审

- 时间：2026-08-03
- 阶段：P0
- 状态：REWORK
- reviewer：`/root/p0_final_reviewer`；未参与 P0 文档或
  `P0-004-REWORK-FIX-003`、`P0-005-REWORK-FIX-001` 的编辑
- review 权限：三份设计文档和源码只读；仅向本追加式日志加入本记录
- review 起点稳定哈希：
  - boundary：`b893a6c8c407829f313f63fdf185acf547522c64b7bb880eb5299cd95474ded7`
  - PPO plan：`6ad599325206e748834615da0b52fa9f1680b1231b728fcf82c0030afc6ca2f7`
  - shared plan：`04f02222a5e042963a31ec7746022cb5203887a9c427f35f47212f3fd62e2e27`
  - implementation log（追加本记录前）：
    `ee04dab99103120528d27808eb9976692e84adfcbcdcfec732e61b2f7c5b7b72`
- 已通过项：
  1. `PASS`：顶层 owner 表已经把共享基础设施、MyoAssist、Kinesis 和两个
     `third_party` 范围分别交给唯一 owner；活跃阶段表不再授权路线 A 修改
     `RL/env/kinesis/**`，Kinesis 等价检查明确为只读。
  2. `PASS`：B-P1 只消费并验证已独立 `PASS` 的 S-P1A/S-P1B 哈希、schema 和公开
     接口；B-P1 没有共享文件修改权，且 B-P2/B-P3 可独立推进、B-P4/B-P6 不得复制
     私有实现绕过依赖。
  3. `PASS`：三份活跃设计文档中 `S-P6B` 零命中；历史日志中的旧命中按追加式审计
     规则保留，不是活跃阶段依赖。shared 第 6.5 节已经改为 B-P6 adapter `PASS`
     后执行 S-P2 教师审计。
  4. `PASS`：fresh PPO 证据等级一致。B-P8 前只能做工程 smoke；B-P8 后是候选训练，
     回报升高本身不代表助力有效；只有预注册的同条件成对 holdout 同时满足激活平方/
     人体净关节力矩、gross、速度、站立与存活门，才能形成“当前 MyoAssist 二维模型
     内有效”的有限结论，且不能替代路线 A 或外推真人、URDF、转向、楼梯。
  5. `PASS`：同一实例 repeated-reset 异常仍被明确留给 B-P3 修复和验收，不被 P0
     文档结论掩盖；B-P3 未通过前禁止 B-P7 smoke 和候选训练。源码独立检查确认
     imitation reset 使用无 seed 的 `np.random.default_rng()`，并把当前 sim qpos/qvel
     重新传给父 reset，因此该阻塞与现有实现事实一致。
  6. `PASS`：Markdown 机械结构、主要路径和现有源码事实一致。三份文档的 fence 数为
     `6/6/14`、display-math delimiter 数为 `2/40/48`，均为偶数；现有共享文件、
     MyoAssist base/imitation/空壳 Exo、22 肌肉 XML、speed-control config/checkpoint
     均存在。MuJoCo 独立解析得到 `nq=53, nv=53, nu=24, na=22`，前 22 路为肌肉、
     最后两路为 `Exo_R/Exo_L` 且 `ctrlrange=[-1,0]`；配置确认控制/物理频率为
     `30/1200 Hz`、人体 observation 索引覆盖 44 维、人体 action 映射为 22 维。
- 阻塞发现：
  1. `HIGH`，唯一 owner 仍在 B-P5 出现可执行歧义。boundary 把共享 TCN runtime
     交给路线 A，shared 阶段表也把它固定为 S-P1C；但 PPO plan 第 6.5/8 节的 B-P5
     仍写成“抽取或复用共享 TCN runtime”，并且没有要求先验证 S-P1C 的 `PASS`、
     文件哈希和协议版本。按字面执行“抽取”会让路线 B 新增或修改路线 A 独占的共享
     文件，与唯一 owner 和“任何文件只能出现在一个路线实际修改栏”冲突。
  2. `MEDIUM`，B-P7 的“只新增 MyoAssist 环境工厂、训练入口参数和统一 evaluator”
     没有写明这些新增只落在路线 B runner；紧邻文字又引用共享 `RL/train.py`，实现者
     可能把 MyoAssist 参数写入路线 A 独占的通用训练器。现有 `RL/train.py` 只有
     fresh/resume PPO，文档已正确把监督初始化留给 S-P4，但 B-P7 的实际修改路径仍需
     收口。
- 修复门：
  1. B-P5 改为“只消费并验证已独立 PASS 的 S-P1C runtime”，记录文件哈希、schema、
     checkpoint/calibration 协议和导入 smoke；删除“抽取”，明确不修改共享 TCN 文件
     或 Kinesis adapter。B-P1 继续只消费 S-P1A/S-P1B，不把 S-P1C 塞回 B-P1。
  2. B-P7 明确所有新增参数、工厂和 evaluator 只位于路线 B 所有的 MyoAssist runner；
     该阶段只调用 `RL/train.py` 公开接口，不修改它。通用训练器若确需扩展，另交共享
     owner 阶段实施和 review。
- 独立命令与结果：
  - `sha256sum` 四份文档，三份设计文档在完整审查期间保持上述稳定哈希；
  - `rg -n 'S-P6B'` 检查三份活跃设计文档，退出码 1，表示零命中；
  - `rg -c '^```'` 与 `rg -c '^\\$\\$$'` 检查 fence/display math，计数全部成对；
  - `rg` 审计 B-P1/S-P1A/S-P1B、fresh PPO、repeated reset、owner 和只读边界；
  - `test -f` 核对现有共享源码、MyoAssist 源码、XML、config 和 checkpoint，全部存在；
  - `/home/lenovo/anaconda3/envs/hackthon/bin/python -c 'import mujoco; ...'` 独立解析
    22 肌肉 XML，退出码 0，维度、actuator 顺序和 ctrlrange 如上；
  - `rg`/`sed` 独立检查 `RL/env/sensors.py`、`RL/env/torque.py`、`RL/train.py`、
    MyoAssist base/imitation/Exo 和 speed-control config，确认计划所述现状。
- review 结论：`REWORK`。P0 的科学边界、证据等级和 reset 归属已经通过，但 B-P5
  仍会造成跨 owner 实施；修复上述 owner/dependency 文字并由另一新 reviewer 复审前，
  不得开始 S-P1A、B-P2 或任何 Python 修改。
- 实际修改：仅追加本 review 记录；未修改三份计划、Python、第三方、资产、checkpoint
  或输出。

### P0-006-REWORK-FIX-001 B-P5/B-P7 消费路径收口

- 时间：2026-08-03
- 阶段：P0
- 状态：REWORK-FIX 已编辑，待新的独立 reviewer
- 编辑 agent：`root`；未参与 `P0-005-REVIEW-001`
- 目标：消除 B-P5 对共享 TCN 的潜在修改权，以及 B-P7 对通用 `RL/train.py` 的
  潜在顺带修改权
- 非目标：不修改 Python、第三方、资产、checkpoint、输出或任何运行时协议
- 修改前哈希：
  - boundary：`b893a6c8c407829f313f63fdf185acf547522c64b7bb880eb5299cd95474ded7`
  - PPO plan：`6ad599325206e748834615da0b52fa9f1680b1231b728fcf82c0030afc6ca2f7`
  - shared plan：`04f02222a5e042963a31ec7746022cb5203887a9c427f35f47212f3fd62e2e27`
  - implementation log：
    `70960ce632eccf5e66212ae2ea940aa3daae167c551e5a1fbc4ee469cf431bee`
- 修改后哈希：
  - boundary：`11b6fb2be8149c0c4ee14d8728544369030d936e55b99573c0eb08a96e00bab2`
  - PPO plan：`8934ad12c69c3efd701a171d3ccff67b3d30e4647318b5f56d7b22304108d0c3`
  - shared plan：未修改，仍为
    `04f02222a5e042963a31ec7746022cb5203887a9c427f35f47212f3fd62e2e27`
  - 本日志为追加式，哈希随本记录和后续 review 变化
- 修复内容：
  1. B-P5 只消费并验证已 `PASS` 的 S-P1A/S-P1C，记录文件哈希、schema、
     checkpoint/calibration 协议和导入 smoke；
  2. B-P5 的接线只落在 `RL/env/myoassist/**`，不新增或修改共享 TCN/Observation，
     也不修改 Kinesis adapter；
  3. B-P7 的工厂、参数和 evaluator 只落在 MyoAssist 专属 runner/adapter；
  4. B-P7 只调用 `RL/train.py` 公开接口且不修改它；接口不足时必须把变更请求交给
     shared owner，以独立步骤编辑和 review。
- 数据流：没有变化；本轮只把 owner/dependency 文字变成可执行的唯一路径
- 自检：`rg` 定位 B-P5/B-P7 均明确“只消费/不修改”，共享计划和所有 Python 哈希
  未变
- 回退：不得改写历史；复审失败时只追加修正记录
- 下一步：由未参与本次编辑的新 agent 复审；PASS 前不修改 Python

### P0-006-REVIEW-001 B-P5/B-P7 所有权与训练证据独立复审

- 时间：2026-08-03
- 阶段：P0
- 状态：PASS
- reviewer：`/root/p0_006_reviewer`；未参与 P0 文档或
  `P0-006-REWORK-FIX-001` 的编辑
- review 权限：三份设计文档只读；仅向本追加式日志加入本记录
- review 起点稳定哈希：
  - boundary：`11b6fb2be8149c0c4ee14d8728544369030d936e55b99573c0eb08a96e00bab2`
  - MyoAssist PPO plan：`8934ad12c69c3efd701a171d3ccff67b3d30e4647318b5f56d7b22304108d0c3`
  - shared plan：`04f02222a5e042963a31ec7746022cb5203887a9c427f35f47212f3fd62e2e27`
  - implementation log（追加本记录前）：
    `37acf11566e6697b84a7c331d633c82b66d0d940be52038f8711e77139081556`
- 复审结论：
  1. `PASS`：B-P5 只消费已独立 `PASS` 的 S-P1A Observation builder 和 S-P1C
     TCN runtime，并要求记录文件哈希、schema/version、checkpoint/calibration 协议与
     导入 smoke；MyoAssist 接线只落在 `RL/env/myoassist/**`，不得修改共享 TCN、
     Observation 或 Kinesis adapter，也不得用私有复制品绕过未通过的共享依赖。
  2. `PASS`：B-P7 的环境工厂、训练入口参数和 evaluator 明确只落在
     `RL/runners/train_myoassist_gexo.py`、`RL/runners/evaluate_myoassist_gexo.py`
     与 `RL/env/myoassist/**`；该阶段只调用 `RL/train.py` 公开接口且不修改它，接口
     不足时必须向 shared owner 提交独立变更并重新 review。
  3. `PASS`：顶层唯一 owner、S-P/B-P 阶段命名空间和跨路线依赖保持一致。B-P1 仍
     只消费 S-P1A/S-P1B；S-P1B/S-P1C 只新增共享实现并对 Kinesis 做只读等价审计；
     活跃设计文档不存在 `S-P6B`，Kinesis 兼容重新导出仍归 Kinesis 分支。
  4. `PASS`：路线 B 的 fresh PPO 仍被限定为 B-P8 后的候选训练；训练回报升高本身
     不构成有效助力证据。只有预注册、同条件的成对 holdout 同时满足激活平方、人体
     净关节力矩、gross、速度、站立和存活门，才能形成“当前 MyoAssist 二维模型内
     有效”的有限结论，不能替代路线 A 或外推真人、URDF、转向和楼梯。
  5. `PASS`：repeated-reset 仍是 B-P3 的运行时阻塞，未被 P0 文档写成已解决事实；
     B-P3 未通过前不得进入 B-P7 smoke 或候选训练。
  6. `PASS`：Markdown 机械结构通过。boundary、PPO plan、shared plan 的 fence 数
     分别为 `6/6/14`，display-math delimiter 数分别为 `2/40/48`，全部成对；复审
     全程三份设计文档哈希保持稳定。
- 独立命令与结果：
  - `sha256sum` 在复审开始、定向检查后和追加前重复执行，三份设计文档始终保持上述
    稳定哈希；日志追加前哈希为上述值，命令退出码 0；
  - `rg -n -C 3 'B-P5|B-P7|S-P1A|S-P1C|RL/train\\.py|RL/env/kinesis|fresh PPO|候选训练|配对 holdout' ...`
    确认两个修复门、所有权与证据等级，退出码 0；
  - `rg -n -C 2 '实际修改|唯一 owner|只消费|修改.*共享|修改.*Kinesis|修改.*RL/train|S-P6B|B-P1' ...`
    确认唯一 owner 与依赖；`S-P6B` 仅作为搜索式的一部分且无活跃命中；
  - `rg -c '^```'` 与 `rg -c '^\\$\\$$'` 分别检查三份文档的代码 fence 和 display
    math delimiter，计数均为偶数，命令退出码 0。
- 决定：P0 文档与边界阶段 `PASS`。可以按日志制度启动下一独立变更单元；B-P2/B-P3
  可先推进，B-P4/B-P5/B-P6 必须分别等待其声明的共享阶段 `PASS`，且每步仍须由
  未参与编辑的 agent 独立 review 和测试。
- 实际修改：仅追加本 review 记录；未修改三份计划、Python、第三方、资产、模型、
  checkpoint 或输出。

### P0-006-SCIENCE-REVIEW-002 全文科学可执行性交叉复审

- 时间：2026-08-03
- 阶段：P0
- 状态：REWORK
- reviewer：`/root/p0_boundary_reviewer`；未参与 P0 文档、
  `P0-006-REWORK-FIX-001` 或 `P0-006-REVIEW-001` 的编辑
- review 权限：四份设计文档和源码只读；仅向本追加式日志加入本记录
- 与上一条 review 的关系：`P0-006-REVIEW-001` 对 B-P5/B-P7 owner 修复的 `PASS`
  仍然成立；本记录检查的是更宽的科学公式、跨路线指标和复现契约，发现新的阻塞，
  不把已经通过的所有权结论改写为失败
- review 起点稳定哈希：
  - boundary：`11b6fb2be8149c0c4ee14d8728544369030d936e55b99573c0eb08a96e00bab2`
  - MyoAssist PPO plan：`8934ad12c69c3efd701a171d3ccff67b3d30e4647318b5f56d7b22304108d0c3`
  - shared plan：`04f02222a5e042963a31ec7746022cb5203887a9c427f35f47212f3fd62e2e27`
  - fixed-trajectory science plan：
    `d769746f3e7feaaa299b47178c9938525dbf0a2437e308e7cb284e5643066ab4`
  - implementation log（追加本记录前）：
    `467b6f0f5bf029a22f104f29bb8e2382267df3641e7b4247ba81b18b43a7fe83`
- 已通过项：
  1. `PASS`：共享、MyoAssist、Kinesis 和第三方目录保持唯一 owner；B-P5 只消费
     S-P1A/S-P1C，B-P7 只调用 `RL/train.py` 公开接口，未重新出现跨 owner 修改权。
  2. `PASS`：现有源码事实仍与计划一致。`RL/train.py` 只有 fresh `PPO(...)` 与完整
     `PPO.load(...)` 恢复，没有监督 AssistActor 初始化；`RL/env/torque.py` 仍直接以
     hard limit 缩放动作；旧 Kinesis TCN/Observation 仍是后续只读等价基线。
  3. `PASS`：四份计划的代码 fence 数为 `6/6/14/24`，display-math delimiter 数为
     `2/40/48/50`，全部成对；五个被核对 Python 文件均通过 Python 3 AST 解析。
  4. `PASS`：两个第三方目录保持只读审计基线：`third_party/myoassist` 共 2425 个文件，
     聚合哈希 `0c11c7c9a83b2e2169446a84cfe0d1e14b433db823c368a8c7a8151ee3e95f10`；
     `third_party/Kinesis` 共 879 个文件，聚合哈希
     `116c021f79abed993325290fae1e8a80a2f31da2a8afa6f2d16c2a6d0e166380`。
- 阻塞发现：
  1. `HIGH`，路线 A 的固定轨迹优化目标尚不能唯一实现。shared plan 先声明扫描单一
     $\rho$，约束却使用没有与它建立映射的 $\rho_a$ 和 $\rho_\tau$；目标中的
     $J_{interaction}$ 没有定义，而被引用的 fixed-trajectory science plan 使用的是
     $J_{belt}$。boundary 的“固定权威层级”又没有列出该 science plan 的相对等级。
     实现者目前必须自行猜测卸载目标和第三个代价项，S-P1D 无法得到唯一答案。
  2. `HIGH`，路线 B 的 gross reward baseline 未定义。PPO plan 只建立
     $\mu_a(v),\sigma_a(v),\mu_h(v),\sigma_h(v)$，随后却在
     $C_{gross,excess}$ 中使用 $\mu_g(v)$；B-P6 的冻结参数清单没有说明
     $\mu_g(v)$ 的估计量、样本集合、稳健统计或最小正尺度。相同代码无法按文档复现
     gross gate。
  3. `MEDIUM`，两路线称为“统一”的生理指标仍缺少数值绑定。shared plan 使用
     $\mathcal M_{target}$、$w_i$、$w_j$ 和 $\tau_{scale,j}$；PPO plan 固定全部 22
     块肌肉、等权均值以及 $S_{h,j}$、$S_j$。文档没有规定 MyoAssist MVP 的目标肌肉
     mask、权重归一化及这些 scale 之间的对应关系，因此路线 A 教师与路线 B holdout
     可能报告同名但不等价的 activation/net/gross。
  4. `MEDIUM`，路线 B 的 baseline、reward 与 gate 参数没有完整进入实验复现契约。
     metadata 清单缺少 baseline 产物哈希、$\mu/\sigma$、$\mu_g$、$\alpha$、
     $\delta_g$、速度/站立铰链阈值、reward 权重和 estimator 版本；保存恢复即使网络
     权重一致，也不能证明 reward 与 holdout 计算一致。
  5. `MEDIUM`，shared plan 允许正式 PPO “从监督 Actor 初始化或学习有界 residual”，
     但 S-P4 只定义监督权重映射，没有 residual 的组合公式、幅值边界、冻结策略、
     checkpoint metadata 或等价测试。监督初始化路径可以实施；residual 路径必须从
     MVP 删除，或作为独立阶段补齐后才能实施。
  6. `LOW`，shared plan 用“改善激活/人体净关节力矩”概括路线 B 的有效性，容易被
     解释为二选一或两者都必须显著下降；PPO plan 的精确定义是两者均不恶化、至少
     一项跨 seed 稳定改善，并同时满足 gross、速度、站立、存活和 episode 长度门。
     共享摘要应直接引用该完整谓词，避免验收实现分叉。
- 修复门：
  1. 把 fixed-trajectory science plan 加入权威层级，并固定 $\rho$ 到
     $(\rho_a,\rho_\tau)$ 的扫描规则；统一使用并定义 $J_{belt}$ 或
     $J_{interaction}$，不能保留两个未映射名称。
  2. 在 B-P6 明确定义、拟合和冻结 $\mu_g(v)$，包括训练 baseline split、统计量、
     epsilon/floor 与外推速度行为。
  3. 为 MyoAssist specialization 固定 target muscle mask、$w_i/w_j$、activation/net/
     gross 的离散时间归一化和 scale 映射；将它们连同 baseline/reward/gate 参数及
     产物哈希写入训练和评估 metadata。
  4. S-P4 首版只保留监督初始化，或新增单独 residual 阶段并定义组合、限幅、冻结、
     保存恢复和测试契约。
  5. shared plan 的路线 B 成功门直接引用 PPO plan 的完整成对 holdout 谓词。
- 独立命令与结果：
  - `sha256sum` 在全文检查前和追加前重复执行；四份设计文档保持上述稳定哈希；
  - `nl -ba`/`sed`/`rg` 逐项定位文档权威层级、$\rho$、$\rho_a/\rho_\tau$、
    $J_{interaction}/J_{belt}$、$\mu_g$、指标参数、metadata、residual 和有效性谓词；
  - `rg -c '^```'` 与 `rg -c '^\$\$$'` 检查四份计划 Markdown 结构，计数均为偶数；
  - `python3` 使用 `ast.parse` 检查 `RL/train.py`、`RL/env/sensors.py`、
    `RL/env/torque.py`、`RL/env/kinesis/tcn_adapter.py`、
    `RL/env/kinesis/exo_env.py`，五项均 `AST PASS`；
  - `find ... -print0 | sort -z | xargs -0 sha256sum | sha256sum` 独立计算两个第三方树的
    文件数和聚合哈希，结果如上；
  - 活跃计划中旧 `S-P6B` 和旧正式训练术语零命中。
- review 结论：`REWORK`。B-P5/B-P7 的所有权修复已经通过，但完整计划仍不能唯一
  实现 S-P1D、B-P6 和 residual PPO，也不能保证两路线的生理指标与实验配置可比、
  可复现。按追加式流程先修正文档并由新的 reviewer 复审；不得用代码中的默认值
  替代这些尚未确定的科学决定。
- 实际修改：仅追加本 review 记录；未修改四份计划、Python、第三方、资产、模型、
  checkpoint 或输出。

### P0-006-SCIENCE-REVIEW-003 共享边界可执行性补充

- 时间：2026-08-03
- 阶段：P0
- 状态：REWORK-ADDENDUM
- reviewer：`/root/p0_boundary_reviewer`；交叉检查来源为只读 agent
  `/root/p0_boundary_reviewer/doc_crosscheck`
- review 权限：设计文档和源码只读；仅向本追加式日志加入本记录
- 关系：补充 `P0-006-SCIENCE-REVIEW-002`，不改变
  `P0-006-REVIEW-001` 对 B-P5/B-P7 owner 修复的局部 `PASS`
- 起点哈希：
  - boundary：`11b6fb2be8149c0c4ee14d8728544369030d936e55b99573c0eb08a96e00bab2`
  - MyoAssist PPO plan：`8934ad12c69c3efd701a171d3ccff67b3d30e4647318b5f56d7b22304108d0c3`
  - shared plan：`04f02222a5e042963a31ec7746022cb5203887a9c427f35f47212f3fd62e2e27`
  - fixed-trajectory science plan：
    `d769746f3e7feaaa299b47178c9938525dbf0a2437e308e7cb284e5643066ab4`
  - implementation log（追加本记录前）：
    `9104ee4a22a91cfed77653207bb9504fe5376b5ee479d8e742e421683f2324a3`
- 补充发现：
  1. `HIGH`，boundary 的共享依赖白名单与它列出的现有共享文件矛盾。该文档规定共享
     模块只能依赖 NumPy、PyTorch、Gymnasium 或自身契约，但同一表中的
     `RL/data/preprocess_tcn.py` 实际依赖 pandas，`RL/train.py` 实际依赖
     Stable-Baselines3。按字面遵守会使两个已声明的共享模块违规。应将约束改成按层
     分类的依赖白名单，或把核心禁令收口为不得依赖 MyoAssist、Kinesis、具体 MuJoCo
     对象和后端模型名。
  2. `HIGH`，runtime32 采集与 Actor 组帧的 owner 仍有高低层文档冲突。boundary 把
     `RL/env/sensors.py` 写成“统一组帧和传感器协议”，并将 `SensorReader` 的“组帧”
     列为直接复用；shared plan 则明确 `RL/env/actor_observation.py` 唯一负责 36/144/
     160 维组帧，`SensorReader` 只负责 runtime32 采集、校验、噪声和裁剪。boundary
     权威级别更高，必须将其措辞改成后一种唯一职责，否则 S-P1A 有两个合法 owner。
  3. `MEDIUM`，“直接复用”术语会掩盖共享 owner 的前置兼容改造。现有
     `sensors.py` 没有 `read_runtime32()`，`torque.py` 没有独立 action scale，
     `train.py` 没有监督 Actor 映射。应统一称为“由共享 owner 兼容改造并独立 PASS
     后复用”；路线 B 始终只能消费，不能把缺失能力补在私有 adapter 中。
  4. `MEDIUM`，boundary 第 4.3 节已正确规定 Kinesis 兼容重新导出只能由 Kinesis
     分支完成，但第 5.2 节又简写成“抽取到中立目录并从旧路径重新导出”。应在后者
     重复限定：路线 A 只新增中立实现和只读等价测试，旧路径重新导出是未来 Kinesis
     owner 的独立阶段。
- 补充修复门：
  1. 将共享依赖规则改成分层、可执行的依赖约束，显式允许现有数据层的 pandas 和
     训练层的 Stable-Baselines3，同时继续禁止后端依赖进入共享层。
  2. 在 boundary 中把 `SensorReader` 职责固定为 runtime32 采集；36/144/160 组帧只
     归 `actor_observation.py`。
  3. 把 sensors/torque/train 的分类改成“共享 owner 兼容改造后复用”，并在抽取后
     复用条目明确 Kinesis 重新导出的唯一 owner。
- 独立证据：
  - `nl -ba` 定位 boundary 第 4.1、4.3、5.1 和 5.2 节以及 shared plan 的
    `actor_observation.py` 唯一职责；
  - 源码读取确认 `preprocess_tcn.py` import pandas，`train.py` import SB3，
    `sensors.py` 仅有 36 维 `read()`，`torque.py` 仍用 hard limit 直接缩放；
  - `rg` 确认 `SensorReader`、`TorqueActuator` 和 `RL.train` 已有 Kinesis/demo/audit
    调用者，因此共享兼容改造必须单独回归，不能由路线 B 顺带修改；
  - 追加前四份设计文档哈希保持稳定。
- 结论：维持 `P0-006-SCIENCE-REVIEW-002` 的 `REWORK`。以上边界文字与前述公式、
  指标和 metadata 修复应在同一文档返工中收口，再由新 reviewer 全文复审。
- 实际修改：仅追加本补充记录；未修改设计文档、Python、第三方、资产、模型、
  checkpoint 或输出。

### B-P2-EDIT-001 生成 22 肌肉加四髋膝理想力矩模型

- 时间：2026-08-03
- 阶段：B-P2
- 状态：编辑和编辑者自检完成，独立 reviewer 待定；不得据此进入 B-P3
- 编辑 agent：`/root/b_p2_model_editor`
- owner 边界：只新增 `RL/env/myoassist/**`、`RL/assets/myoassist/**`，并追加本日志；
  未修改共享层、Kinesis、`third_party`、计划文档、checkpoint 或其他脏文件
- 起点事实：
  - 本次收到的启动门为 `P0-006-REVIEW-001: PASS`；
  - 编辑开始时日志哈希：
    `467b6f0f5bf029a22f104f29bb8e2382267df3641e7b4247ba81b18b43a7fe83`；
  - 追加本记录前日志已被并行分支更新为
    `215233889f77f5069c08864c321441146db8f05b502cecaf82289e3dbc07486e`，并出现
    `P0-006-SCIENCE-REVIEW-002/003: REWORK`；该并发阻塞已通知主 agent，本记录不把
    B-P2 标为 `PASS`，也不覆盖任何 P0 历史；
  - 上游源 XML 哈希：
    `15449322a8e91295fa48bf5d85fe809aee98c572c9922baeafc39ff0cd7fc6cb`；
  - 以下五个路线 B 文件在本步骤前均为 `MISSING`
- 新增文件及当前哈希：
  - `RL/env/myoassist/__init__.py`：
    `5c081284c0a5389c5baa38ca23acd9a22a28ecf771312bc72ea92b4ed805b8ba`
  - `RL/env/myoassist/model_builder.py`：
    `8d3d672450a55fc54ce39c598401c359cdd25831dc6bd5970ea814a6483ac688`
  - `RL/env/myoassist/tests/__init__.py`：
    `2f84ec016fa57bb1c6f8728a18c608a7827d748a50a8816f7c7795a7431772c2`
  - `RL/env/myoassist/tests/test_model_builder.py`：
    `4f9f33b332b0f209c313d1da81f3d9352a8e5d2e6dee36d9303854386f8968b7`
  - `RL/assets/myoassist/myoLeg22_2D_GEXO.xml`：
    `0fda496cf4fbef646f884d3b4a43ccce80ff63932d9f6f2d87762d83aa4581a1`
- 数据流和模型改动：
  1. 标准库 `ElementTree` 解析上游 XML，并先验证其执行器仍严格为 22 路肌肉和
     `Exo_R/Exo_L` 两路旧踝执行器；结构变化时直接失败；
  2. 前 22 路肌肉定义和顺序原样保留，移除两路旧踝执行器；
  3. 移除旧 tutorial 中六个踝部 cuff/actuator/foot attachment 刚体及对应 mesh，
     防止理想力矩基线仍携带旧硬件质量；
  4. 后四路固定为 `[gexo_left_hip, gexo_left_knee, gexo_right_hip,
     gexo_right_knee]`，分别驱动 `[hip_flexion_l, knee_angle_l,
     hip_flexion_r, knee_angle_r]`；
  5. 髋 gear 为 `+1`；MyoAssist 膝坐标屈曲为负，故膝 gear 为 `-1`，对外协议仍为
     膝屈曲正；四路硬 `ctrlrange` 均为 `[-17, 17] Nm`；
  6. mesh 和 include 路径重写为相对生成 XML 的工作空间路径，没有写死
     `/home/lenovo`；没有加入 URDF、绑带/连杆质量、IMU 或域随机化
- 命令和结果：
  - `PYTHONDONTWRITEBYTECODE=1 .../envs/hackthon/bin/python -m
    RL.env.myoassist.model_builder`：退出码 0；重复生成前后资产哈希均为
    `0fda496c...581a1`，生成确定；
  - `PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp/matplotlib-gexo
    .../envs/hackthon/bin/python -m unittest -v
    RL.env.myoassist.tests.test_model_builder`：7 项通过，耗时 0.319 秒；
  - 单测覆盖：跨目录 XML 编译、`nq=53/nv=53/nu=26/na=22`、肌肉定义/顺序、
    四执行器名称/关节/范围/gear、旧踝和旧硬件质量缺失、资源路径相对且存在、零力矩
    严格为零，以及每路正负 `1 Nm` 的广义力、qacc 和单步 qvel 方向；
  - 从 `/tmp` 以 `PYTHONPATH` 加载默认资产：退出码 0，得到
    `nq=53, nv=53, nu=26, na=22, nbody=37`；
  - `git diff --check -- RL/env/myoassist RL/assets/myoassist`：退出码 0；
  - 上游 XML 收尾哈希仍为 `15449322...fc6cb`，无 `__pycache__` 生成
- 测试过程中修正：最初把 MuJoCo 3.3 的 `actuator_moment` 当作致密二维数组；确认其
  实际通过 `moment_rowadr/moment_rownnz/moment_colind` 暴露稀疏行后，仅修正测试
  辅助函数，最终以外骨骼四行的稀疏 moment 和 actuator force 独立重建广义力；模型
  实现未因此改变
- 局限：本步骤只证明理想执行器的静态/局部动力学契约，不证明 22 肌肉策略在移除旧
  踝硬件质量后仍能稳定行走；repeated reset、冻结人体稳定性和 50 Hz 长 rollout
  属于 B-P3，且当前并发 P0 `REWORK` 解除前不得推进
- 回退：删除上述五个新增文件即可；不得改写本记录
- 下一步：先由未参与编辑的 agent 独立 review 和复跑单测；同时由主 agent 处理最新
  P0 科学 review 阻塞。只有两者均形成有效 `PASS` 后才可开始 B-P3

### B-P2-FIX-002 用冻结人体 checkpoint 的显式兼容惯量替代删除质量

- 时间：2026-08-03
- 阶段：B-P2
- 状态：实现和回归通过，等待最终整体 review
- 编辑 agent：`root`
- 原因：`B-P2-EDIT-001` 删除了旧 tutorial 每腿 `0.09 + 0.325 + 0.75 =
  1.165 kg` 的硬件惯量。严格同 reset、同冻结人体策略、同零踝力矩 A/B 表明：
  - 删除惯量的派生模型在 0.8 m/s 仅运行 109 步，最低骨盆高度 0.681 m；
  - 原模型关闭两路旧踝力矩后走满 1000 步，平均速度 0.973 m/s，最低骨盆高度
    0.856 m；
  - 因此低速失败由 checkpoint 的动力学分布变化造成，不是 reset 漂移。
- 修改：
  - 旧 `Exo_R/Exo_L` 仍彻底移除；
  - 六个旧硬件 mesh 和 geom 仍彻底移除；
  - 六个无关节刚体仅保留其显式 inertial，并重命名为 `teacher_inertia_*`；
  - 这些兼容惯量不可控制、不可发力、不可见，不是 G-Exo URDF，后续必须由真实
    G-Exo URDF 质量和惯量替换后重新适配/微调人体策略。
- 当前文件哈希：
  - `model_builder.py`：`0923482c28fbf8029aee60caa357fe262d501ac1d59dc4550a19abd865e33ce1`
  - `test_model_builder.py`：`1fd7167a98172cbc0345361359e95f67b4d3060cd9c33d936a3465a93d366adb`
  - 生成 XML：`b5aac395c273c69aaaa14ff17f8479bd35b57b932dd6d3c1d8a785bf9fd353c6`
- 验证：B-P2 七项模型测试与 B-P3 两项 runtime 测试合计 9/9 PASS；四执行器顺序、
  gear、`[-17,17] Nm` 和正负脉冲契约不变
- 证据边界：该兼容层只保证当前 released teacher 的可用性，不证明其质量等于未来
  实机；正式 URDF 接入时必须删除 teacher inertia，禁止重复计入质量

### B-P3-EDIT-001 确定性 50 Hz 人体 runtime 与冻结 22 肌肉策略

- 时间：2026-08-03
- 阶段：B-P3
- 状态：实现和正式回归通过，等待最终整体 review
- 编辑 agent：`root`
- 新增文件和哈希：
  - `RL/env/myoassist/human_runtime.py`：
    `ce775fc9d5e82c8c76437e1fd2eee7d6c1f242f3e44f325ed97756e13131d327`
  - `RL/env/myoassist/policy_transfer.py`：
    `738551112b3570fbc9bdbcd01e9bb63b895695156258bf626baf84ffa84b7c5d`
  - `RL/env/myoassist/tests/test_human_runtime.py`：
    `01b4cedd348cd4e4304be775a753732b82fac955b5a6c007666a98dba77b0799`
  - `RL/runners/check_myoassist_human.py`：
    `4249665f696038ba47f88cdd3f5c21b3556cb3414010e73fbe588e82226cc20b`
  - 正式报告：`435a1323ad38edc8dd3973797bf55bf217ebf9d92e23e42550ba8828737cb698`
- 数据流：`native44 -> released PPO deterministic predict -> 前22维 muscle action ->
  四维 zero exo -> 26维 MyoAssist action -> 1200 Hz physics / 50 Hz control`
- 修复内容：
  1. reset 每次从 `init_qpos/init_qvel.copy()` 和指定 reference frame 重建完整状态；
  2. 使用 `self.np_random` 统一 reference、速度模式、phase、period 和 step speed RNG；
  3. 修复上游随机速度位置参数错位，但只在 G-Exo 本地子类覆盖；
  4. gait reference 私有复制后重采样到 50 Hz，循环读取，不修改第三方数据；
  5. checkpoint 只加载一次并冻结，强制验证 44 维 observation、24 维旧 action 和
     SHA256 `6bf9df3e...da1381`，实际只取前 22 维人体肌肉动作；
  6. 四个新髋膝动作在本阶段严格为零。
- 正式验收：
  - 同实例、相同 seed/reference/speed 连续 10 次 reset：最大 qpos、qvel、observation
    误差均为 0，time 恢复为 0；
  - 0.8 m/s × seeds 0/1/2：均 1000/1000 步成功，平均速度 0.978 m/s，最低骨盆
    高度 0.858 m；
  - 1.25 m/s × seeds 0/1/2：均 1000/1000 步成功，平均速度 1.348 m/s，最低骨盆
    高度 0.842 m；
  - 9 项单元/契约测试全部通过；`git diff --check` 通过。
- 局限：固定 reference index 和 deterministic teacher 下不同 seed 结果相同属于预期；
  随机 episode 分布、外骨骼动作敏感性、肌肉指标与 PPO 多进程在后续阶段验收
- 下一步：实现 MyoAssist 专属 sensor/muscle adapter 和组合 Gymnasium 环境；共享
  runtime32/TCN/metrics 未 `PASS` 前只做后端原始量测试，不复制共享实现
### B-P0-DECISION-007 正式人体基座改为 BASELINE 迁移适配

- 时间：2026-08-03
- 阶段：B-P0/B-P3 设计纠偏
- 状态：设计决定已落文档，代码实施进行中
- owner：路线 B；消费者为后续 B-P2--B-P8
- 触发证据：在相同 reset、50 Hz、严格零旧踝力矩和同一 released checkpoint 下，
  保留 tutorial 训练惯量的模型于 0.8 m/s 走满 1000 步；删除每腿 1.165 kg、总计
  2.33 kg 旧踝硬件惯量后约 109 步跌倒。1.25 m/s 删除惯量模型偶然稳定不能推翻
  低速反例。
- 科学结论：22 肌肉人体模型本身不需要踝部外骨骼惯量；依赖该惯量的是 released
  policy checkpoint。将旧惯量隐藏后继续训练只能保持 checkpoint 兼容，不能代表
  无旧硬件人体、四髋膝外骨骼或最终 sim2real。
- 正式决定：
  1. 从 `myoLeg22_2D_BASELINE.xml` 生成正式 22 肌肉 + 四髋膝理想力矩模型；
  2. tutorial 派生的 teacher-compatible 模型只用于 checkpoint/reset/frequency 诊断；
  3. 从 released checkpoint 显式迁移 44-to-22 human actor 权重；
  4. 在正式模型上以严格零四髋膝力矩短程微调人体策略，验收后冻结；
  5. 外骨骼 PPO 阶段不得更新人体策略，且当前不接 URDF、不做域随机化。
- 同步收口：MyoAssist MVP 的 22 肌肉和四关节首版均等权；effort 权重
  `alpha=0.6`；gross baseline 使用训练 split 零助力 rollout 的速度条件稳健中位数，
  scale 为 `max(MAD, 0.05 * median, 1e-6)`，训练速度范围外拒绝外推；所有 baseline、
  reward/gate 参数、schema 和 SHA256 必须进入 metadata。
- 流程决定：按用户最新要求，B-P0--B-P7 连续迅捷开发，每步仍追加事实和测试证据；
  不再等待逐步骤独立 review。全部完成后由此前未参与编辑的新 agent 做 B-P8 全量
  review。遇到新的科学含义或协议问题仍立即报告用户。
- 修改文件：
  - `RL/MYOASSIST_GEXO_BOUNDARY.md`
  - `RL/MYOASSIST_GEXO_PPO_PLAN.md`
  - 仅追加本日志
- 文档修改后、追加本记录前哈希：
  - boundary：`809604c9e2f221469bc15a7bafc53f735ee1019ad82f544a754d692a662cafc7`
  - PPO plan：`e15daae6abe50114bbab1801ab37d4e26364ec12b777b13caa1259b0f1edb16f`
  - implementation log：`874bc166064bb2ee44d877c59d09652517d9986f27b1d3e4ce3be834b7f1a43b`
- 文档结构检查：boundary/PPO plan 的代码 fence 分别为 `6/6`，display math
  delimiter 分别为 `2/40`，均为偶数；旧“禁止微调”和逐步骤 review 硬门已无活跃
  命中。

### B-P4--B-P7-IMPLEMENTATION-008 训练前闭环、100k smoke 与统一评估

- 时间：2026-08-03
- 阶段：B-P4--B-P7
- 状态：实现、训练冒烟和回归完成；B-P8 全新 agent 整体 review 待执行
- owner 边界：MyoAssist 实现仅位于 `RL/env/myoassist/**`、
  `RL/assets/myoassist/**` 和 MyoAssist runners；共享层只消费既有 32/144/160、TCN、
  torque 与 physiology 协议。`RL/train.py` 只保留后端无关 `additional_callbacks`
  扩展，已删除其中的 MyoAssist 字段映射；未编辑 `RL/env/kinesis/**` 或第三方源码。
- 锁定数据流：
  `22-muscle frozen human + physical4 torque -> four motors/four virtual IMUs -> runtime32
  -> causal TCN50 -> four real 36-d frames (144) + feature16 -> Actor160 -> normalized4 ->
  shared torque safety -> four physical Nm -> MyoAssist`。
- 正式范围：二维平地；四执行器顺序 `[左髋、左膝、右髋、右膝]`；硬限矩
  `+/-17 Nm`，变化率 `50 Nm/s`，50 Hz；不接 URDF，不做域随机化；人体 Actor 与
  TCN 在 PPO 中冻结。
- B-P4/B-P5：
  1. `sensor_adapter.py` 从四目标关节和四个局部 gyro/accelerometer 形成统一 32 维；
  2. 共享 `SensorReader`、`ActorObservationBuilder` 和 `FrozenTCNRuntime` 形成严格
     160 维 Actor observation；TCN 只读取当前和过去 50 帧；
  3. calibration 交叉验证人体、物理模型和 TCN SHA256，速度范围固定为
     `[0.8,1.0,1.25] m/s`。
- B-P6：
  1. `muscle_adapter.py` 输出后端中立 `MuscleSnapshot`，包含 22 肌肉 activation、
     activation bounds、force affine representation、四关节 moment arm、target mask、
     validity 与模型哈希；
  2. 零助力 baseline 共 4500 帧，使用三档速度、seeds 0/1/2、50 步 preroll 和 50
     步因果速度均值；关节安全包络来自零助力观测分位数而非 XML 全范围；
  3. effort 为 `0.6 * activation_z_saving + 0.4 * human_torque_z_saving`；gross 只作
     非抵消负载恶化铰链；正 saving 受速度/站立 gate，负 saving 始终保留；
  4. 电机正则包含归一化力矩、真实二阶差分和超过 20 W 免费区间的正功；所有分项
     同时写入 `reward_terms`、`reward_metrics` 和 TensorBoard；
  5. 修复 baseline 端点浮点误差：允许机器精度容差并钳回 `[0.8,1.25]`，实际
     `0.7999999999999998` 不再被误判为外推，真实 `0.99 < 1.0` 测试样例仍拒绝。
- B-P7 协议：
  1. `gexo_myoassist_ppo_protocol_v3` 锁定全部 artifact hash、Observation、动作安全、
     reward、PPO 参数、worker、seed、评估条件和
     `speed_schedule=uniform_per_episode_v1`；
  2. fresh run 拒绝覆盖已有 config，resume 必须匹配不可变协议；训练结束无论成功或
     异常都写冻结人体/TCN训练前后哈希；
  3. 8 worker 内部 PyTorch thread 固定为 1，实测约 367--434 fps，避免每个 worker
     争用全部 CPU；
  4. evaluator 在同 seed、速度、reference index 和 horizon 下运行
     `baseline/oracle/policy`，不完整或不等长 pair 的 saving 为 null；oracle 是当前
     状态净肌肉力矩方向的动作敏感性诊断，不是生理真值或上界。
- 权威 artifact SHA256：
  - 物理模型：`7127a1cb67a64782410659f73dfd752b5b490c3d8c3a4f0e2f615e5af6c331fe`；
  - teacher-compatible 诊断模型：
    `f75e773702ef7434c359f835ddde43e72a77f400803d90048ae955fbac5c9f1d`；
  - adapted frozen human：
    `457ff4e33b62e9a1ff09e2b2aa821719fe743fc1f70234d7b4b53fb4bc01502c`；
  - baseline JSON：
    `4fc12a09d44107e02de4a39ea614c060dd50abbda3b98d8efafe93a82b86e87e`；
  - TCN calibration：
    `50a6dbf6c41b26f50245a31675ac4e2f169f64fe1f751d8b9c4e0c61776d335c`；
  - frozen TCN：
    `fc6f552a00b17c5f98a4ee03ade4862eda1ce2f9724b25b3fe41739f1e8beb98`。
- 100k smoke：
  - 输出：`RL/outputs/myoassist_exo_ppo_100k_smoke_v5/`；
  - 8 worker、seed 42、500 步 episode、`n_steps=256`、`batch_size=512`、
    `n_epochs=5`、`learning_rate=3e-4`、`log_std_init=-1`；
  - 实际完成 100352 步，约 272 秒；四个 25k checkpoint、best/final model、Eval、
    TensorBoard 和完整性文件齐全；最终 model SHA256 为
    `40b192b781d71b4b5aa7ab29097e2af6bb7d3de3203e96d34b80c0f074cad209`；
  - TensorBoard 共 82 个 scalar tags；必需的 total/各 reward 项、存活、速度、骨盆
    高度/俯仰、关节越界、激活、人体力矩、gross、四电机力矩、二阶差分和功率均存在；
  - `frozen_artifact_integrity.json` 为 `unchanged=true`；单环境 100 步全幅随机动作
    smoke 为 finite、无崩溃且能正常结束/reset。
- resume smoke：从 100k final model 在独立输出目录续训 4096 步，计数从 100352
  延续到 104448；协议哈希均为
  `8c1243339df0c5c185a7ffb9f1b26fa2ed5cfbfb576a44b85f622e19490b5e75`，冻结哈希不变；
  输出 `RL/outputs/myoassist_exo_ppo_resume_smoke_v5/`。
- 正式统一配对报告：
  `RL/outputs/myoassist_exo_ppo_100k_smoke_v5/paired_evaluation.json`，trace 为同目录
  `paired_evaluation.npz`；3 个速度 x 3 seeds x 1 reference，共 9 pair。
  - baseline 与 oracle 在全部条件均走满 500 步；
  - policy 在 1.0/1.25 m/s 的 6 pair 走满，完整 pair 均值为 activation `+2.94%`、
    human torque `+13.50%`、gross `+3.89%` saving；
  - policy 在 0.8 m/s 的 3 pair 均于 157 步跌倒，故只有 6/9 valid pairs，正式
    `protocol_pass=false`、`effectiveness_pass=false`；上述 6-pair 均值不得冒充全域
    有效性；
  - 结论仅为训练/记录/恢复/评估流水线可用，100k T0 策略尚未通过全速度门。
- 全量回归：共享 `RL/tests` 44/44、MyoAssist env tests 47/47、runner tests 7/7，
  合计 98/98 PASS；`py_compile` 通过。第三方 BASELINE/TUTORIAL 源 XML 哈希分别为
  `ffe9976762eb5b591d85a0bc0d33f26659a03f9b06be574dcf2d9dec18e3aa6b` 和
  `15449322a8e91295fa48bf5d85fe809aee98c572c9922baeafc39ff0cd7fc6cb`，后者与编辑前
  日志一致；本阶段没有修改第三方源码。
- 已知限制和下一步：不同 seed 在 canonical reference 0、确定性人体策略下产生相同
  trajectory，当前 seed 组主要验证复现而非随机鲁棒性。B-P8 必须如实区分工程
  readiness 与策略 effectiveness；若 B-P8 通过，才进入 T1，并优先处理 0.8 m/s
  存活，禁止放宽 gate 或删除失败样本换取 PASS。

### B-P7-COMPAT-ENTRY-009 增加计划规定的正式 runner 兼容入口

- 时间：2026-08-03
- 阶段：B-P7
- 状态：薄入口实现与最小测试 PASS；真实端到端验收仍由 root 完成
- 编辑 agent：`/root/canonical_entry_docs`
- owner 与消费者：两个入口和测试归路线 B；命令行用户消费正式 `gexo` 命名；实际
  PPO 与配对评估逻辑仍由既有 `*_myoassist_exo.py` 唯一拥有
- 目标：让计划规定的 `train_myoassist_gexo.py` 和
  `evaluate_myoassist_gexo.py` 成为可执行入口，同时不复制任何业务逻辑
- 非目标：不修改现有训练/评估实现、共享基础模块、计划正文、Kinesis、第三方、
  baseline/TCN 生成逻辑或任何物理协议
- 修改前数据流：正式计划入口名不存在，用户只能直接调用既有 `*_myoassist_exo.py`
- 修改后数据流：`python -m RL.runners.*_myoassist_gexo ->` 直接导入并调用对应既有
  `main()`；CLI 参数解析、训练、评估和输出仍只有一份实现
- 实际修改文件及 SHA256：
  - `RL/runners/train_myoassist_gexo.py`：
    `944923898b1819543562874089351eab8f8d04c75546164490b766460f631f2d`；
  - `RL/runners/evaluate_myoassist_gexo.py`：
    `4297d14472011ce319eb82c92a7dd599a13872c7c17bcfb384b47f5a8ea3b2ee`；
  - `RL/runners/tests/test_myoassist_entrypoints.py`：
    `c131aedc329303da58a02048fb4d1c04785c3e8307e6187eb4a847a6e203e6f7`；
  - 仅向本日志追加本记录
- 明确未修改的既有实现及 SHA256：
  - `RL/runners/train_myoassist_exo.py`：
    `ce6de0fcfd3bbca45f509e7b44050a32a05fc0e5195276fc670074c8f89e3fed`；
  - `RL/runners/evaluate_myoassist_exo.py`：
    `1eb61864438c22d8a85c4240b701f393f66d8eb6b33741a691e63711f2ecd5d7`
- 本轮已知正式输入产物：
  - baseline v2 JSON `RL/assets/myoassist/zero_assist_baseline.json`：
    `a538d356b8cea5edc9f1a02cb97a7104556573edae5517391b475d84e6018b52`；
  - baseline trace NPZ `RL/assets/myoassist/zero_assist_baseline.npz`：
    `f6ab19fc6f63a54780ed1e602748e2e59c1e0275ab1dba5af72e3ff7bdd58f88`；
  - TCN calibration `RL/assets/tcn/myoassist_phase12_calibration.json`：
    `50a6dbf6c41b26f50245a31675ac4e2f169f64fe1f751d8b9c4e0c61776d335c`
- 自检命令与结果：
  - `python -m unittest -v RL.runners.tests.test_myoassist_entrypoints`：2/2 PASS；
    对两个正式入口分别断言其 `main` 与既有实现是同一函数对象；
  - `python -m RL.runners.train_myoassist_gexo --help`：退出码 0，完整训练参数可见；
  - `python -m RL.runners.evaluate_myoassist_gexo --help`：退出码 0，完整评估参数可见；
  - `python -m py_compile <两个入口和测试>`：退出码 0；生成的临时 bytecode 已清理；
  - `git diff --check -- <两个入口和测试>`：退出码 0
- 测试环境：`/home/lenovo/anaconda3/envs/hackthon/bin/python`，
  `PYTHONPATH=$PWD/G-Exo:$PWD/third_party/myoassist`；无显示器时 GLFW 仅报告
  `Failed to open display :1` 警告，不影响导入和 CLI 验收
- 兼容性影响：旧入口继续有效；正式入口不维护参数副本，不会与既有实现漂移
- 验证边界：本记录只证明入口委托、语法和当前产物身份；不证明环境长 rollout、
  1/8 worker PPO、保存恢复、TensorBoard、冻结哈希或配对生理有效性。上述真实
  端到端验证与最终 B-P8 判定仍由 root 完成
- 回退方法：删除两个薄入口和对应单测，并追加回退记录；不得改动旧实现

### B-P8-REWORK-010 baseline v3 漂移修复与快速 demo 收口

- 时间：2026-08-03
- 阶段：B-P8 首轮审查整改
- 状态：阻塞项已修复并补齐运行证据；第二个全新 agent 复审待执行
- 触发问题：首轮只读审查发现 `baseline.py` 已要求
  `gexo_myoassist_zero_assist_baseline_v3` 和逐速度 bin 的阈值数组，但正式 JSON 仍为
  `v2` 标量字段；真实环境加载会报 `speed_free_error_m_s must have shape (3,)`。此前
  100k/resume 配置也锁定旧 baseline SHA，因此不能作为当前代码的训练证据。
- 修复动作：不修改第三方或 Kinesis；使用正式 baseline collector、适配后冻结人体、
  三档速度 `0.8/1.0/1.25 m/s`、seeds `0/1/2`、reference 0、50 步 preroll 和每条件
  500 步，覆盖重建 4500 帧 baseline JSON/NPZ。
- 当前 baseline：
  - schema：`gexo_myoassist_zero_assist_baseline_v3`；
  - JSON SHA256：`bf87bab90bc2336e1f165c849b23e4ea2df101b622cd7e0eb40883e223a704a7`；
  - trace NPZ SHA256：`f6ab19fc6f63a54780ed1e602748e2e59c1e0275ab1dba5af72e3ff7bdd58f88`；
  - `speed_free_error_m_s` 和 `speed_transition_m_s` 均为 shape `(3,)`，实际
    `MyoAssistBaseline.load()` 与 `at_speed(1.0)` 通过。
- 当前协议 smoke：
  - 输出：`RL/outputs/myoassist_exo_ppo_current_protocol_smoke/`；
  - 8 worker、seed 42、500 步 episode，从 0 训练到 8192 步；
  - 4096/8192 checkpoint、best/final model、两次 Eval、TensorBoard 和冻结完整性
    文件齐全；final model SHA256 为
    `e42e2b1f1a68faee5a85fd0f80c75dc7e18da0e858caa961ef7df3f290c6b8ed`；
  - TensorBoard 有 82 个 scalar tags，step 范围 4096--8192，包含 rollout、PPO、
    reward、saving、人体和四电机指标；
  - 当前不可变协议 SHA256：
    `b07f4ed75247cfe51f02e790825a44b0c280bf414b15425318691c777dc8c477`。
- 当前协议 resume：
  - 输出：`RL/outputs/myoassist_exo_ppo_current_protocol_resume/`；
  - 从上述 8192 final model 续训 4096 步，checkpoint 计数为 12288；
  - 协议 SHA 与 fresh run 完全一致，冻结人体/TCN before/after 哈希一致；
  - final model SHA256：
    `5a466bee5c81facec1556cb86b79f31bf22f45e74d44a4a112c9737714638715`。
- 快速 demo 决定：不重跑长训；固定二维平地 `1.0 m/s`，使用历史 100k candidate
  `40b192b781d71b4b5aa7ab29097e2af6bb7d3de3203e96d34b80c0f074cad209`，在当前
  baseline v3、当前物理环境和当前 evaluator 下重新做 baseline/policy 配对。
- 快速 demo 结果：`3/3` pair 均走满 500 步，`protocol_pass=true`、
  `effectiveness_pass=true`；activation-squared saving `3.4858%`、人体四关节力矩
  cost saving `14.7813%`、gross 非抵消肌肉负载 saving `4.7497%`。报告/trace：
  - `RL/outputs/myoassist_quick_demo_1ms/paired_evaluation.json`，SHA256
    `f6fb0c98e7a285d0a18a8cacdc179659430dd0292e6ab11dc6f9de64e457f097`；
  - `RL/outputs/myoassist_quick_demo_1ms/paired_evaluation.npz`，SHA256
    `0df04640c860f150c5ccbdd12235cafacf2f7538cfac028f5effe56c44f25892`。
- 解释边界：历史 100k candidate 使用 baseline v2 训练，只能作为固定工况演示策略；
  当前 baseline v3 smoke 证明最新代码可训练/恢复，但 8192 步不用于证明性能。固定
  `1.0 m/s` 成功不能覆盖已知 `0.8 m/s` 跌倒，也不能外推真人省力比例。
- 回归：共享 tests `44/44`、MyoAssist env tests `48/48`、runner tests `9/9`，合计
  `101/101 PASS`；headless GLFW 警告不影响测试或训练。
- 快速 sim2real 后续只保留：TCN + Actor 导出、离线输出一致性、50 Hz 推理、高频
  电机安全环、低力矩缩放、watchdog/急停/支撑。URDF、域随机化、楼梯和长时调参
  推迟，不得直接把仿真 `17 Nm` 上限用于真人。

### B-P8-FINAL-AUDIT-011 全新 agent 最终只读复审

- 时间：2026-08-03
- 阶段：B-P8
- 审查 agent：`/root/final_b_p8_reaudit`，未参与本路线实现与整改
- 判定：`PASS`，严格限于“训练就绪 + 确定性二维平地 `1.0 m/s` 仿真/数据 demo”；
  不包含全速度泛化、随机鲁棒性、URDF、域随机化或 sim2real 完成。
- 独立核验：
  1. baseline v3 JSON/NPZ 可加载，真实 `GexoMyoAssistEnv` reset/zero-step 返回 finite
     160 维 Observation；
  2. fresh/resume 配置的协议 SHA 均为
     `b07f4ed75247cfe51f02e790825a44b0c280bf414b15425318691c777dc8c477`，artifact
     身份匹配，SB3 计数为 8192 -> 12288，冻结人体/TCN哈希不变；
  3. checkpoint、TensorBoard、Eval NPZ 和 integrity 文件一致；
  4. 从 quick-demo 原始 trace 独立复算 activation-squared、human four-joint torque
     cost、gross non-cancelling load saving，分别精确得到 `3.4858%`、`14.7813%`、
     `4.7497%`；mean absolute exo torque 为 `6.4337 Nm`，10 秒正/负功分别为
     `+322.21 J/-287.80 J`；
  5. 独立重跑共享 `44`、MyoAssist env `48`、runner `9` 项测试，合计
     `101/101 PASS`；未发现 MyoAssist 路线导入 Kinesis、共享层后端污染或本轮第三方
     源码写入。
- 保留风险：
  1. canonical seeds 0/1/2 的 baseline 与 policy trajectory byte-identical，3/3 只证明
     确定性重复性，不是独立 seed 鲁棒性；
  2. 实机安全尚未验收；策略仿真包络为 `+/-17 Nm` 且平均绝对力矩 `6.43 Nm`，必须
     先完成模型导出一致性、真实传感器标定、延迟、watchdog、急停和支撑验证，人体
     首测缩放到约 `1--2 Nm`；
  3. protocol config 未显式记录从 `RL/train.py` 继承的 `clip_range`、`ent_coef`、
     `vf_coef`、`max_grad_norm`、`normalize_advantage`；当前 archive 可复现本次证据，
     但未来正式长训前应补齐；
  4. baseline v3 当前只完成 8192 + 4096 smoke；性能 demo 来自历史 baseline v2
     100k candidate 在 v3 环境下的重新评估，证明当前路线和固定工况 demo，不证明
     v3 已收敛。
- 收口决定：本轮目标完成。下一轮只做快速 sim2real 最短路径，不继续奖励调参或
  多速度长训；任何实机输出都必须先经过 `1--2 Nm` 降额安全门。

### B-P8-FOLLOWUP-012 逐速度 baseline、当前协议 100k 与全域反例

- 时间：2026-08-03
- 阶段：B-P8 后续权威证据更新
- 状态：工程验收 PASS；100k 策略全速度验收 FAIL
- 修改边界：只修改 `G-Exo/RL/env/myoassist/**`、MyoAssist runner、正式产物与本项目
  文档；没有修改 Kinesis 或 `third_party/myoassist` 源码，没有接 URDF，没有开启域
  随机化。
- 触发问题：旧 baseline 用单一全局速度误差阈值；真实零助力 rollout 的三档 P95
  速度误差约为 `0.3009/0.1454/0.0750 m/s`，全局值会给 `0.8 m/s` 零动作施加约
  `-0.52/step` 的错误惩罚。
- 修改后数据流：`baseline collector -> 每速度 bin 的 free/transition 阈值 ->
  BaselineAtSpeed 线性插值 -> reward/evaluator 使用同一速度条件协议`。超出标定速度
  范围仍直接拒绝。
- 修改文件及 SHA256：
  - `RL/env/myoassist/baseline.py`：
    `9f53e127b4c0736645e735e0ae927c34da85aa9398f9aa1234257e8cdffd24fd`；
  - `RL/env/myoassist/reward.py`：
    `8adc613d6eedd69255e4dfa986d87316ae635a9587714092cc297be73a57d85a`；
  - `RL/runners/collect_myoassist_baseline.py`：
    `b89a5400538b1566fe65c1c5775c0a02400e8d8900e5c5e0111b0d3c11d979cb`；
  - `RL/runners/evaluate_myoassist_exo.py`：
    `af95bb5735779c8d193112bb5e2880c08e7c85783d081d822b85c9c2ee6a8605`；
  - `RL/env/myoassist/tests/test_baseline_reward.py`：
    `9dc1d2d57ce44b600215c579def36812d45099c40c7e30f1d57e6787e642455a`。
- 当前 baseline v3：JSON
  `bf87bab90bc2336e1f165c849b23e4ea2df101b622cd7e0eb40883e223a704a7`，NPZ
  `f6ab19fc6f63a54780ed1e602748e2e59c1e0275ab1dba5af72e3ff7bdd58f88`；
  4500 帧、9/9 完整 episode。
- 正式模型边界复核：模型 SHA256
  `7127a1cb67a64782410659f73dfd752b5b490c3d8c3a4f0e2f615e5af6c331fe`，
  `nu=26`，后四执行器是四髋膝 G-Exo；不存在旧踝外骨骼 actuator 或兼容惯性。人体
  解剖踝关节和肌肉保留。
- 当前协议 100k：输出 `RL/outputs/myoassist_gexo_ppo_100k_smoke_v3/`，实际步数
  `100352`，final SHA256
  `bbe30959902babf7dbf9dcced69cad99c8c9da21283487250070e75ab52af6fe`，协议 SHA256
  `199f16b039cbc0329421e8ea498d0b4a1b8d52cffb427d4b28b35e48312f3185`；82 个 TB
  scalar tags 齐全，冻结人体/TCN完整性为 `unchanged=true`。
- 保存/加载与 resume：确定性动作 round-trip 最大误差为 0；resume 输出
  `RL/outputs/myoassist_gexo_ppo_resume_smoke_v3_round2/`，计数 `100352 -> 104448`，
  final SHA256
  `65aab2a39cdb40bf4a8c312d09e95a70fd4298499a96b81c04df99a9fd6567bf`，协议和冻结
  文件哈希保持一致。
- 严格配对：报告 JSON SHA256
  `3696750eea0cfa3ad98a66977a07b89bebdb783215fbb3f32b7a81440a634f9e`，trace NPZ
  SHA256 `4a580d19235ee065123f906637a7ecedec6dc2170689f45c08820be6179e1b4e`。
  `1.0/1.25 m/s` 的 6 个完整 pair 平均 activation/human torque/gross saving 为
  `3.31%/17.35%/5.35%`；`0.8 m/s` 三个 pair 均在第 175 步因骨盆高度终止，故
  `6/9 valid`、`protocol_pass=false`、`effectiveness_pass=false`。不得把有效 pair
  均值冒充全域有效性。
- 回归：标准库 `unittest` 运行共享 `44/44`、MyoAssist `48/48`、runner `9/9`，合计
  `101/101 PASS`；`compileall` 与 `git diff --check` PASS。`pytest` 未安装，因此未把
  缺少测试运行器误记为代码失败。
- 第三方只读证据：BASELINE/TUTORIAL XML SHA256 仍分别为
  `ffe9976762eb5b591d85a0bc0d33f26659a03f9b06be574dcf2d9dec18e3aa6b` 和
  `15449322a8e91295fa48bf5d85fe809aee98c572c9922baeafc39ff0cd7fc6cb`。
- 决定：基础设施允许进入 T1；当前策略不允许标记为全速度有效。T1 必须多 PPO seed、
  每 250k 配对评估，并优先解决低速存活，不得仅延长同一失败 run 或放宽验收门。

### B-P8-FINAL-REVIEW-013 当前协议全新 agent 只读总审查

- 时间：2026-08-03
- 审查 agent：`/root/final_myoassist_v3_review`，此前未参与实现
- 审查方式：只读检查源码、XML、产物、config、TensorBoard 和配对 trace；独立重算
  baseline 与配对统计并重跑测试；未修改文件，未启动训练。
- 判定：`PASS`，范围为四髋膝理想力矩路线的工程闭环、当前协议训练/恢复能力和进入
  T1 的基础设施资格；明确不包含当前 100k 策略全速度有效性、独立随机鲁棒性、URDF、
  域随机化或 sim2real。
- 独立物理核验：正式 XML 编译为 `nu=26/na=22`，后四路严格为左髋、左膝、右髋、
  右膝；人体解剖踝保留，旧踝外骨骼 actuator、legacy body、`teacher_inertia_*` 和
  URDF 均不存在；正式模型 body/inertial 与 BASELINE 源逐项一致。
- 独立运行时核验：1200 Hz 物理、24 子步、50 Hz 控制；reset 后 TCN 50 帧、Actor
  历史 4 帧、Observation `(160,)`、action `(4,)`；人体和 TCN 均冻结。
- 独立资产与统计核验：baseline v3 的 4500 帧和逐速度统计与 NPZ 完全一致；100k
  实际 `100352` 步且产物齐全；resume 连续到 `104448`；配对 trace 重算仍为
  `6/9 valid`，中高速 `3.31%/17.35%/5.35%` saving，低速三次 175 步终止，总协议和
  有效性均为 false。
- 独立边界核验：`third_party/myoassist` 与 `third_party/Kinesis` 聚合 hash 与开工
  基线相同；MyoAssist 路线无 Kinesis import；回归 `101/101 PASS`。
- 两个 LOW、非阻塞加固项：
  1. 新 fresh run 的不可变协议应显式补齐从共享 `train.py` 继承的五个 PPO 默认项；
  2. T1 自动选模前 evaluator 应默认校验 policy 相邻 run config，跨协议只允许显式
     override。
  当前 checkpoint 自身保存实际 PPO 值，当前报告的全部路径/hash/config 已人工交叉
  验证，因此两项不影响本轮 PASS 或统计结论；它们已进入计划第 13.5 节。
