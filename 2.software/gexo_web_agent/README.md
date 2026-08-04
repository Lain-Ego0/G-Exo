# gexo_web_agent

外骨骼本地大模型 Web 交互与 ROS 2 控制桥接系统。

手机浏览器 → FastAPI（Web/对话/安全校验）→ 单一 ROS 2 Topic（JSON）→ 控制节点。
本地 LLM（llama.cpp + K3 当前部署的 Qwen3.5-0.8B）只负责意图解析和语言组织，**从不直接控制电机**。

## 架构

```
浏览器 (React + Vite build, WebSocket)
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

### 前端开发与构建

FastAPI 继续托管 `static/` 中已经编译好的生产文件；K3 运行服务不需要 Node.js。
修改 React 源码时在开发机执行：

```bash
cd 2.software/gexo_web_agent/frontend
npm ci
npm run dev       # 5173，/api、/health、/ws 代理到 127.0.0.1:8000
npm run build     # TypeScript 检查后输出到 ../static
```

`frontend/src/` 是唯一手工维护的前端源码，`static/` 是需随 Python 包部署的构建产物。

### B. K3 实机（Bianbu 4.0.1 + ROS 2 Humble）

2026-08-02 实机核验结果：`riscv64`、系统 Python 3.14、ROS 2 Humble overlay，
`/usr/bin/llama-server` 已在 `127.0.0.1:9193` 加载
`~/.cache/models/llm/Qwen3.5-0.8B-Q4_0.gguf`。运行配置以 `/v1/models` 返回为准：

```bash
# 1. 已有服务健康时不要重复启动或下载模型
curl http://127.0.0.1:9193/v1/models
# 仅服务未运行时，复用实机已有 GGUF 和当前参数
bash scripts/start_llama_server.sh

# 2. 虚拟环境保留系统 ROS Python 包可见性
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
source /opt/ros/humble/setup.bash
source /home/gexo/ros2_ws/install/setup.bash

# 3a. 进程内 Mock（不依赖 ROS，最安全的 Web/LLM/RAG 演示路径）
python -m gexo_web_agent.main --transport mock --host 0.0.0.0 --port 8000

# 3b. ROS 2 端到端 Mock。使用隔离 topic，避免触达未来的真实控制器。
python scripts/mock_controller.py --topic /g_exo/mock_bridge --scenario normal
# 另开同环境终端：
GEXO_BRIDGE__TOPIC=/g_exo/mock_bridge \
  python -m gexo_web_agent.main --transport ros2 --host 0.0.0.0 --port 8000
```

### 配置

`config/default.yaml`，所有键可用 `GEXO_` 前缀环境变量覆盖（`__` 分隔嵌套）：

```bash
GEXO_BRIDGE__TRANSPORT=ros2        # mock | ros2
GEXO_BRIDGE__TOPIC=/g_exo/bridge
GEXO_STATE__STALE_TIMEOUT_S=1.0
GEXO_LLM__BASE_URL=http://127.0.0.1:9193/v1
GEXO_LLM__MODEL=Qwen3.5-0.8B-Q4_0.gguf
GEXO_LLM__ENABLE_THINKING=false
GEXO_LLM__FORCE_JSON_FALLBACK=true
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
cd frontend && npm run build      # React 类型检查 + 生产静态构建
```

覆盖验收标准：助力边界/步长、阻尼禁调、二次确认、运动中拒绝、急停/故障/CAN 拒绝、
超时失败、真实失败原因透传、状态失联显示、无文档依据不编造、Mock 全链路演示（#18）。

## 目录

```
gexo_web_agent/   核心模块（schemas/config/state_cache/safety_guard/
                  command_manager/ros_bridge/mock_controller_core/
                  llm_client/intent_router/rag_service/api/main）
frontend/         React + TypeScript + Vite 源码（SENSE / REASON / ACT Cockpit）
static/           Vite 生产构建产物，由 FastAPI 静态托管
config/           default.yaml
launch/ scripts/  ROS 2 launch 与启动脚本
data/docs/        RAG 补充语料（另默认索引仓库 4.document/ 的 PDF）
tests/            pytest（无 ROS 2 环境全部可跑）
```
