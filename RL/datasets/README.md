# G-Exo 训练数据集

本目录不随仓库分发数据集本体。TCN 与 PPO 的训练/验证数据来自公开数据集，请自行下载。

> English summary: this directory does not bundle the dataset. Training/evaluation data comes from
> the public dataset released with the task-agnostic exoskeleton control work — download it from
> <https://repository.gatech.edu/entities/publication/a9341fbd-33c4-43e8-878d-a44cf9e99c75>
> (DOI [10.35090/gatech/75759](https://doi.org/10.35090/gatech/75759)).

## 数据来源

本项目使用的步态与生物关节力矩数据来自公开数据集：

- 下载地址：<https://repository.gatech.edu/entities/publication/a9341fbd-33c4-43e8-878d-a44cf9e99c75>
- 数据集主页：[Task-agnostic exoskeleton control via biological joint moment estimation — Dataset](https://www.epic.gatech.edu/task-agnostic-exoskeleton-control-via-biological-joint-moment-estimation-dataset/)（Georgia Tech EPIC Lab）
- 对应论文：Molinaro et al., *Nature* 2024 — <https://doi.org/10.1038/s41586-024-08157-7>

G-Exo 的任务无关控制范式即参考该工作，因此训练数据与该数据集同源。

## 受试者划分

仓库内的清单文件按受试者隔离训练/验证/测试集，不允许跨集泄漏；受试者编号沿用数据集原始编号（`BT15`–`BT24`）：

| 阶段 | 受试者 | 清单文件 | 用途 |
|------|--------|----------|------|
| Phase 1/2 | 训练受试者（含 BT15–BT17 作为验证） | [`../assets/datasets/phase12_manifest.json`](../assets/datasets/phase12_manifest.json)、[`phase12_variable_speed_manifest.json`](../assets/datasets/phase12_variable_speed_manifest.json) | TCN 监督预训练与标定 |
| Phase 3 | 仅 `BT18`–`BT24`，仅 `normal_walk` | [`../assets/datasets/phase3_test_manifest.json`](../assets/datasets/phase3_test_manifest.json) | 冻结测试，不参与训练、归一化、早停或选点 |

Phase 3 是最终检测集：只包含未在 Phase 1/2 出现的受试者，排除 shuffle 与 skip 步态。评测口径见
[`../TCN_PIPELINE.md`](../TCN_PIPELINE.md) 的「Phase 3 冻结测试」一节。

## 放置方式

数据体积较大，不进入版本库。设置数据根目录后，按下述约定组织：

```bash
export GEXO_DATA_ROOT='<你解压数据集的目录>'
```

脚本从 `GEXO_DATA_ROOT` 读取原始数据，处理产物写入其 `processed/` 子目录
（例如 `processed/tcn50/`、`processed/tcn50_phase3/`）。具体命令见
[`../TCN_PIPELINE.md`](../TCN_PIPELINE.md)。

## 许可

数据集版权与使用条款归原始发布方所有，本项目不附带任何再分发授权。请遵守数据集页面上的许可要求。
