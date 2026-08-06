#!/bin/bash
# ============================================================
# 语音控制 Agent —— 支持工具调用 (function calling)
# 说"加大速度" → LLM 识别意图 → 执行 ros2 发布 /cmd_vel
# 说"你好"     → 正常聊天回复
#
# 用法: ./voice_control.sh "你的话"
# 依赖: speed_controller.py (ROS2 速度控制)
# ============================================================
set -e
source ~/G-Exo/spacemit_robot/build/envsetup.sh >/dev/null 2>&1
source /opt/ros/humble/setup.bash 2>/dev/null || true
source ~/G-Exo/ros2_ws/install/setup.bash 2>/dev/null || true

TEXT="${1:-你好}"
TS=$(date +%H%M%S)
cd ~/G-Exo/omni_test

# ---------- 1. LLM 带工具调用生成回复 ----------
echo "[1/3] LLM 分析意图 (function calling)..."
cat > /tmp/tools_payload_${TS}.json << PAYLOAD_EOF
{
  "model": "qwen3.5-4b",
  "messages": [
    {"role":"system","content":"你是嵌入式开发板上的语音助手。你可以调用工具控制机器人。若用户要求调整速度请调用 set_speed 工具，否则直接中文简短回答，不超过50字。"},
    {"role":"user","content":"$TEXT"}
  ],
  "max_tokens": 200,
  "chat_template_kwargs": {"enable_thinking": false},
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "set_speed",
        "description": "调整机器人移动速度。speed_up=加速, slow_down=减速, stop=停止",
        "parameters": {
          "type": "object",
          "properties": {
            "action": {"type": "string", "enum": ["speed_up", "slow_down", "stop"]},
            "amount": {"type": "number", "description": "可选的速度变化量, 默认0.1"}
          },
          "required": ["action"]
        }
      }
    }
  ]
}
PAYLOAD_EOF

curl -s -X POST http://127.0.0.1:9191/v1/chat/completions \
  -H "Content-Type: application/json" --data @/tmp/tools_payload_${TS}.json \
  > /tmp/tools_resp_${TS}.json

# ---------- 2. 解析响应: 工具调用 or 普通对话 ----------
FINISH=$(python3 -c "import json; d=json.load(open('/tmp/tools_resp_${TS}.json')); print(d['choices'][0]['finish_reason'])")
echo "    finish_reason: $FINISH"

if [ "$FINISH" = "tool_calls" ]; then
    # ---- 工具调用分支: 执行速度控制 ----
    ACTION=$(python3 -c "
import json
d=json.load(open('/tmp/tools_resp_${TS}.json'))
args=json.loads(d['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
print(args.get('action',''))
")
    echo "[2/3] 🔧 检测到工具调用: set_speed -> $ACTION"
    RESULT=$(python3 ~/G-Exo/omni_test/speed_controller.py "$ACTION" 2>&1 | tail -2)
    echo "    执行结果: $RESULT"
    SPEED=$(python3 ~/G-Exo/omni_test/speed_controller.py status 2>&1 | grep -o '[0-9.]* m/s' || echo "0.00 m/s")
    echo "    当前速度: $SPEED"
    case "$ACTION" in
        speed_up)  REPLY="好的，已为您加速，当前速度 ${SPEED}" ;;
        slow_down) REPLY="好的，已为您减速，当前速度 ${SPEED}" ;;
        stop)      REPLY="好的，机器人已停止" ;;
        *)         REPLY="已执行 ${ACTION} 操作" ;;
    esac
else
    # ---- 普通对话分支: 先做关键词规则兜底 ----
    REPLY=$(python3 -c "import json; print(json.load(open('/tmp/tools_resp_${TS}.json'))['choices'][0]['message']['content'])")
    echo "[2/3] 💬 普通对话: $REPLY"
    # 规则兜底: 若文本包含速度控制关键词而 LLM 未触发工具, 强制走工具分支
    # 注意: 停止匹配必须放在最前, 防止"停车"等词被"减速"模式误匹配
    case "$REPLY" in
        *停*止*|*停车*|*停下*|*刹车*|*停*下*)
            ACTION="stop"
            echo "    ⚡ 规则兜底触发: 识别为停止指令"
            RESULT=$(python3 ~/G-Exo/omni_test/speed_controller.py "$ACTION" 2>&1 | tail -2)
            echo "    执行结果: $RESULT"
            REPLY="好的，机器人已停止"
            ;;
        *加*速*|*快*一*点*|*快*点*|*开*快*)
            ACTION="speed_up"
            echo "    ⚡ 规则兜底触发: 识别为加速指令"
            RESULT=$(python3 ~/G-Exo/omni_test/speed_controller.py "$ACTION" 2>&1 | tail -2)
            echo "    执行结果: $RESULT"
            SPEED=$(python3 ~/G-Exo/omni_test/speed_controller.py status 2>&1 | grep -o '[0-9.]* m/s' || echo "0.00 m/s")
            REPLY="好的，已为您加速，当前速度 ${SPEED}"
            ;;
        *减*速*|*慢*一*点*|*慢*点*|*开*慢*)
            ACTION="slow_down"
            echo "    ⚡ 规则兜底触发: 识别为减速指令"
            RESULT=$(python3 ~/G-Exo/omni_test/speed_controller.py "$ACTION" 2>&1 | tail -2)
            echo "    执行结果: $RESULT"
            SPEED=$(python3 ~/G-Exo/omni_test/speed_controller.py status 2>&1 | grep -o '[0-9.]* m/s' || echo "0.00 m/s")
            REPLY="好的，已为您减速，当前速度 ${SPEED}"
            ;;
    esac
fi

# ---------- 3. TTS 合成回复 ----------
echo "[3/3] TTS 合成回复..."
tts_file_demo -p "$REPLY" -l matcha:zh-en -o reply_${TS}.wav 2>&1 | grep -E "已保存|时长" || true
echo ""
echo "✅ 完成! 回复音频: reply_${TS}.wav"
echo "   文字回复: $REPLY"
