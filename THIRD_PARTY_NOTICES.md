# Third-Party Notices

本项目（G-Exo）以 MIT 许可证发布（见 [LICENSE](LICENSE)），但仓库内包含的部分组件、文档与模型
由其原始版权方所有，**不随 MIT 许可证授权**。各组件版权归属如下，请在使用前确认许可条款。

## 软件组件

### Web 前端依赖（2.software/gexo_web_agent/frontend/）

前端使用 npm 管理依赖，锁定版本见 `frontend/package-lock.json`，主要依赖（均为开源许可）：

| 包 | 用途 | 许可证 |
|----|------|--------|
| react / react-dom | UI 框架 | MIT |
| lucide-react | 图标库 | ISC |
| @fontsource/barlow-condensed、@fontsource/ibm-plex-mono、@fontsource/noto-sans-sc | 字体 | OFL-1.1 / MIT |
| vite、typescript、@vitejs/plugin-react | 构建工具链 | MIT / Apache-2.0 |

### ROS2 IMU 驱动（2.software/imu_driver/）

| 组件 | 说明 | 版权 |
|------|------|------|
| `ess_imu_driver2` | 供应商 ROS2 驱动（G354 惯性导航模组） | 第三方，版权归原厂商；详见目录内说明 |
| `G354_Attitude-algorithm` | 姿态解算算法 | 第三方，版权归原厂商 |

### RL 训练框架运行时依赖（RL/）

RL 目录仅包含自有代码与设计文档；以下为运行时安装的外部依赖（不在仓库内）：

| 依赖 | 说明 | 许可证 |
|------|------|--------|
| MyoSuite | 肌肉骨骼仿真环境 | Apache-2.0 |
| MuJoCo | 物理引擎 | Apache-2.0 |
| stable-baselines3 / torch | RL 训练库 | MIT / BSD-3-Clause |

## 厂商硬件资料（4.document/、1.hardware/）

以下厂商资料随仓库分发，**仅供研究与参考，版权归各自厂商所有，请勿再分发或用于商业用途**：

| 资料 | 版权方 | 位置 |
|------|--------|------|
| K3 Pico-ITX 用户手册、原理图、PCB 图、BOM | SpaceMIT | 4.document/K3 Pico-ITX/ |
| K3 260com kit 板图（.brd）、原理图（.DSN）、手册、BOM | SpaceMIT | 4.document/K3 260com kit/ |
| K3 Pico-ITX 3D 模型 | SpaceMIT | 1.hardware/G-Exo V1/K3_PICO_ITX_260528.stp |
| RS02 / RS06 执行器使用说明书、STEP 模型 | 供应商 | 4.document/RS02/、4.document/RS06/ |
| DM-J4340-2EC 电机说明书、曲线、图纸、模型 | 供应商 | 4.document/DM-J4340-2EC/ |

## 参考论文（3.paper/）

论文版权归原作者/出版社所有，收录仅供学习参考。

## Alloop 套件（受限许可，未随仓库分发）

`2.software/alloop/` 为 Alloop 提供的黑客松套件（Dart 源代码与二进制组件 AAR）。
该套件以受限许可提供（"仅授权黑客松参赛者使用，未经书面许可不得单独再分发"），
其许可条款不包含再分发权利，因此**套件代码未随本仓库分发**（本地保留）。
使用范围说明见 [2.software/alloop/README.md](2.software/alloop/README.md)；
如获 Alloop 书面许可后希望恢复分发，请提交 Issue 讨论。
