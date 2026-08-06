#!/bin/bash
# ============================================
# 文件版语音对话流水线 (无麦克风环境)
# 用法: ./voice_file_pipeline.sh "你的问题"
# 默认问题: "你好，请问今天天气怎么样？"
# ============================================
set -e
cd ~/G-Exo/omni_test
TEXT="${1:-你好，请问今天天气怎么样？}"
TS=$(date +%H%M%S)

echo "[1/4] TTS 合成问题音频..."
tts_file_demo -p "$TEXT" -l matcha:zh-en -o q_$TS.wav 2>&1 | grep -E "已保存|时长" || true

echo "[2/4] ASR 语音识别..."
ASR_TEXT=$(asr_file_demo q_$TS.wav --engine qwen3-asr --endpoint http://127.0.0.1:8063/v1/chat/completions 2>&1 | grep "Extracted text" | sed 's/.*\[\(.*\)\].*/\1/')
echo "    识别文本: $ASR_TEXT"

echo "[3/4] LLM 生成回复 (Qwen3.5-4B, 关闭思考)..."
curl -s http://127.0.0.1:9191/v1/chat/completions -H "Content-Type: application/json" \
  -d "{\"model\":\"qwen3.5-4b\",\"messages\":[{\"role\":\"system\",\"content\":\"你是嵌入式开发板上的语音助手，请用中文简短回答，不超过30字。\"},{\"role\":\"user\",\"content\":\"$ASR_TEXT\"}],\"max_tokens\":120,\"chat_template_kwargs\":{\"enable_thinking\":false}}" \
  > resp_$TS.json
REPLY=$(python3 -c "import json; print(json.load(open('resp_$TS.json'))['choices'][0]['message']['content'])")
echo "    回复内容: $REPLY"

echo "[4/4] TTS 合成回复音频..."
tts_file_demo -p "$REPLY" -l matcha:zh-en -o reply_$TS.wav 2>&1 | grep -E "已保存|时长" || true

echo ""
echo "✅ 完成! 音频文件: q_$TS.wav (问题)  reply_$TS.wav (回答)"
echo "   文字回复: $REPLY"
