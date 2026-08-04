[English](README.md) | 中文

# 示例数据

两个 CSV 文件，覆盖**连续 14 天**的戒指历史数据，让你无需先佩戴两周设备即可开始做可视化、
数据分析与算法开发。

| 文件 | 行数 | 间隔 | 内容 |
| --- | --- | --- | --- |
| `sample_14days_Measurement.csv` | 约 7,900 | 2.5 分钟 | 心率、HRV、血氧、呼吸率 |
| `sample_14days_Activity.csv` | 约 1,300 | 15 分钟 | 电量、步数、活跃秒数、皮肤温度 |

> **这些文件是模拟生成的**，其统计分布与时间节奏对齐真实设备采集数据，并非采自真实人体。
> 列格式与 app 在「历史数据」同步时导出的 CSV **完全一致**，因此你可以把这些文件与自己导出的
> 数据混用，并用同一套代码解析。

---

## 测量数据 — `sample_14days_Measurement.csv`

表头：`time,hr,hrv,spo2,respRate,hrSuccess,spo2Success`

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `time` | ISO8601 UTC | 例如 `2026-07-01T00:02:30.000Z` |
| `hr` | 整数 | 心率（bpm）。见下方「读取有效性标志」。 |
| `hrv` | 整数 | 心率变异性。无有效读数时为 `0`。 |
| `spo2` | 整数 | 血氧（%）。见下方「读取有效性标志」。 |
| `respRate` | 整数 | 呼吸率，**放大 10 倍存储**——`124` 表示 12.4 次/分。无效时为 `0`。 |
| `hrSuccess` | `true`/`false` | 本行 `hr` 是否为真实读数 |
| `spo2Success` | `true`/`false` | 本行 `spo2` 是否为真实读数 |

### 读取有效性标志 —— 重要

记录每 **2.5 分钟**写一条，但传感器不会在每个插槽都产出值。这与真实设备行为一致：

- **心率**约每 **5 分钟**测一次，因此约一半的行没有真实 HR。
- **血氧**约每 **15 分钟**测一次。清醒时节奏会漂移（一次心率测量可能打断它），睡眠时则稳定。

当某个插槽没有读数时，值列会填设备占位符 `18`，对应的 `*Success` 列为 `false`。

**请始终用标志位过滤，而不是用值判断**（占位符 `18` 不是真实测量值）：

```python
# Python / pandas
df = pd.read_csv('sample_14days_Measurement.csv')
# pandas 会把 true/false 列解析为真正的布尔类型，可直接用于过滤：
valid_hr = df[df.hrSuccess]['hr']            # 真实心率读数
valid_spo2 = df[df.spo2Success]['spo2']      # 真实血氧读数
resp_bpm = df[df.spo2Success]['respRate'] / 10   # respRate 放大 10 倍存储
```

```dart
// Dart —— 读取 CSV，只保留有真实心率读数的行。
// 每行格式：time,hr,hrv,spo2,respRate,hrSuccess,spo2Success
final lines = await File('sample_14days_Measurement.csv').readAsLines();
final validHr = <int>[];
for (final line in lines.skip(1)) {          // 跳过表头
  final c = line.split(',');
  if (c[5] == 'true') validHr.add(int.parse(c[1]));   // c[5]=hrSuccess, c[1]=hr
}
```

---

## 活动数据 — `sample_14days_Activity.csv`

表头：`time,batteryPercent,steps,activeSeconds,temperaturesC`

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `time` | ISO8601 UTC | 15 分钟间隔 |
| `batteryPercent` | 整数 0–100 | 戒指电量 |
| `steps` | 整数 | **本 15 分钟区间内**的步数（区间增量，不是累计值） |
| `activeSeconds` | 整数 | 本区间内的活跃秒数（0–900；900 = 整个区间） |
| `temperaturesC` | 浮点列表 | 15 个皮肤温度采样（每分钟一个），分号分隔，如 `33.4;33.5;33.2` |

```python
# 每日步数汇总
df = pd.read_csv('sample_14days_Activity.csv', parse_dates=['time'])
daily = df.groupby(df.time.dt.date)['steps'].sum()   # 每天约 7k-12k

# 皮肤温度：展开分号分隔的采样
temps = df.temperaturesC.str.split(';').explode().astype(float)
```

---

## 数据长什么样

数据内置了真实的规律，使图表与算法能产出合理结果：

- **心率昼夜节律** —— 睡眠时较低（约 58 bpm），日间较高，偶有活动峰值。有效范围 51–107。
- **血氧** —— 多在 94–99，睡眠时轻度下探。有效范围 86–99。
- **HRV** —— 与心率反向变化，睡眠时更高。范围 21–104。
- **步数** —— 集中在日间，夜间接近 0，每天约 7k–12k。
- **电量** —— 数天内递减，周期性充电回升。
- **断档** —— 戒指在充电时会离手（约 1 小时，每隔一天），因此**那些时段完全没有记录行**。
  真实同步的数据也是这样——请确保你的图表能处理缺失的时间段。

所有数值都落在生理/物理合理区间内。真实采集偶尔会含传感器毛刺（不合理的温度、超范围的心率），
这些**刻意未在此复现**，以免让你误以为是自己代码的 bug。

**联合分析两个文件：** 它们共用同一条 UTC 时间轴，但间隔不同（测量每 2.5 分钟、活动每 15 分钟）。
若要联合分析——例如「步数高的时段心率是否也偏高」——请先按 `time` 列把两者重采样/归并到同一个
时间窗（15 分钟较合适）再做 join。

> 大文件：如果你的工具处理测量文件（约 380 KB、约 7.9k 行）有压力，建议用流式/分块读取。
