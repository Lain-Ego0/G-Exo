# SpacemiT K3 omni_agent 语音助手 · 完整启动流程

> 适用开发板：SpacemiT K3 (com260ifx) · Bianbu 4.0.1 (riscv64)
> 主机名：`gexo-spacemitk3com260ifx` · 局域网 IP：`192.168.11.66` · 用户：`gexo`
> 本文档基于 Spacemit 官方文档《4.5 Agent》整理，并结合本板实际验证结果。

---

## 1. 环境总览

| 项目 | 值 |
|---|---|
| 系统 | Bianbu 4.0.1 (Debian 系), kernel 6.18.3-generic, riscv64 |
| CPU / 内存 | 8 核 / 15 GiB RAM + 31 GiB swap |
| SDK 路径 | `~/spacemit_robot` |
| SDK 环境脚本 | `source ~/spacemit_robot/build/envsetup.sh` |
| Agent 源码 | `~/spacemit_robot/application/native/omni_agent` |
| 配置目录 | `~/.config/omni_agent/`（5 个 JSON） |
| 日志目录 | `~/.cache/omni_agent/logs/` |
| 测试工作区 | `~/omni_test/`（文件版流水线） |
| 音频输入 | ❌ 无（无麦克风/无 USB 音频设备） |
| 音频输出 | ✅ snddp1 I2S DP 播放 |

### 1.1 依赖组件

| 组件 | 路径 | 作用 |
|---|---|---|
| audio | `components/multimedia/audio` | 音频采集、播放、重采样 |
| VAD | `components/model_zoo/vad` | Silero VAD 语音起止检测 |
| ASR | `components/model_zoo/asr` | Qwen3-ASR 语音识别 |
| TTS | `components/model_zoo/tts` | Matcha-TTS 语音合成 |
| LLM | `~/.cache/models/llm` | Qwen3.5-4B 对话模型 |
| voiceprint | `components/model_zoo/voiceprint` | 可选说话人验证 |
| MCP | `components/agent_tools/mcp` | 可选工具调用 |

### 1.2 语音对话管线（官方架构）

```
麦克风采集 → VAD 检测 → (声纹验证) → ASR 识别 → LLM 生成回复 → (MCP 工具) → TTS 合成 → 扬声器
                                        ↕ barge-in 打断（TTS 播放期间 VAD 持续工作）
```

---

## 2. 模型清单（均已下载验证 ✅）

| 模型 | 路径 | 大小 |
|---|---|---|
| LLM | `~/.cache/models/llm/Qwen3.5-4B-Q4_0.gguf` | 2.5 GB |
| ASR | `~/.cache/models/asr/qwen3-asr-0.6B-dynq-q40/`（含 3 个文件 + config.json） | — |
| VAD | `~/.cache/models/vad/silero/silero_vad.onnx` | 2.3 MB |
| TTS | `~/.cache/models/tts/matcha-tts/matcha-icefall-zh-en/`（model-steps-3.q.onnx + vocab_tts.txt） | — |

> ⚠️ 镜像地址已变更：旧地址 `vad/silero.tar.gz`、`tts/matcha-tts.tar.gz` 已 404，
> 新地址为目录式：
> - VAD: `https://archive.spacemit.com/spacemit-ai/model_zoo/vad/silero/silero_vad.onnx`
> - TTS: `https://archive.spacemit.com/spacemit-ai/model_zoo/tts/matcha-tts/matcha-icefall-zh-en.tar.gz`
> - ASR: `https://archive.spacemit.com/spacemit-ai/model_zoo/asr/qwen3-asr-0.6B-dynq-q40.tar.gz`

---

## 3. 一键启动流程（语音对话）

### 3.1 第一步：加载 SDK 环境

```bash
source ~/spacemit_robot/build/envsetup.sh
```

### 3.2 第二步：启动两个 llama-server（LLM + ASR）

两个服务都需要后台常驻，建议用 nohup：

```bash
# --- LLM 服务 (Qwen3.5-4B, 端口 9191) ---
nohup llama-server -m /home/gexo/.cache/models/llm/Qwen3.5-4B-Q4_0.gguf \
    --host 127.0.0.1 --port 9191 -c 4096 -t 8 --no-webui \
    > /tmp/llm_server.log 2>&1 &

# --- ASR 服务 (Qwen3-ASR-0.6B, 端口 8063, 需要 SMT 加速后端) ---
nohup llama-server -m /home/gexo/.cache/models/asr/qwen3-asr-0.6B-dynq-q40/Qwen3-ASR-0.6B-text-q40.gguf \
    --media-backend smt \
    --smt-config-dir /home/gexo/.cache/models/asr/qwen3-asr-0.6B-dynq-q40 \
    --host 127.0.0.1 --port 8063 -c 4096 -t 4 --no-webui \
    > /tmp/asr_server.log 2>&1 &
```

等待就绪（约 35s LLM + 12s ASR）：

```bash
# 等待两个端口监听
for p in 9191 8063; do
    for i in $(seq 1 30); do
        ss -tlnp 2>/dev/null | grep -q ":$p " && echo "端口 $p 就绪" && break
        sleep 10
    done
done
# 验证
ss -tlnp | grep -E '9191|8063'
grep -E "model loaded|listening" /tmp/llm_server.log | tail -2
grep -E "model loaded|listening" /tmp/asr_server.log | tail -2
```

> 注意：每次重启 llama-server 都要重新加载模型（LLM ~34s，ASR ~11s），非必要不要重启。

### 3.3 方式 A：文件版语音对话（当前无麦克风环境推荐）

这是本板当前唯一可完整跑通的语音闭环方案（无音频输入设备时）。

```bash
cd ~/omni_test
# 一键流水线：TTS 合成问题 → ASR 识别 → LLM 回复 → TTS 合成回答
./voice_file_pipeline.sh "你好，请介绍一下你自己"
```

产物：`q_<时间戳>.wav`（问题音频）、`reply_<时间戳>.wav`（回答音频）、`resp_<时间戳>.json`（LLM 原始回复）。

分步手动执行：

```bash
# 1) TTS 合成问题音频（matcha:zh-en = 16kHz 中英双语）
tts_file_demo -p "你好，请问今天天气怎么样？" -l matcha:zh-en -o question.wav

# 2) ASR 识别
asr_file_demo question.wav --engine qwen3-asr \
    --endpoint http://127.0.0.1:8063/v1/chat/completions

# 3) LLM 生成回复（⚠️ 必须关闭思考模式！）
curl -s http://127.0.0.1:9191/v1/chat/completions -H "Content-Type: application/json" \
  -d '{"model":"qwen3.5-4b",
       "messages":[{"role":"system","content":"你是嵌入式开发板上的语音助手，请用中文简短回答，不超过30字。"},
                   {"role":"user","content":"你好，请问今天天气怎么样？"}],
       "max_tokens":120,
       "chat_template_kwargs":{"enable_thinking":false}}'

# 4) TTS 合成回答音频
tts_file_demo -p "抱歉，我无法获取实时天气信息。请告诉我您想聊什么？" -l matcha:zh-en -o reply.wav
```

#### ⚠️ Qwen3.5-4B 思考模式关键经验

| 现象 | 原因 | 解决 |
|---|---|---|
| `content` 为空，只有 `reasoning_content` | Qwen3.5 默认开启思考，token 全被思考占用 | 请求加 `"chat_template_kwargs":{"enable_thinking":false}` |
| 思考模式被截断无正文 | `max_tokens` 太小 | 关闭思考 + `max_tokens:120` 足够 |
| `thinking:{"type":"disabled"}` / `reasoning_effort:0` 无效 | 不是该模型识别的参数 | 使用 `chat_template_kwargs.enable_thinking=false` |

### 3.4 方式 B：voice_chat_daemon 麦克风实时对话（未来接入手机音频后用）

```bash
source ~/spacemit_robot/build/envsetup.sh

# 初始化/查看配置（不会覆盖已有文件）
voice_chat_daemon config-init
voice_chat_daemon config-show

# 启动 / 状态 / 日志 / 停止
voice_chat_daemon start          # 标准模式
voice_chat_daemon status
voice_chat_daemon logs           # tail -f 日志
voice_chat_daemon stop

# 临时启用软件 AEC / MCP
voice_chat_daemon start --aec --mcp

# 声纹注册（可选）
voice_chat_daemon --register-speaker NAME
```

> ⚠️ 当前板卡无输入音频设备，`start` 会报：
> `错误: 没有匹配到输入设备 hints: ["SPV Composite", "USB Audio"]`
> 这是预期的——接入手机音频接收器后即可正常运行。

---

## 4. 配置文件详解（~/.config/omni_agent/）

### 4.1 voice_chat.json（主干配置）

本板当前实际配置要点：

```jsonc
{
    "mode": "voice_chat",
    "audio": {
        "input_device_hints":  ["SPV Composite", "USB Audio"],   // 输入设备名匹配序列
        "output_device_hints": ["SPV Composite", "USB Audio"],   // 输出设备名匹配序列
        "input_device_id":  null,   // 非 null 时直接按 PortAudio index 指定
        "output_device_id": null,
        "capture_rate":     16000,  // 录音采样率（AEC 模式必须 48000）
        "playback_rate":    16000,  // 播放采样率（USB 设备不支持 48k 时改 16000）
        "capture_channels": 4,      // 4 麦阵列
        "playback_channels": 2,
        "speech_channel":   1
    },
    "tts": "matcha:zh-en",
    "vad": { "threshold": 0.8, "silence_duration": 0.5 },
    "asr": { "engine": "qwen3-asr", "endpoint": "http://127.0.0.1:8063/v1/chat/completions",
             "auto_start_server": true, "server_port": 8063,
             "model_path": "~/.cache/models/asr/qwen3-asr-0.6B-dynq-q40/Qwen3-ASR-0.6B-text-q40.gguf",
             "smt_config_dir": "~/.cache/models/asr/qwen3-asr-0.6B-dynq-q40" },
    "wake": { "enabled": false },
    "debug": {
        "save_audio": false,             // 调试录音开关
        "save_tts_audio": false,         // 保存 TTS 输出排查音质
        "save_tts_audio_file": "tts_debug.wav"
    },
    "startup_greeting": "你好，请问有什么可以帮到您？",
    "log_dir":  "~/.cache/omni_agent/logs",
    "pid_file": "~/.cache/omni_agent/voice_chat_daemon.pid"
}
```

### 4.2 llm.json（LLM 配置，本板已指向 Qwen3.5-4B）

```jsonc
{
    "auto_start_server": true,                     // 自动拉起本地 llama-server
    "api_base": null,                              // null = 本地；非空 = 云端 OpenAI API
    "server_binary": "llama-server",
    "server_port": 9191,
    "model_path": "~/.cache/models/llm/Qwen3.5-4B-Q4_0.gguf",
    "model_name": "qwen3.5-4b",
    "ctx_size": 4096,
    "threads": 8,
    "reasoning_budget": 0,        // 0 = 隐藏 thinking，避免思考内容送 TTS
    "max_tokens": 200,
    "system_prompt": "You are a helpful assistant."
}
```

云端 LLM 示例（api_base 非空时 daemon 不再启动本地服务）：

```jsonc
{ "api_base": "https://api.deepseek.com", "api_key": "sk-...", "model_name": "deepseek-v4-flash" }
```

其余 3 个文件：`voiceprint.json`（声纹）、`mcp.json`（工具调用）、`aec.json`（回声消除）按需启用，默认关闭即可。

---

## 5. 📱 局域网手机音频接收器方案（后续开发方向）

> 目标：手机作为无线麦克风 + 扬声器，通过局域网（WiFi）与开发板通信，
> 让 `voice_chat_daemon` 的实时对话模式在无硬件音频设备情况下也能工作。

### 5.1 方案对比

| 方案 | 原理 | 优点 | 缺点 | 推荐度 |
|---|---|---|---|---|
| **A. ALSA Loopback + 网络音频** | 手机 App 推流 → 开发板创建虚拟声卡（`snd-aloop`）→ voice_chat 从虚拟声卡采集/播放 | 不改 agent 代码，voice_chat 透明工作 | 需要开发板跑音频服务器 + 手机端 App | ⭐⭐⭐⭐⭐ |
| **B. RTP/RTSP 音频流** | 手机推 RTP 流，开发板 `gst-launch` 收流转虚拟声卡 | 标准协议 | 手机端 App 选择少 | ⭐⭐⭐ |
| **C. MQTT/WebSocket 自研** | 自写推流/订阅服务，两端各写客户端 | 完全可控、可加协议 | 工作量大 | ⭐⭐ |
| **D. USB/IP 虚拟音频** | USB/IP 把远端 USB 音频设备映射到开发板 | 透明 | 手机不支持 | ❌ |

### 5.2 推荐实施方案（方案 A 详细步骤）

```
手机 App (麦克风+扬声器)
   │  WiFi UDP/HTTP 音频流
   ▼
开发板 音频桥接服务 (python/node 脚本)
   │  写入/读取
   ▼
ALSA 虚拟声卡 (snd-aloop, "Loopback")
   │  PortAudio 采集/播放
   ▼
voice_chat 进程 (不感知变化)
```

**开发板侧准备（预留脚本位置：`~/omni_test/phone_audio_bridge/`）：**

```bash
# 1) 加载 ALSA 回环虚拟声卡
sudo modprobe snd-aloop
# 验证：aplay -l 应出现 Loopback 设备

# 2) 验证 voice_chat 能枚举到虚拟设备
# 修改 voice_chat.json:
#   "input_device_hints":  ["Loopback"]
#   "output_device_hints": ["Loopback"]

# 3) 手机端可选 App（安卓）：
#    - AudioRelay / SoundWire / WO Mic（把手机当网络麦克风）
#    - 或自己用 Python + pyaudio 写推流脚本
```

**手机侧 Python 推流示例（预留，后续开发）：**

```python
# phone_mic.py —— 跑在手机上（Termux 或电脑模拟）
import socket, pyaudio, struct
CHUNK, RATE, FORMAT, CHANNELS = 1600, 16000, pyaudio.paInt16, 1
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
p = pyaudio.PyAudio()
stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                input=True, frames_per_buffer=CHUNK)
while True:
    sock.sendto(struct.pack('!I', len(data)) + data if (data := stream.read(CHUNK)) else b'', ('192.168.11.66', 12345))
```

**开发板侧接收脚本（预留）：**

```python
# board_audio_sink.py —— 跑在开发板，把 UDP 音频写入 snd-aloop 捕获端
import socket, subprocess
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('0.0.0.0', 12345))
# 用 arecord/aplay 或 pyaudio 写入 Loopback 设备
```

### 5.3 里程碑规划

- [ ] M1：开发板加载 snd-aloop，`aplay/arecord` 读写 Loopback 验证
- [ ] M2：手机推流 → 开发板 Loopback → `asr_file_demo` 识别成功
- [ ] M3：`voice_chat.json` 的 hints 改为 Loopback，`voice_chat_daemon start` 成功
- [ ] M4：TTS 回复通过 Loopback → 手机接收播放（双向闭环）
- [ ] M5：加入 barge-in 打断、双工体验优化

---

## 6. 常用命令速查

```bash
# 服务状态
ss -tlnp | grep -E '9191|8063'        # LLM / ASR 端口
pgrep -af llama-server                 # 服务进程
voice_chat_daemon status               # daemon 状态（含 PID、日志路径）

# 日志
voice_chat_daemon logs                 # tail -f
tail -f ~/.cache/omni_agent/logs/*.log # 或直接看日志目录
tail -20 /tmp/llm_server.log           # LLM 服务日志
tail -20 /tmp/asr_server.log           # ASR 服务日志

# 配置
voice_chat_daemon config-show          # 查看合并后有效配置
voice_chat_daemon config-init          # 补写缺失配置（不覆盖已有）
voice_chat_daemon config-init --force  # 备份后还原默认（备份在 .backup-时间戳）

# 重启
voice_chat_daemon restart              # 先停后启
```

---

## 7. 调试与排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| `start` 报没有匹配到输入设备 | 无麦克风（本板现状） | 用文件版流水线，或接入手机音频（第 5 章） |
| 端口 9191/8063 被占用 | 上次服务未退出 | `pkill -f llama-server` 后重启 |
| LLM 回复为空、只有思考 | Qwen3.5 思考模式 | 请求加 `enable_thinking:false` |
| 报模型不存在 | 模型未下载到 model_path | 按第 2 章下载 |
| USB 设备 Invalid sample rate | 设备不支持 48k | `playback_rate` 设为 16000 |
| 播放思考内容 | reasoning_budget 被覆盖 | 保持 `llm.json.reasoning_budget=0` |
| 没有声音 | 设备 index/hints 不匹配 | 检查 `audio.input/output_device_hints` |

---

## 8. 重启电脑后的恢复步骤（速查卡）

```bash
# 1. 加载环境（若用到 SDK 工具）
source ~/spacemit_robot/build/envsetup.sh

# 2. 启动 LLM + ASR 服务（见 3.2 节两条 nohup 命令）

# 3a. 文件版测试
cd ~/omni_test && ./voice_file_pipeline.sh "你好"

# 3b. 实时对话（需先接入音频设备，见第 5 章）
voice_chat_daemon start && voice_chat_daemon status
```

---

*文档版本: v1.0 · 2026-08-01 · 基于实板验证（ASR RTF 0.196 / LLM ~7 tok/s / TTS RTF 0.23）*
