# build.md — gexo_web_agent 开发沉淀文档

> 本文档沉淀 `feature/web-agent` 分支从零构建本包的全部设计决策、模块契约与迭代指南。
> 目标读者：在此架构上继续迭代的开发者（包括未来的 Claude Code 会话）。
> 面向用户的启动/使用说明见 `README.md`；本文回答「为什么这样设计、改哪里、怎么验证」。

---

## 1. 任务背景与硬约束

| 项 | 值 |
|---|---|
| 目标设备 | K3 CoM260（16GB）；实机为 Bianbu 4.0.1、ROS 2 Humble overlay、Python 3.14 |
| LLM | 实机 `/v1/models`：`Qwen3.5-0.8B-Q4_0.gguf`，llama-server `127.0.0.1:9193/v1` |
| 开发机 | Windows（**无 rclpy**）——这是最重要的工程约束 |
| 控制 Topic | 真实控制器接口**未定型**，先按 `/g_exo/bridge` + `std_msgs/String` JSON 契约实现 |
| 用途 | 黑客松演示；优先级：安全 > 实时稳定 > 演示可靠 > 状态正确 > 可维护 > LLM/UI 打磨 |

产品契约（不可违反，来自项目 CLAUDE.md）：

- 两模式：`assist`（全局 assist_ratio 缩放已有控制器输出）/ `damping`（阻尼训练模式——**不叫**「阻抗模式」）
- 助力步长恰 `±0.1`，范围 `[0.3, 1.0]`，四关节统一（关节顺序 `left_hip, left_knee, right_hip, right_knee`）
- LLM 只允许 4 个意图：`query_status` / `set_mode` / `adjust_assist` / `document_qa`
- 模型输出永远不可直达：原始力矩/电流、CAN 帧、单关节、急停解除、控制/滤波/安全参数、shell
- 控制器确认前绝不报成功；超时即失败；不自动重试；LLM/Web 故障不得影响实时控制

---

## 2. 架构总览

```
浏览器 (static/ 原生 HTML/CSS/JS, WebSocket)
   │
FastAPI (api.py, create_app 工厂)
   │  /api/chat ──▶ IntentRouter (intent_router.py)
   │                   ├─ 规则快路径 (regex, <1ms)
   │                   ├─ LLM tools API (llm_client.py) → Pydantic 白名单复验
   │                   └─ document_qa → RagService (rag_service.py)
   │  /api/action ──▶ 同一入口（无 NL 解析）
   │                   │
   │            CommandManager (command_manager.py)
   │                   │  submit() 内调 SafetyGuard (safety_guard.py)
   │                   ▼
   │            RosBridgeAdapter (ros_bridge.py)
   │                   ├─ MockTransport ─ MockControllerCore（进程内）
   │                   └─ Ros2Transport ─ /g_exo/bridge（懒加载 rclpy）
   │
   └─ /ws ◀── WsHub ◀── StateCache (state_cache.py) ◀── state 消息
```

依赖方向（严格单向，上层不 import 下层实现细节）：

```
api.py ─▶ command_manager ─▶ safety_guard ─▶ schemas
   │            │                              ▲
   │            └─▶ ros_bridge ────────────────┤
   ├─▶ state_cache ────────────────────────────┤
   └─(可选注入)─ intent_router ─▶ llm_client / rag_service
main.py 负责对象图组装（唯一知道全部模块的地方）
```

关键原则：

1. **契约集中在 schemas.py**——LLM 输出、HTTP body、Topic 线格式全部经 Pydantic 模型，`extra="forbid"`（Action/API）或 `extra="allow"`（StateData，容忍真实控制器加字段）。
2. **ROS 细节只在 ros_bridge.py**——真实 Topic/消息格式定型后，只改这一个文件（及 config topic 键），Web/LLM/安全逻辑零改动。
3. **安全逻辑独立于提示词**——SafetyGuard 是无状态纯函数，按钮与 LLM 同一入口，无特权差别；Mock 控制器作为权威端再复验一遍（双层防御）。
4. **api.py 无 LLM import**——chat_handler 以 `Optional[Callable]` 注入，LLM 栈构建失败时 `/api/chat` 返回 503 降级话术，控制路径完全不受影响（`main._try_build_chat_handler`）。

---

## 3. 模块职责与关键实现点

| 模块 | 行数 | 职责 | 迭代时注意 |
|---|---|---|---|
| `schemas.py` | 275 | 三层契约：Action 白名单 / 线格式 / API 模型 | `AdjustAssistAction.delta` 校验 `abs(abs(v)-0.1)>1e-9` 即拒；`ActionEnvelope.parse_untrusted()` 是所有不可信输入的唯一入口 |
| `config.py` | 122 | pydantic-settings；`GEXO_` 前缀 + `__` 嵌套环境变量覆盖 YAML | 新配置键先加 config.py 的 Config 类，再加 default.yaml |
| `state_cache.py` | 51 | threading.Lock + 整体快照原子替换；monotonic 时钟判 stale | 读者永不见撕裂状态；不要在这里加业务逻辑 |
| `safety_guard.py` | 137 | 无状态纯函数 `check(action, state, *, state_stale, confirmed, cfg)` | **11 条检查有序，第一个失败即返回**（见 §5）；staleness 由调用方传入，guard 不读时钟（保持可测） |
| `command_manager.py` | 318 | 命令状态机 + request_id 关联 + 超时（见 §6） | `on_result` 在传输线程被调；terminal 状态先到先赢；`_inflight` asyncio.Lock 保证单命令在途 |
| `ros_bridge.py` | 239 | BridgeTransport 协议 + Mock/Ros2 双实现 + Adapter | rclpy import 在 `Ros2Transport.start()` 内（Windows 可 import 包）；`source == source_id` 的自发消息被过滤 |
| `mock_controller_core.py` | 155 | 无 ROS 依赖的控制器仿真核心，8 场景 | 进程内 MockTransport 与独立 rclpy 节点**共用同一核心**（一套行为两个壳）；它是 mock 模式下的权威端，独立复验全部安全规则 |
| `mock_controller_node.py` | 71 | 上述核心的独立 rclpy 节点壳（`source=gexo_controller_mock`） | K3 上真 Topic 联调用 |
| `api.py` | 248 | create_app 工厂（lifespan 上下文）+ WsHub + 全部端点 | debug 端点仅 `debug.enabled && mock_core is not None` 时挂载 |
| `intent_router.py` | 450 | 规则→LLM tools→复验→执行/澄清（见 §7） | 规则表顺序有含义：status 必须先于 doc（「现在是什么模式」vs「阻尼模式是什么」） |
| `llm_client.py` | 81 | httpx 封装 chat（tools / response_format）+ `extract_tool_call` | 所有网络异常统一抛 `LlmError`，上层捕获后降级 |
| `rag_service.py` | 241 | jieba + SQLite FTS5 + BM25（见 §8） | FTS5 表是**普通表非 contentless**（contentless 不支持 DELETE，rebuild 会炸） |
| `main.py` | 104 | 对象图组装 + CLI（`--config/--transport/--host/--port`） | chat handler 构建失败只 log warning 不崩 |
| `logging_config.py` | 39 | `control_event()` 单行 JSON 结构化日志 | 所有安全拒绝/命令收发/意图解析均有埋点 |

### 线程模型（改并发代码前必读）

只有两个长活线程：

1. **uvicorn asyncio 事件循环**：全部 HTTP/WS、submit/confirm、LLM/RAG 调用（RAG 检索走 `asyncio.to_thread`，索引构建在独立 daemon 线程）。
2. **传输线程**：rclpy spin 或 mock ticker（另有 mock 的 `threading.Timer` 模拟结果延迟）。

跨线程规则：

- 传输线程回调只做：解析 JSON → `StateCache.update()` → `CommandManager.on_result()` → `hub.mark_dirty_threadsafe()`。**禁止 LLM/HTTP/阻塞 IO**。
- 传输线程 → 事件循环的唯一通道是 `loop.call_soon_threadsafe`（唤醒 asyncio.Event / 置脏标记）。
- `CommandManager._records` 与 `MockControllerCore` 内部状态用 `threading.Lock`（双线程访问）；`WsHub._clients` 只在事件循环线程动，不需要锁。
- WsHub 用 asyncio.Event 脏标记合并推送，最小间隔 200ms（`state.ws_min_interval_ms`），慢客户端不积压，发送失败即摘除。

---

## 4. 线格式契约（/g_exo/bridge，version 1.0）

单 Topic 双向复用，`std_msgs/String`，payload 为 JSON。公共信封字段：
`version / type / source / timestamp_ms / request_id`。

| type | 方向 | 关键字段 |
|---|---|---|
| `command` | web→controller | `action`（仅 set_mode/adjust_assist）、`params` |
| `state` | controller→web | `data`（StateData，5Hz 左右） |
| `result` | controller→web | `request_id`（关联 command）、`success`、`error_code`、`message`、`result` |

- `source` 用于防自处理：Adapter 丢弃 `source == "gexo_web_agent"` 的回声；独立 mock 节点用 `gexo_controller_mock`。
- `StateData` 字段见 `schemas.py`（mode/assist_ratio/is_stationary/joint_*/motor_temperature/bus_*/battery_percent/imu_*/can_online/emergency_stop/fault_*），`extra="allow"`——真实控制器加字段不需改代码。
- `is_stationary` 是**建议接口**：已列入契约，Mock 模式下模拟；真实控制器若不提供需另想判据（这是接真机时的第一个待确认项）。

**真实控制器接入路径**（预期唯一改动面）：

1. Topic 名 → 改 `config/default.yaml` 的 `bridge.topic`（或 `GEXO_BRIDGE__TOPIC`）。
2. 消息格式偏离 JSON 契约 → 只改 `ros_bridge.py`：`Ros2Transport._on_ros_message`（入向解码）与 `publish_command`（出向编码），把外部格式转成本文 §4 的 dict 再交给 Adapter。必要时在此处做字段映射。
3. 验证 → K3 上 `python -m pytest tests/test_ros2_transport.py -v`（先跑独立 mock 节点，再换真机）。

---

## 5. SafetyGuard 检查表（有序，第一个失败即拒）

只读操作（query_status / document_qa）直接放行。写操作按序：

| # | 检查 | ErrorCode | 备注 |
|---|---|---|---|
| 1 | 从未收到状态 | `NO_STATE` | |
| 2 | 状态超时（> stale_timeout_s=1.0s） | `STATE_TIMEOUT` | staleness 由 StateCache 判定后传入 |
| 3 | 急停激活 | `EMERGENCY_STOP_ACTIVE` | |
| 4 | 存在故障码 | `FAULT_ACTIVE` | |
| 5 | CAN 离线 | `CAN_OFFLINE` | |
| 6 | 阻尼模式下调助力 | `ASSIST_IN_DAMPING` | 仅 adjust_assist |
| 7 | delta 非恰 ±0.1 | `INVALID_DELTA` | 纵深防御（schemas 已拦一次） |
| 8 | 结果超出 [0.3, 1.0] | `ASSIST_AT_MAXIMUM/MINIMUM` | `round(ratio+delta, 1)` 后比较，±1e-9 容差 |
| 9 | set_mode 未确认 | `CONFIRMATION_REQUIRED` | 触发 pending_confirmation 流程 |
| 10 | 非静止 | `NOT_STATIONARY` | 仅 set_mode |
| 11 | 已在目标模式 | `INVALID_MODE` | 软拒 |

另有非 guard 的拒绝码：`BUSY`（在途互斥，HTTP 409）、`CONFIRMATION_EXPIRED`、`CONTROLLER_TIMEOUT`、`INVALID_ACTION`。

**双层防御**：MockControllerCore（权威端）独立复验急停/故障/CAN/运动中/阻尼/步长/边界。因此当缓存滞后一个 state tick 时，同一违规可能表现为 guard 侧 `rejected` 或控制器侧 `failed`——两者都是正确行为，测试也如此断言（`test_api_e2e.py` 的边界用例接受两种 status，但 error_code 必须精确）。

**加一条安全规则的方法**：schemas.py 加 ErrorCode → safety_guard.py 按正确顺序插入检查（想清楚它应排在哪）→ test_safety_guard.py 加正反用例 → 若权威端也应拦，则 mock_controller_core.py 同步 → 前端 `app.js` 的文案映射（可选）。

---

## 6. 命令生命周期（CommandManager）

```
                  ┌────────── (SafetyGuard 拒) ──────▶ rejected
submit(action) ───┤
                  ├─ set_mode 未确认 ─▶ pending_confirmation ─┬─ confirm(approve=true)
                  │                        │                  │   └─ 对新鲜状态重跑 guard ─▶ sent 或 rejected
                  │                        ├─ approve=false ─▶ cancelled
                  │                        └─ 30s TTL ──────▶ expired（confirm/get_view 时惰性判定）
                  └─ 其余 ───────────────▶ sent ─┬─ result.success ──▶ success
                                                  ├─ result.!success ─▶ failed
                                                  └─ 3s 无 result ───▶ timeout
```

不变量（改动此模块时必须保持）：

- **success 只能由控制器 result 触发**，永不假定。
- **超时即失败，无自动重试**（用户看到失败自己决定重发）。
- **confirm 时对新鲜状态重跑 SafetyGuard**（用户盯着弹窗期间设备可能急停了）。
- **单写命令在途**（`_inflight` asyncio.Lock；并发写 → BUSY/409）。
- **先到终态优先**：`on_result` 只处理 `status is SENT` 的记录，迟到/重复/外来 result 丢弃；timeout 分支复查 `status is SENT` 防竞态。
- 记录存有界 OrderedDict（`command.history_size=200`），`GET /api/action/{request_id}` 即字典查询。

---

## 7. 意图路由

流水线：`route_by_rules()`（确定性，<1ms）→ 未命中则 LLM → `_validate()` Pydantic 白名单复验 → 仍失败则澄清话术。**解析失败/意图不明绝不猜写操作。**

### 规则表（intent_router.py，顺序即优先级）

输入先 `_normalize()`：全角→半角、去标点空白、lower。

| 优先级 | 意图 | 代表模式 | 踩过的坑 |
|---|---|---|---|
| 1 | query_status | `(现在|当前|目前).*(模式|助力|温度|电|状态|can)`、`(还有|剩)(多少|余)`、`多少(度|电)` | 裸 `多少` 曾把「RS02 电机的额定扭矩是多少」误判为查状态，已收紧——**不要放宽回去** |
| 2 | document_qa | `怎么|如何|什么是|是什么|为什么|教程|穿戴|使用方法|注意事项` | status 必须排在 doc 前：「现在是什么模式」是查询，「阻尼模式是什么」是问答 |
| 3 | set_mode damping | `(切|换|进入|开启|…).*(阻尼|训练)` | |
| 4 | set_mode assist | `(切|换|…).*助力(模式)?$` | 末尾 `$` 防止「切大助力」误判 |
| 5 | adjust +0.1 | `助力.*(大|增|加|高|强|提)`、`(增加|加大|…).*助力` | |
| 6 | adjust -0.1 | `助力.*(小|减|降|低|弱)` 等 | |

### LLM 路径

- K3 默认路径：`response_format: json_schema` 单派发 schema（`_JSON_FALLBACK_SCHEMA`，含 `clarify` 动作）。实机 0.8B 对该路径的三项意图测试均正确。
- 可选路径：`llm.force_json_fallback: false` 使用 OpenAI `tools` API。实机 0.8B 对“助力再大一点”未稳定返回 tool call，因此不作为默认。
- 所有请求发送 `chat_template_kwargs.enable_thinking=false`，避免 Qwen3.5 将 token 预算消耗在 reasoning content。
- 模型无 tool call 且有 content → 视为模型自主澄清，原文返回。
- `_validate()`：一切 LLM 输出经 `ActionEnvelope.parse_untrusted()`——编造 action 名、越界 delta、多余字段全部 ValidationError → 澄清。
- `LlmError`（llama-server 挂了）→ 固定降级话术，提示用按钮或固定说法；控制路径不受影响。

### 状态回答与文档问答

- `query_status` 由 `render_status()` **用真实缓存数据确定性渲染**——LLM 永不参与状态数值生成（防编造）。stale → 「设备数据失联」。
- `document_qa`：RAG Top3 → 二次 LLM 调用（system prompt 强制只依据片段、注明来源、无关则说没找到）→ 检索为空直接返回 `NO_DOC_REPLY`；LLM 挂了降级为直接展示最相关原始片段（demo 仍可用）。

---

## 8. RAG 设计

**选型：jieba 预分词 + SQLite FTS5 unicode61 + 内置 bm25()。** 理由：

- FTS5 默认分词器不切中文（整句一个 token）；
- trigram 分词器对「助力」「电池」这类**二字词**失效（不足 3 字符）；
- jieba 对文档和查询统一分词后，unicode61 按空格切即可正确工作。原始 chunk 存伴随列用于展示。

实现要点：

- PDF 用 pypdf 提取文本层（纯 Python 无原生依赖）；单页提取 <20 字符视为扫描页跳过并记日志。
- 分块：先按 markdown 标题切 section，再贪心打包 500–800 字（`chunk_size: 700`）、重叠 100 字，记录 `(file, section/page)` 作为来源。
- 增量索引：按 `(path, mtime, size)` 跳过未变文件；`--rebuild` 全量重建（`DELETE FROM chunks_fts`——因此 FTS5 必须是普通表，contentless 表不支持 DELETE，这是踩过的坑）。
- 语料目录：`data/docs/`（包内补充 md）+ `../../4.document`（仓库 PDF，相对包根解析）。DB 在 `data/rag_index.db`（gitignored）。
- jieba 首次 import 建缓存约 1–2s，`start_rag_indexing()` 在独立 daemon 线程完成 warmup+建索引，就绪前 document_qa 返回「索引正在构建」。
- 实测：`4.document/` 全部 14 个文件 0 错误，首建约 3 分钟（PDF 提取占大头），二次启动增量跳过。

---

## 9. 配置速查

`config/default.yaml` 为唯一默认源；任意键可用 `GEXO_` 前缀环境变量覆盖，嵌套用 `__`：

```bash
GEXO_BRIDGE__TRANSPORT=ros2                  # mock | ros2
GEXO_BRIDGE__TOPIC=/g_exo/bridge
GEXO_STATE__STALE_TIMEOUT_S=1.0
GEXO_COMMAND__RESULT_TIMEOUT_S=3.0
GEXO_COMMAND__CONFIRM_TTL_S=30.0
GEXO_SAFETY__ASSIST_MIN=0.3                  # 改边界只动配置，代码无硬编码（mock core 除外）
GEXO_LLM__BASE_URL=http://127.0.0.1:9193/v1
GEXO_LLM__MODEL=Qwen3.5-0.8B-Q4_0.gguf
GEXO_LLM__ENABLE_THINKING=false
GEXO_LLM__FORCE_JSON_FALLBACK=true           # 实机 0.8B 的已验证默认路径
GEXO_MOCK__SCENARIO=estop                    # normal|estop|fault|can_offline|moving|overheat|no_reply|fail
GEXO_DEBUG__ENABLED=false                    # 真机演示务必关（关闭 /api/debug/scenario）
```

注意：`mock_controller_core.py` 顶部的 `ASSIST_MIN/MAX/STEP` 是权威端自己的常量（模拟真实控制器有独立配置的事实），与 `safety` 配置改其一不自动同步——若要改边界，两处都要改。

---

## 10. 提交历史（8 个阶段 commit，feature/web-agent）

| # | commit | 内容 |
|---|---|---|
| 1 | `1e3ff04` | scaffold：package.xml / setup.py / config / schemas / logging |
| 2 | `c5cfcc1` | state_cache、mock_controller_core、ros_bridge 传输抽象 |
| 3 | `fb69d32` | safety_guard 全序检查表（先于 API，任何端点从诞生起有防护） |
| 4 | `ffda4dd` | command_manager 确认/超时生命周期 |
| 5 | `c17873a` | FastAPI 端点、WsHub、main 入口（此起 Mock 端到端可跑 = 验收 #18） |
| 6 | `973b7d6` | 手机 Web UI（状态卡片/控制/对话壳/调试区） |
| 7 | `3e0b13a` | llm_client、intent_router、rag_service |
| 8 | `e5ca764` | ros2 收尾：mock 节点、launch、scripts、README、设备端冒烟测试 |

依赖安装注意（Windows 开发机踩坑）：pytest-asyncio 1.x 在含旧式 `backports` regular package 的 anaconda 环境下 import 失败（namespace 包被遮蔽，装 `backports.asyncio.runner` 也无解），**锁定 `pytest-asyncio==0.21.2`**（requirements.txt 已固定，pytest.ini `asyncio_mode=auto`）。

---

## 11. 测试矩阵

```bash
python -m pytest tests/ -q          # Windows/无 ROS 2：176 passed, 1 skipped
```

| 文件 | 覆盖 |
|---|---|
| test_schemas.py | delta 恰 ±0.1、模式枚举、白名单派发、线格式往返 |
| test_state_cache.py | 快照原子性、staleness |
| test_mock_controller_core.py | 8 场景行为、权威端复验 |
| test_ros_bridge.py | source 过滤、消息派发、Mock 传输 |
| test_safety_guard.py | 全部拒绝码 + 0.3/1.0 边界 + 浮点容差 + stale/no-state |
| test_command_manager.py | 状态机全梯、确认过期、confirm 重校验、超时即失败、不重试、在途 BUSY |
| test_intent_router_rules.py | 规则表正反例（含 status/doc 分流、`多少` 收紧回归） |
| test_intent_router_llm.py | FakeLlm canned 响应、编造 action 被拒、越界 delta 被拒、LlmError 降级 |
| test_rag_service.py | 增量索引、中文二字词命中、无依据回答 |
| test_api_e2e.py | httpx ASGITransport + Mock 全链路，覆盖验收标准 4–15、18 |
| test_ros2_transport.py | **仅 K3**（`pytest.importorskip("rclpy")`），真 Topic 往返冒烟 |

测试写法约定：

- e2e 用 `app.router.lifespan_context` 手动进入 lifespan（TestClient 不自动触发）。
- 安全边界用例接受 `status in ("rejected", "failed")` 但 error_code 精确断言（双层防御两条路径都合法，见 §5）。
- LLM 测试全部用 FakeLlm/FakeRag 注入，不依赖真 llama-server。

---

## 12. 已知风险与迭代待办

**接真机前必须确认：**

1. **模型配置漂移**——部署前查询 K3 的进程参数和 `/v1/models`；若模型或端口变化，先更新配置再验证 JSON Schema 路径，禁止依据旧文档猜测。
2. **真实控制器线格式**——预期只改 `ros_bridge.py`（§4 接入路径）；`is_stationary` 若真机不提供，需和控制器方定判据。
3. **`GEXO_DEBUG__ENABLED=false`**——真机演示必关，否则场景注入端点暴露在局域网。

**已知薄弱点：**

- `k3_pico_itx_2d_0512.pdf` 近扫描版只提取出 1 个 chunk；若演示涉及该文档，向 `data/docs/` 补 md 语料后 `python scripts/build_rag_index.py --rebuild`。
- 无鉴权：任何局域网设备可控设备（黑客松范围内接受；若延长使用，最小改动是 FastAPI middleware 加 token）。
- WsHub 广播是逐客户端顺序 await；客户端 >10 时考虑 `asyncio.gather` 并发发送。
- Ros2Transport 的 `stop()` 直接 `rclpy.shutdown()`——多节点同进程场景需改为 executor 级关闭（当前单节点无碍）。

**自然的迭代扩展点：**

| 想做的事 | 改哪里 |
|---|---|
| 新增一个 LLM 意图 | schemas.py 加 Action 模型入 Union → intent_router.py TOOLS+SYSTEM_PROMPT+handle 分支 →（若写操作）safety_guard/command_manager → 测试 |
| 新增安全规则 | §5 末尾的五步法 |
| 换/加控制 Topic、改消息格式 | 仅 ros_bridge.py + config（§4） |
| 状态页加新字段 | StateData（extra=allow，可能已透传）→ render_status() → 前端 app.js |
| 换 LLM 模型 | 只改 `llm.model` / `MODEL_PATH`（llm_client 是 OpenAI 兼容通用封装） |
| RAG 换向量检索 | 只动 rag_service.py（RagHit 接口不变，IntentRouter 无感知） |
