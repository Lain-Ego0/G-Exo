# gexo_web_agent

外骨骼本地大模型 Web 交互与 ROS 2 控制桥接系统。

手机浏览器 → FastAPI（Web/对话/安全校验）→ 单一 ROS 2 Topic（JSON）→ 控制节点。
本地 LLM（llama.cpp + Qwen3-4B）只负责意图解析和语言组织，**从不直接控制电机**。

## 架构

```
浏览器 (HTML/JS, WebSocket)
   │
FastAPI  ── /api/chat ──▶ IntentRouter（规则优先 → LLM tools → Pydantic 校验）
   │            │                │
   │            │                └─▶ RagService（jieba + FTS5 + BM25 教程问答）
   │            ▼
   │       SafetyGuard（独立安全校验，按钮与 LLM 同一入口，无特权差别）
   │            │
   │       CommandManager（二次确认 / request_id 关联 / 超时即失败 / 不重试）
   │            │
   │       RosBridgeAdapter ──┬─ MockTransport（进程内模拟控制器，无需 ROS 2）
   │                          └─ Ros2Transport（/g_exo/bridge, String+JSON）
   └── /ws  实时状态推送（StateCache，1s 超时判失联）
```

两种工作模式：**助力模式 assist**（全局 assist_ratio 0.3–1.0，步长 ±0.1，四关节统一）
和**阻尼训练模式 damping**（停止主动助力，电机转阻尼/保护状态）。
LLM 只允许 4 个意图：`query_status` / `set_mode` / `adjust_assist` / `document_qa`。

## 从零启动

### A. 开发机 / 无 ROS 2 环境（Mock 模式，完整演示）

```bash
cd 2.software/gexo_web_agent
pip install -r requirements.txt
python -m gexo_web_agent.main            # 默认 mock transport, 0.0.0.0:8000
```

手机与电脑同一局域网，浏览器打开 `http://<电脑IP>:8000`。
调试折叠区可切换 Mock 场景（急停/故障/CAN 离线/运动中/超时不回…）验证全部安全分支。

### B. K3 设备（Ubuntu 22.04 + ROS 2 Humble）

```bash
# 1. 启动本地大模型（另开终端，常驻）
MODEL_PATH=~/models/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf \
  bash scripts/start_llama_server.sh          # 127.0.0.1:8080/v1

# 2a. pip 方式（黑客松推荐，最少步骤）
pip install -r requirements.txt
source /opt/ros/humble/setup.bash
python -m gexo_web_agent.main --transport ros2

# 2b. 或 colcon 方式
cd <ros2_ws> && ln -s <repo>/2.software/gexo_web_agent src/gexo_web_agent
colcon build --packages-select gexo_web_agent && source install/setup.bash
ros2 launch gexo_web_agent gexo_web_agent.launch.py use_mock_controller:=true

# 3. 真实控制器未就绪时，用独立 Mock 节点联调真 Topic：
python scripts/mock_controller.py --scenario normal
```

### 配置

`config/default.yaml`，所有键可用 `GEXO_` 前缀环境变量覆盖（`__` 分隔嵌套）：

```bash
GEXO_BRIDGE__TRANSPORT=ros2        # mock | ros2
GEXO_BRIDGE__TOPIC=/g_exo/bridge
GEXO_STATE__STALE_TIMEOUT_S=1.0
GEXO_LLM__BASE_URL=http://127.0.0.1:8080/v1
GEXO_DEBUG__ENABLED=false          # 真机演示时关闭调试端点
```

真实控制器 Topic 名称/消息格式定型后，只需修改 `ros_bridge.py`（及 topic 配置），
Web/LLM/安全逻辑零改动。

## HTTP API

| 端点 | 说明 |
|---|---|
| `GET /health` | 存活探针 |
| `GET /api/state` | 最新状态快照 + 失联标记 |
| `POST /api/chat` | 自然语言（规则→LLM 意图解析→安全校验→执行） |
| `POST /api/action` | 按钮直达（同一 SafetyGuard） |
| `POST /api/confirm` | 模式切换二次确认 |
| `GET /api/action/{request_id}` | 命令状态轮询 |
| `WS /ws` | 状态实时推送 |

命令状态机：`pending_confirmation → sent → success | failed | timeout`，
另有 `rejected / expired / cancelled`。控制器未确认前绝不显示成功；超时即失败，不自动重发。

## 安全设计（独立于提示词）

写操作按序检查：无状态 → 状态超时 → 急停 → 故障 → CAN 离线 → 阻尼模式禁调助力 →
步长必须 ±0.1 → 结果限 [0.3, 1.0] → 模式切换需确认 → 需站立静止 → 已在目标模式。
Mock 控制器作为权威端再次校验全部规则（双层防御）。
`is_stationary` 字段已列入建议接口，Mock 模式下模拟。

## 测试

```bash
python -m pytest tests/ -q        # Windows/无 ROS 2 → 176 通过，ROS 用例自动跳过
python -m pytest tests/test_ros2_transport.py -v   # 仅 K3 设备（需 rclpy）
python scripts/build_rag_index.py --rebuild        # 手动重建教程索引
```

覆盖验收标准：助力边界/步长、阻尼禁调、二次确认、运动中拒绝、急停/故障/CAN 拒绝、
超时失败、真实失败原因透传、状态失联显示、无文档依据不编造、Mock 全链路演示（#18）。

## 目录

```
gexo_web_agent/   核心模块（schemas/config/state_cache/safety_guard/
                  command_manager/ros_bridge/mock_controller_core/
                  llm_client/intent_router/rag_service/api/main）
static/           手机 Web 页面（原生 HTML/CSS/JS）
config/           default.yaml
launch/ scripts/  ROS 2 launch 与启动脚本
data/docs/        RAG 补充语料（另默认索引仓库 4.document/ 的 PDF）
tests/            pytest（无 ROS 2 环境全部可跑）
```
