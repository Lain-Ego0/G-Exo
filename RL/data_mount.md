# G-Exo 移动硬盘数据接入

## 1. 当前状态

移动硬盘已经由 Ubuntu 桌面自动挂载：

```text
设备：/dev/sda1
硬盘挂载点：/media/lenovo/艾谧My Passport
文件系统：NTFS
挂载模式：只读
```

本项目使用的数据实际位于：

```text
/media/lenovo/艾谧My Passport/昝昊林/HK_hackthon/datasets/AAA外骨骼
```

该目录已经确认：

- 目录存在；
- 当前用户可以读取；
- 当前用户不能写入。

只读状态不影响训练时读取原始数据，但禁止把缓存、预处理结果、TensorBoard 日志和模型权重写回移动硬盘。

## 2. 接入原理

这里包含三个不同概念：

1. **硬盘挂载**：Ubuntu 已经把 `/dev/sda1` 挂载到 `/media/lenovo/艾谧My Passport`，无需再次挂载其中的子目录。
2. **环境变量**：`GEXO_DATA_ROOT` 告诉程序原始数据位于哪里。
3. **符号链接**：在项目中建立一个简短、稳定的路径别名，不复制任何数据。

最终数据流为：

```text
移动硬盘原始数据（只读）
    /media/lenovo/艾谧My Passport/.../AAA外骨骼
                         │
                         ├── GEXO_DATA_ROOT
                         │
                         └── RL/assets/datasets/task_agnostic_phase3
                                      │
                                      ▼
                              训练程序只读取数据

本地工作区（可写）
    RL/cache    ← 预处理缓存、标准化参数、数据清单
    RL/output   ← checkpoint、TensorBoard、评估和回放结果
```

符号链接不是数据副本，因此不会占用第二份磁盘空间。移动硬盘拔出后链接会暂时失效，重新插入并恢复相同挂载点后会自动恢复。

## 3. 当前终端立即配置

在项目根目录执行：

```bash
cd ~/HK_hackthon

export GEXO_DATA_ROOT='/media/lenovo/艾谧My Passport/昝昊林/HK_hackthon/datasets/AAA外骨骼'
export GEXO_OUTPUT_ROOT="$HOME/HK_hackthon/RL/output"
export GEXO_CACHE_ROOT="$HOME/HK_hackthon/RL/cache"

mkdir -p "$GEXO_OUTPUT_ROOT"
mkdir -p "$GEXO_CACHE_ROOT"
mkdir -p "$HOME/HK_hackthon/RL/assets/datasets"
```

路径含有空格和中文，所有 Bash 路径与变量引用都必须放在双引号中。

## 4. 建立项目内数据入口

执行：

```bash
DATA_LINK="$HOME/HK_hackthon/RL/assets/datasets/task_agnostic_phase3"

if [ ! -e "$DATA_LINK" ] && [ ! -L "$DATA_LINK" ]; then
    ln -s "$GEXO_DATA_ROOT" "$DATA_LINK"
fi
```

检查链接实际指向：

```bash
readlink -f "$DATA_LINK"
ls -ld "$DATA_LINK"
```

预期 `readlink -f` 输出：

```text
/media/lenovo/艾谧My Passport/昝昊林/HK_hackthon/datasets/AAA外骨骼
```

## 5. 每次开发前检查

检查移动硬盘是否已挂载：

```bash
findmnt '/media/lenovo/艾谧My Passport'
```

检查数据目录：

```bash
test -d "$GEXO_DATA_ROOT" && echo "data directory exists"
test -r "$GEXO_DATA_ROOT" && echo "data directory is readable"
test -w "$GEXO_DATA_ROOT" || echo "data directory is read-only, expected"
```

检查本地输出目录：

```bash
test -w "$GEXO_OUTPUT_ROOT" && echo "output directory is writable"
test -w "$GEXO_CACHE_ROOT" && echo "cache directory is writable"
```

一次性执行全部检查：

```bash
cd ~/HK_hackthon

findmnt '/media/lenovo/艾谧My Passport' >/dev/null || {
    echo "mobile disk is not mounted"
    exit 1
}

test -r "$GEXO_DATA_ROOT" || {
    echo "dataset is not readable: $GEXO_DATA_ROOT"
    exit 1
}

test -w "$GEXO_OUTPUT_ROOT" || {
    echo "output directory is not writable: $GEXO_OUTPUT_ROOT"
    exit 1
}

echo "G-Exo data paths are ready"
```

## 6. 让环境变量长期生效

打开 Bash 配置：

```bash
nano ~/.bashrc
```

在文件末尾加入：

```bash
export GEXO_DATA_ROOT='/media/lenovo/艾谧My Passport/昝昊林/HK_hackthon/datasets/AAA外骨骼'
export GEXO_OUTPUT_ROOT="$HOME/HK_hackthon/RL/output"
export GEXO_CACHE_ROOT="$HOME/HK_hackthon/RL/cache"
```

保存后加载：

```bash
source ~/.bashrc
```

验证：

```bash
printf 'data:   %s\n' "$GEXO_DATA_ROOT"
printf 'output: %s\n' "$GEXO_OUTPUT_ROOT"
printf 'cache:  %s\n' "$GEXO_CACHE_ROOT"
```

## 7. Python 中的读取方式

代码不要写死用户名或中文绝对路径，而是读取环境变量：

```python
from pathlib import Path
import os


data_root = Path(os.environ["GEXO_DATA_ROOT"])
output_root = Path(os.environ["GEXO_OUTPUT_ROOT"])
cache_root = Path(os.environ["GEXO_CACHE_ROOT"])

if not data_root.is_dir():
    raise FileNotFoundError(
        f"Dataset directory is unavailable: {data_root}"
    )

output_root.mkdir(parents=True, exist_ok=True)
cache_root.mkdir(parents=True, exist_ok=True)
```

原始数据只能通过 `data_root` 读取。以下内容只能写到本地：

- 训练集、验证集、测试集清单；
- Z-score 均值与标准差；
- 临时窗口索引；
- TensorBoard 日志；
- checkpoint；
- 模型评估和回放结果。

## 8. 与数据集切分的关系

移动硬盘中的原始文件保持不变。训练、验证和测试拆分使用本地清单引用原始文件：

```text
RL/cache/manifests/phase3_split_v1.csv
```

清单只记录以下信息：

```text
subject_id, session_id, trial_id, relative_path, split
```

其中 `relative_path` 相对于 `GEXO_DATA_ROOT`，不能保存当前机器的完整绝对路径。这样未来改变挂载点时，只需修改环境变量，不需要重建数据清单。

## 9. 注意事项

- 不要将训练输出路径设为 `GEXO_DATA_ROOT` 的子目录。
- 不要在只读移动硬盘中建立缓存或虚拟环境。
- 不要在训练期间拔出移动硬盘。
- 不要对滑动窗口随机切分；必须先按被试或 trial 划分，再生成窗口。
- `GEXO_DATA_ROOT` 是原始数据的真实入口；项目符号链接只是方便人工浏览。
- OpenSim 动力学环境当前使用 conda 自带模型，不依赖该移动硬盘；TCN 数据预训练才会读取这里的数据。
