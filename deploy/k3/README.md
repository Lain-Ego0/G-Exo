# K3 板载部署（SpaceMIT 机器人 SDK）

G-Exo 的实机控制运行在 K3（Pico-ITX / CoM 260 Kit）上，软件基于**进迭时空机器人 SDK**（SpaceMIT Robotics K3 SDK）构建。

> 本目录只保留部署说明。SDK 是第三方代码，体积大且由 `repo` 工具管理，
> 不随本仓库分发，请按下述步骤自行同步。

## SDK 获取

官方 manifest 仓库（进迭时空机器人）：

```
https://gitee.com/spacemit-robotics/manifest.git
```

```bash
# 初始化工作区
repo init -u https://gitee.com/spacemit-robotics/manifest.git -m <manifest>
repo sync -c
```

随后按照 SDK 自带的文档（`docs/`）完成工具链配置与构建。

## 工作区结构（本地使用，不入库）

| 目录 | 说明 |
|------|------|
| `components/` | SDK 组件（agent_tools、control、model_zoo、multimedia 等） |
| `middleware/` | 中间件（ROS2 桥接等） |
| `application/` | 应用层（humanoid demo 骨架） |
| `output/` | 构建产物（可随时删除重建） |
| `.repo/` | `repo` 同步状态（可删除后重新 `repo sync`） |

## 相关资源

- K3 硬件文档：[4.document/K3 260com kit/](../../4.document/) 、[4.document/K3 Pico-ITX/](../../4.document/)
- 板载运行的上层软件（语音控制、Web Agent 等）：[2.software/](../../2.software/)
