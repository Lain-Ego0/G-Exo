# Contributing to G-Exo

感谢你考虑为 G-Exo 贡献代码！请阅读以下指引。

## 快速开始

1. **Fork 本仓库**并克隆到本地。
2. 创建功能分支：`git checkout -b feature/your-feature`。
3. 提交改动，提交信息请使用清晰的中文或英文描述。
4. 推送分支并提交 Pull Request。

## 提交 PR 前

- 确保改动不影响其他模块：本仓库是软硬件混合仓库（CAD / ROS2 / Web / RL），改动前先在
  [README](README.md) 的目录结构中确认归属模块。
- 硬件（CAD/STEP）改动请附版本说明；软件改动请保持风格一致。
- **不要提交**构建产物（`build/`、`install/`、`log/`、`__pycache__/`、`node_modules/`）与
  第三方 SDK（见 [.gitignore](.gitignore)）。
- 涉及第三方厂商资料的改动请先阅读 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md)，
  厂商资料与受限许可代码不在本仓库分发范围内。

## 分支保护

`main` 分支受保护，所有改动须通过 PR 合入，且至少 1 人评审。

## 行为准则

参与本项目即表示同意 [CODE_OF_CONDUCT](CODE_OF_CONDUCT.md)。
