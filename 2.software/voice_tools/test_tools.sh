#!/bin/bash
# 测试 llama-server function calling 能力
cd ~/G-Exo/omni_test
echo "=== 测试1: 加大速度 ==="
curl -s -X POST http://127.0.0.1:9191/v1/chat/completions \
  -H "Content-Type: application/json" --data @test_tools.json
echo ""
echo "=== 测试2: 聊天问题(无工具调用) ==="
curl -s -X POST http://127.0.0.1:9191/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.5-4b","messages":[{"role":"user","content":"你好"}],"max_tokens":100,"chat_template_kwargs":{"enable_thinking":false},"tools":[{"type":"function","function":{"name":"set_speed","description":"调整机器人速度","parameters":{"type":"object","properties":{"action":{"type":"string","enum":["speed_up","slow_down","stop"]},"amount":{"type":"number"}},"required":["action"]}}}]}'
echo ""
