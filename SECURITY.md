# Security Policy

## Supported Versions

当前仓库处于活跃开发阶段（pre-1.0），所有 main 分支提交均受支持。

## Reporting a Vulnerability

如发现安全漏洞（尤其是板载 Web Agent、语音控制、网络接口相关），请**不要公开讨论**，通过以下任一方式报告：

- GitHub Security Advisory（仓库 → Security → Report a vulnerability）
- 在 Issues 中新建带 `security` 标签的私密 issue（如已公开仓库）

我们会在 7 天内回复确认，并在修复后公开致谢（如你愿意）。

## 注意事项

- 本项目的 Web Agent（FastAPI + WebSocket）面向**局域网/板载本地**使用，默认未做公网安全加固；
  请勿直接暴露到公网。
- 任何命令执行类接口（语音控制、LLM 工具调用）均有真实硬件操作风险，改动此类代码时必须经过评审。
