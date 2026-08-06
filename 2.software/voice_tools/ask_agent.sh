#!/bin/bash
# 在新工作空间 G-Exo/spacemit_robot 下运行的语音提问流水线
# 用法: ./ask_agent.sh "你的问题"
set -e
source ~/G-Exo/spacemit_robot/build/envsetup.sh >/dev/null 2>&1

echo "工具来源: $(which tts_file_demo asr_file_demo)"
TEXT="${1:-你好，请问今天天气怎么样？}"
TS=$(date +%H%M%S)

echo "[1/4] TTS 合成问题音频..."
tts_file_demo -p "$TEXT" -l matcha:zh-en -o qswap_${TS}.wav 2>&1 | grep -E "已保存|时长" || true

echo "[2/4] ASR 语音识别..."
ASR_TEXT=$(asr_file_demo qswap_${TS}.wav --engine qwen3-asr --endpoint http://127.0.0.1:8063/v1/chat/completions 2>&1 | grep "Extracted text" | sed 's/.*\[\(.*\)\].*/\1/')
echo "    识别文本: $ASR_TEXT"

echo "[3/4] LLM 生成回复 (Qwen3.5-4B)..."
curl -s http://127.0.0.1:9191/v1/chat/completions -H "Content-Type: application/json" \
  -d "{\"model\":\"qwen3.5-4b\",\"messages\":[{\"role\":\"system\",\"content\":\"你是嵌入式开发板上的语音助手，请用中文简短回答，不超过50字。\"},{\"role\":\"user\",\"content\":\"$ASR_TEXT\"}],\"max_tokens\":150,\"chat_template_kwargs\":{\"enable_thinking\":false}}" \
  > qswap_resp_${TS}.json
REPLY=$(python3 -c "import json,sys; print(json.load(open('qswap_resp_${TS}.json'))['choices'][0]['message']['content'])")
echo "    回复内容: $REPLY"

echo "[4/4] TTS 合成回复音频..."
tts_file_demo -p "$REPLY" -l matcha:zh-en -o qswap_reply_${TS}.wav 2>&1 | grep -E "已保存|时长" || true

echo ""
echo "✅ 完成! 问题音频: qswap_${TS}.wav  回复音频: qswap_reply_${TS}.wav"
ls -la qswap_${TS}.wav qswap_reply_${TS}.wav
