[English](README.md) | 中文

# Alloop Kit Demo

欢迎参赛！本仓库是基于 **Alloop Kit 智能指环**的 Flutter Demo 工程，内置扫描、连接、血氧验证、历史数据同步四个核心功能，供你在此基础上二次开发。

---

## 目录

1. [产品与 Demo 简介](#1-产品与-demo-简介)
2. [环境准备](#2-环境准备)
3. [快速开始](#3-快速开始)
4. [工程结构导览](#4-工程结构导览)
5. [API 参考](#5-api-参考)
6. [代码示例](#6-代码示例)
7. [二次开发建议](#7-二次开发建议)
8. [FAQ 与注意事项](#8-faq-与注意事项)

---

## 1. 产品与 Demo 简介

**Alloop Kit** 是一款智能指环产品，具备心率、血氧（SpO2）、活动量等多种生理与运动监测能力，可通过蓝牙（BLE）与手机 App 通信，实时获取传感器数据并同步历史记录。

本 Demo 是一个裁剪版的 Flutter 测试 App（应用名 **Alloop Kit Demo**），聚焦以下四个功能：

| 功能 | 说明 |
| --- | --- |
| **扫描** | 搜索附近可连接的 Alloop Kit 设备，展示设备名称与信号强度（RSSI） |
| **连接** | 连接指定设备，在设备详情页展示连接状态与设备基础信息（固件版本、电量等）；详情页的功能入口卡片标题为 "Features" |
| **血氧验证（SpO2 Verification）** | 触发设备血氧（SpO2）测量，实时展示血氧数值 + PPG 四通道（ledG/ledGAmb/ledRedAmb/ledIr）与 ACC 三轴（x/y/z）原始波形，分 PPG / ACC 两个 Tab 分通道展示 |
| **历史数据同步** | 从设备拉取历史测量 / 活动 / 运动数据，展示同步进度与结果；该页面 UI 标题为 "History Data" |

> 界面截图：运行后可见（Demo 首次运行即可看到实际界面，此处不额外附图）。

Demo 已经帮你完成了蓝牙连接、协议解析、数据流封装等底层工作，你只需要调用简洁的 Dart 接口即可拿到结构化的数据实体，把精力集中在 **应用层创新**（可视化、算法、交互）上。

### 先阅读赛题说明

开始编码前，请先阅读 [`docs/`](docs/) 目录下的官方赛题文档：

```
docs/Physical_AI_Hackathon_Sense_and_Reason赛道_alloop赛题说明文档.zip
```

解压后可查看完整的 **「Sense and Reason」赛道**说明——赛题主题、需要构建的内容、评审标准与提交要求。**本 Demo 只是你的起步脚手架，真正决定得分的是赛题文档中的要求。**

---

## 2. 环境准备

| 项目 | 要求 |
| --- | --- |
| Flutter | 3.x stable（建议使用 `flutter --version` 确认为 stable channel） |
| IDE | Android Studio（推荐）或 VS Code + Flutter/Dart 插件 |
| Android SDK | Compile/Target SDK 34 |
| 测试设备 | **真机**，Android 8.0（API 26）及以上，且支持 BLE（Bluetooth Low Energy） |
| 硬件 | 一枚 Alloop Kit 智能指环（活动组织方提供） |

> 本 Demo 仅支持 Android 平台，不支持 iOS / 桌面端，也不支持模拟器（模拟器无法访问真实蓝牙硬件）。

### 蓝牙权限说明

Demo 已在 `AndroidManifest.xml` 中声明所需权限，首次运行时会向用户申请，请在真机弹窗中选择"允许"：

- **Android 12（API 31）及以上**：需要 `BLUETOOTH_SCAN`、`BLUETOOTH_CONNECT` 运行时权限。
- **Android 11（API 30）及以下**：BLE 扫描依赖定位权限，需要 `ACCESS_FINE_LOCATION` 运行时权限（这是 Android 系统的历史限制，与是否使用位置信息无关）。

若权限被拒绝或运行中被手动关闭，扫描/连接功能将不可用，请在系统设置中重新授予。

---

## 3. 快速开始

目标：5 分钟内跑通"扫描 + 连接"。

```bash
# 1. 解压交付包后进入工程目录
cd alloop-hackathon-demo

# 2. 拉取依赖（包含内置的设备通信 SDK，无需额外配置）
flutter pub get

# 3. 用数据线连接一台 Android 真机，并确认设备已开启 USB 调试
flutter devices   # 确认真机已被识别

# 4. 运行
flutter run
```

App 启动后：

1. 打开手机蓝牙。
2. 在首页点击"Scan Devices"进入扫描页，扫描会自动开始，等待你的 Alloop Kit 设备出现在列表中（需要重新扫描时可点击"Start Scan"）。
3. 点击设备进入详情页，点击"Connect"连接。
4. 连接成功后，通过"Features"卡片进入血氧验证（SpO2 Verification）或历史数据（History Data）页面。

---

## 4. 工程结构导览

```
lib/
├── main.dart       # 应用入口
├── core/           # 通用工具（文件、权限、CSV、状态转换等）
├── features/       # 业务功能模块（按 Clean Architecture 分层）
│   ├── main/                  # 启动页与主导航
│   ├── scan/                  # 设备扫描
│   ├── device_detail/         # 设备详情 / 连接管理
│   ├── algorithm_verify/      # 血氧算法验证（数值 + PPG/ACC 波形）
│   ├── history_sync_debug/    # 历史数据同步
│   └── common/                # 跨功能共享的设备状态管理
├── foundations/    # 基础设施封装（日志、导航、错误处理、UI 提示）
└── widgets/        # 可复用 UI 组件（如实时波形图表）

packages/
└── alloop_blue_lite/   # 设备通信 SDK（Flutter 插件）
```

每个 `features/xxx` 模块内部遵循统一分层：

- `data/`：数据源与仓库（Repository），负责调用 SDK
- `domain/`：模型定义
- `presentation/`：GetX Controller + 页面 + 组件

### `packages/alloop_blue_lite` 是什么

这是本 Demo 内置的**设备通信 SDK**，以 Flutter 插件的形式提供。它的核心实现是一段**闭源二进制（Android AAR）**，负责与 Alloop Kit 设备的蓝牙通信、协议解析等底层细节。

对你来说，**只需要关心它暴露出来的 Dart 接口**（`AlloopBlueLite` 类及配套的数据实体/异常类型）——调用一个方法或订阅一个 Stream，就能拿到结构化的业务数据（如 `Spo2Result`、`PpgWave`），完全不需要、也无法接触底层通信细节。二次开发时，请把改造精力放在 `lib/features/` 这一层。

---

## 5. API 参考

所有类型均由 `import 'package:alloop_blue_lite/alloop_blue_lite.dart';` 导出。入口是单例 `AlloopBlueLite.instance`。

### 5.1 `AlloopBlueLite` 方法一览

| 方法 | 参数 | 返回 | 说明 |
| --- | --- | --- | --- |
| `initialize()` | 无 | `Future<void>` | 初始化底层通信模块，需在其他方法调用前执行一次 |
| `startScan()` | `Duration? timeout`, `String? nameFilter` | `Future<void>` | 开始扫描附近设备；`timeout` 到时自动停止；`nameFilter` 按设备名过滤 |
| `stopScan()` | 无 | `Future<void>` | 停止扫描 |
| `deviceDiscoveredStream` | — | `Stream<LiteDevice>` | 扫描期间每发现一个设备触发一次 |
| `isScanningStream` | — | `Stream<bool>` | 扫描状态变化 |
| `isScanning` | — | `bool` | 当前是否正在扫描（同步读取） |
| `connect(deviceId)` | `String deviceId` | `Future<void>` | 连接指定设备；连接过程与结果通过 `connectionStateStream` 获取 |
| `disconnect(deviceId)` | `String deviceId` | `Future<void>` | 断开指定设备 |
| `connectedDevicesStream` | — | `Stream<List<LiteDevice>>` | 当前已连接设备列表（本 Demo 限单设备，列表长度为 0 或 1） |
| `connectionStateStream(deviceId)` | `String deviceId` | `Stream<LiteConnectionState>` | 指定设备的连接状态变化 |
| `getDeviceInfo(deviceId)` | `String deviceId` | `Future<LiteDeviceInfo>` | 查询设备静态信息（固件版本、电量、设备状态） |
| `queryDeviceStatus(deviceId)` | `String deviceId` | `Future<LiteDeviceStatus>` | 主动查询一次设备状态。**注意**：查询设备状态会同时触发设备开始上报历史数据，页面展示状态请改用 `deviceStatusStream`；只有同步类流程才需要直接调用它，`syncHistory` 内部已经会触发一次，不要在同步前重复调用 |
| `deviceStatusStream(deviceId)` | `String deviceId` | `Stream<LiteDeviceStatus>` | 设备状态持续更新（电量、状态码、历史数据可同步类型变化），推荐所有页面展示状态时使用此流，而不是 `queryDeviceStatus` |
| `startSpo2Verification(deviceId)` | `String deviceId` | `Future<void>` | 启动血氧验证测量 |
| `stopMeasurement(deviceId)` | `String deviceId` | `Future<void>` | 停止当前测量 |
| `spo2ResultStream(deviceId)` | `String deviceId` | `Stream<Spo2Result>` | 血氧测量结果（数值） |
| `ppgWaveStream(deviceId)` | `String deviceId` | `Stream<PpgWave>` | 血氧测量期间的原始 PPG 波形数据，供可视化或自定义算法使用 |
| `accStream(deviceId)` | `String deviceId` | `Stream<AccWave>` | 血氧测量期间的原始 ACC 三轴加速度波形，供可视化或自定义算法使用 |
| `syncHistory(deviceId)` | `String deviceId` | `Stream<HistorySyncEvent>` | 触发一次历史数据同步，返回进度事件流，同步结束（成功或失败）后自动关闭 |

> 注：`deviceId` 均以 `startScan` 发现的 `LiteDevice.id` 为准。

### 5.2 数据实体字段表

**`LiteDevice`**（扫描发现的设备）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `String` | 设备唯一标识，用于后续 `connect`/`disconnect` 等调用 |
| `name` | `String` | 设备广播名称 |
| `rssi` | `int` | 信号强度，单位 dBm |

**`LiteConnectionState`**（连接状态）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `state` | `LiteConnectionStateValue` | 枚举：`connecting` / `connected` / `disconnected` |
| `errorCode` | `String?` | 当 `state == disconnected` 且因异常断开时携带的错误码（见 5.3） |

**`LiteDeviceInfo`**（设备静态信息）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `firmwareVersion` | `String` | 固件版本号 |
| `batteryPercent` | `int` | 电量百分比，范围 0~100 |
| `deviceState` | `int` | 设备状态码（业务含义参见 App 内展示文案） |
| `hasMeasurementHistory` | `bool` | 设备是否有测量数据（心率/血氧）待同步 |
| `hasActivityHistory` | `bool` | 设备是否有活动数据待同步 |
| `hasSportHistory` | `bool` | 设备是否有运动数据待同步 |

**`LiteDeviceStatus`**（设备动态状态）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `batteryPercent` | `int` | 电量百分比，范围 0~100 |
| `deviceState` | `int` | 设备状态码 |
| `hasMeasurementHistory` | `bool` | 设备是否有测量数据（心率/血氧）待同步 |
| `hasActivityHistory` | `bool` | 设备是否有活动数据待同步 |
| `hasSportHistory` | `bool` | 设备是否有运动数据待同步 |

**`Spo2Result`**（血氧结果，涵盖实时测量与最终结果两种来源，用 `isVerified` 区分）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `spo2` | `int?` | 血氧饱和度，单位 %，范围 0~100 |
| `hr` | `int?` | 心率，单位 bpm（仅部分来源携带） |
| `success` | `bool?` | 本次读数是否被设备判定为有效 |
| `measuredAt` | `DateTime?` | 测量时间（标准 UTC 时间，仅部分来源携带） |
| `isVerified` | `bool` | `true` 表示带时间戳的验证采样，`false` 表示实时测量结果 |

**`PpgWave`**（一批 PPG 原始波形采样）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `packCount` | `int` | 包序号，可用于检测丢包 |
| `captureTime` | `int` | 采集时间戳，标准 Unix 秒 |
| `samples` | `List<PpgSample>` | 本批次的采样点列表 |

`PpgSample` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ledG` | `int` | 绿光通道原始值，20-bit 有符号整数，范围 -524288 ~ +524287，采样率 100Hz |
| `ledGAmb` | `int` | 绿光环境光通道原始值，范围同上 |
| `ledRedAmb` | `int` | 红光环境光通道原始值，范围同上 |
| `ledIr` | `int` | 红外光通道原始值，范围同上 |

**`AccWave`**（一批 ACC 原始加速度采样）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `packCount` | `int` | 数据包序号，可用于检测丢包 |
| `captureTime` | `int` | 采样时间基准序号 |
| `samples` | `List<AccSample3>` | 本包的采样点列表 |

`AccSample3` 字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `x` | `int` | 加速度 X 轴分量，范围 -7995 ~ +7995，采样率约 25Hz |
| `y` | `int` | 加速度 Y 轴分量，范围同上 |
| `z` | `int` | 加速度 Z 轴分量，范围同上 |

**`HistorySyncEvent`**（历史同步过程事件，密封类型，用 `switch` 模式匹配处理）

| 子类型 | 关键字段 | 说明 |
| --- | --- | --- |
| `HistoryTypeStarted` | `type`（`measurement`/`sport`/`activity`）, `total`（预计条数，可能为 `null`） | 某类历史数据开始同步 |
| `HistoryRecordReceived` | `type`, `record`（见下）, `index`, `total` | 收到一条记录 |
| `HistoryTypeCompleted` | `type`, `count` | 某类历史数据同步完成，`count` 为实际条数 |
| `HistoryAllCompleted` | `counts`（`Map<String,int>`，各类型条数汇总） | 全部类型同步完成，流随之关闭 |
| `HistorySyncError` | `code`, `message` | 同步失败，流随之关闭 |

`record` 字段依据 `type` 取值为以下三种之一：

- `MeasurementRecord`：`unixSec`（Unix 秒）、`hr`（心率 bpm）、`hrv`、`spo2`（%）、`respRate`（呼吸率）、`hrSuccess`、`spo2Success`
- `SportRecord`：`unixSec`、`hr`、`steps`（步数）、`activityCount`
- `ActivityRecord`：`unixSec`、`batteryPercent`（%）、`steps`、`activeSeconds`（活动秒数）、`temperaturesC`（`List<double>`，摄氏度）

> 所有时间戳字段均为**标准 Unix 秒/毫秒**（`unixSec` 为秒，`measuredAt`/`DateTime` 系列已转换为标准时间对象），无需自行换算纪元。

**历史同步完成后的 CSV 导出与分享**（`history_sync_debug` 模块）

同步结束（完成或中途出错但已收到部分数据）后，Demo 会自动把已接收到的记录按类型写出为 CSV 文件，路径为：

```
<用户可访问目录>/history_sync/history_<yyyy-MM-dd_HH-mm-ss>_<Type>.csv
```

其中 `<Type>` 为 `Measurement` / `Sport` / `Activity`，只有实际收到过至少 1 条记录的类型才会生成对应文件。各类型 CSV 表头如下：

| 类型 | 表头 | 说明 |
| --- | --- | --- |
| 测量数据（Measurement） | `time,hr,hrv,spo2,respRate,hrSuccess,spo2Success` | `time` 为 ISO8601 UTC 时间字符串 |
| 运动数据（Sport） | `time,hr,steps,activityCount` | `time` 同上 |
| 活动数据（Activity） | `time,batteryPercent,steps,activeSeconds,temperaturesC` | `time` 同上；`temperaturesC` 为分号（`;`）连接的多个温度值 |

写出成功后：

- 页面「同步进度」卡片会展示导出的文件名列表，并提供「分享」按钮（基于 `share_plus` 调起系统分享面板）；
- 对应类型的本地「可同步」标志会立即清除（即状态卡片上的徽章变为"无数据"），无需等待设备下一次状态推送——但设备自身的状态推送仍是最终权威来源，如果之后收到新的推送，会覆盖这次本地更新。

**血氧验证数据导出**（`algorithm_verify` 模块）

血氧验证页顶部提供保存图标按钮（tooltip 为 "Export Data"）。点击后，本次测量收集到的数据会写入应用外部存储目录下的 `algorithm_verify/` 子目录，文件名以 `spo2_<时间戳>` 为基名（时间戳取本次测量起始时间），按数据类别生成以下 CSV（只有实际采集到对应数据的类别才会生成文件）：

| 文件 | 表头 | 说明 |
| --- | --- | --- |
| `<base>_SpO2.csv` | `timestamp,spo2,hr,success,isVerified` | 血氧数值序列，`timestamp` 为标准时间字符串 |
| `<base>_PPG.csv` | `elapsedSeconds,ledG,ledGAmb,ledRedAmb,ledIr` | PPG 四通道原始波形，`elapsedSeconds` 为测量起始的相对秒数 |
| `<base>_ACC.csv` | `timestamp,x,y,z` | ACC 三轴原始波形，其中首列为测量起始的相对秒数 |

### 5.3 错误码表

所有异常均以 `AlloopBlueLiteException(code, message)` 的形式抛出（`code` 为下表中的字符串，`message` 为英文描述，仅供调试参考，不建议展示给最终用户）。

| 错误码 | 含义 | 建议处理 |
| --- | --- | --- |
| `NOT_INITIALIZED` | 调用任何方法前必须先调用 `initialize()`  | 应用启动时调用一次 `AlloopBlueLite.instance.initialize()` |
| `BLUETOOTH_UNAVAILABLE` | 设备不支持蓝牙或蓝牙不可用 | 提示用户该设备不支持蓝牙功能 |
| `NOT_CONNECTED` | 设备未连接或已断开连接 | 提示用户重新连接设备后重试 |
| `BUSY` | 设备或 SDK 当前正忙（如测量与历史同步互斥占用中） | 提示用户稍后重试；先停止当前操作再发起新操作 |
| `CONNECT_TIMEOUT` | 连接设备超时 | 提示用户靠近设备、确认设备已开启蓝牙广播后重试 |
| `CONNECT_FAILED` | 蓝牙连接失败 | 提示用户重试；检查设备是否可用 |
| `SERVICE_DISCOVERY_FAILED` | 服务发现失败 | 重试连接；仍失败可能是设备固件问题 |
| `SERVICE_DISCOVERY_START_FAILED` | 服务发现启动失败 | 重试连接操作 |
| `POST_CONNECT_READ_FAILED` | 连接后读取设备信息失败 | 重试连接操作；确保设备正常工作 |
| `NOTIFY_SETUP_FAILED` | 设置数据通知失败 | 重试连接；可能是蓝牙配对问题 |
| `WRITE_FAILED` | 写入命令到设备失败 | 重试操作；多次失败建议重新连接 |
| `COMM_ERROR` | 设备通信异常 | 重试当前操作；联系技术支持 |
| `RING_IN_BOX` | 设备当前处于收纳盒内或类似不可测量状态 | 提示用户取出设备后重试 |
| `OFFLINE_DATA_PENDING` | 设备存在待处理的离线数据，暂不能执行本次请求 | 提示用户先完成历史数据同步 |
| `SPORT_MODE_ACTIVE` | 设备正处于运动模式，与本次请求冲突 | 提示用户退出运动模式后重试 |
| `MEASUREMENT_START_FAILED` | 测量启动失败 | 检查设备状态后重试 |
| `MEASUREMENT_STOP_FAILED` | 停止测量失败 | 重试停止操作或重新连接设备 |
| `STATUS_PARSE_FAILED` | 设备状态解析失败 | 重试查询设备状态 |
| `WORK_MODE_FAILED` | 设备工作模式切换失败 | 重试操作或重新连接设备 |
| `AUTH_FAILED` | 设备认证失败 | 检查设备固件；可能需要重新配对 |
| `CANCELLED` | 操作被取消 | 重新发起操作 |
| `COMMAND_TIMEOUT` | 命令响应超时 | 检查连接后重试 |
| `HISTORY_SYNC_FAILED` | 历史数据同步失败 | 重新发起同步；确认设备处于静置可同步状态 |
| `INVALID_ARGUMENT` | 调用参数缺失或非法 | 检查传入的 deviceId 等参数 |
| `CORE_ERROR` | 底层通信模块内部错误（未归类的兜底错误码） | 记录日志，提示用户重试；仍失败建议重启 App |

---

## 6. 代码示例

以下片段与 Demo 实际代码风格一致，展示"扫描 → 连接 → 测血氧 → 历史同步"最小可运行链路。

```dart
import 'package:alloop_blue_lite/alloop_blue_lite.dart';

final blue = AlloopBlueLite.instance;

Future<void> quickStart() async {
  // 0. 初始化（App 启动时执行一次）
  await blue.initialize();

  // 1. 扫描
  blue.deviceDiscoveredStream.listen((device) {
    print('discovered: ${device.name} (${device.id}), rssi=${device.rssi}');
  });
  await blue.startScan(timeout: const Duration(seconds: 15));

  // 假设已从扫描结果中拿到目标设备 id
  const deviceId = 'YOUR_DEVICE_ID';

  // 2. 连接
  blue.connectionStateStream(deviceId).listen((state) {
    print('connection state: ${state.state}');
  });
  await blue.connect(deviceId);

  // 3. 血氧验证：数值 + PPG 波形
  blue.spo2ResultStream(deviceId).listen((result) {
    print('spo2=${result.spo2}%, success=${result.success}');
  });
  blue.ppgWaveStream(deviceId).listen((wave) {
    print('ppg batch: packCount=${wave.packCount}, samples=${wave.samples.length}');
  });
  await blue.startSpo2Verification(deviceId);
  // ... 展示一段时间后停止
  await blue.stopMeasurement(deviceId);

  // 4. 历史数据同步
  blue.syncHistory(deviceId).listen(
    (event) {
      switch (event) {
        case HistoryTypeStarted():
          print('sync started: ${event.type}, total=${event.total}');
        case HistoryRecordReceived():
          print('record: ${event.type} #${event.index} -> ${event.record}');
        case HistoryTypeCompleted():
          print('type done: ${event.type}, count=${event.count}');
        case HistoryAllCompleted():
          print('all done: ${event.counts}');
        case HistorySyncError():
          print('sync error: ${event.code} ${event.message}');
      }
    },
    onError: (Object error) {
      if (error is AlloopBlueLiteException) {
        print('sync failed: ${error.code} ${error.message}');
      }
    },
  );
}
```

对应到 Demo 实际工程中，这些调用被封装在各功能模块的 `data/` 层仓库里，例如：

- `lib/features/scan/data/scan_repository.dart` — 扫描
- `lib/features/device_detail/data/device_detail_repository.dart` — 连接
- `lib/features/algorithm_verify/data/repositories/algorithm_verify_repository.dart` — 血氧验证
- `lib/features/history_sync_debug/presentation/controllers/history_sync_debug_controller.dart` — 历史同步

建议二次开发时优先阅读这几个文件，理解现有调用方式后再扩展。

---

## 7. 二次开发建议

Demo 只实现了最基础的展示逻辑，以下方向都值得发挥：

- **血氧 / PPG 可视化增强**：当前 `ppgWaveStream` 提供的原始波形只是简单折线展示，可以尝试更丰富的可视化（多通道叠加、频域分析、心率变异性推导等）。
- **自定义算法**：基于 `PpgWave` 原始采样，尝试自己的信号处理或算法（滤波、峰值检测、置信度评估等），与官方 `spo2ResultStream` 结果对比。测量期间还可通过 `accStream` 拿到 `AccWave` 三轴加速度数据，用于运动伪影抑制、活动识别等运动相关算法。
- **历史数据统计分析**：`syncHistory` 拉取到的 `MeasurementRecord` / `SportRecord` / `ActivityRecord` 可以做趋势图、日报周报、健康评分等二次加工。`sample_data/` 目录用于存放官方提供的连续 14 天真实佩戴历史数据 CSV（格式与 app 内历史同步导出一致）；若尚未附带，可用 app 的历史同步功能自行导出数据进行开发。
- **多设备管理 UI**：虽然本 Demo 限定单设备连接，但你可以设计更完善的设备列表管理、收藏、重命名等交互体验（受限于 SDK 单设备连接能力，多设备并发连接不在本次可发挥范围内）。
- **交互与体验优化**：连接引导流程、异常提示文案、测量过程的动效反馈等，都可能是评审关注的加分项。

### 改造切入点

- 想改**数据获取逻辑**：改各 `features/xxx/data/` 下的 repository（它们是唯一直接调用 `AlloopBlueLite` 的地方）。
- 想改**页面交互/状态管理**：改 `features/xxx/presentation/controllers/`（GetX Controller）与 `presentation/pages/`、`presentation/widgets/`。
- 想改**图表渲染**：参考 `widgets/` 下现有的实时波形图表组件。
- 想新增功能模块：参照现有 `features/xxx` 目录的三层结构（`data/domain/presentation`）新建即可，无需改动 `packages/alloop_blue_lite`。

---

## 8. FAQ 与注意事项

**Q: 扫描不到设备怎么办？**
A: 依次检查：手机蓝牙是否开启；App 是否已授予蓝牙相关权限（见第 2 节）；Android 11 及以下机型是否授予了定位权限；设备是否已开机且未被其他手机连接；靠近设备（1 米以内）重试。

**Q: 连接失败 / 连接超时怎么办？**
A: 常见原因是设备距离过远、设备已被其他手机占用、或蓝牙环境干扰较大。建议靠近设备重试；仍失败可重启蓝牙或重启 App。

**Q: 连接中途断开了，App 会自动重连吗？**
A: 不会。本 Demo 只上报断线状态（`LiteConnectionState.disconnected`），不做自动重连，需要用户在 App 内手动发起重新连接。

**Q: 可以同时连接多台设备吗？**
A: 不可以，本 Demo 及内置 SDK 仅支持单设备连接。`connectedDevicesStream` 虽然是列表类型，但同一时刻最多只有一个元素。

**Q: 测量和历史同步能同时进行吗？**
A: 不能，两者互斥。若在血氧测量进行中发起历史同步（或反之），会收到 `BUSY` 错误，请先停止当前操作再切换。设备长时间同步无数据会以 error 事件结束，提示用户稍后并保持设备静置后重试。

**Q: 出现 `CORE_ERROR` 怎么办？**
A: 这是底层通信模块的兜底错误码，代表未被具体分类的内部异常。建议先重试；持续出现可尝试重启 App 或更换设备重试，并记录日志以便复现。

**Q: 页面上展示设备状态，应该用 `queryDeviceStatus` 还是 `deviceStatusStream`？**
A: 请用 `deviceStatusStream`。查询设备状态会同时触发设备开始上报历史数据，如果页面频繁或重复调用 `queryDeviceStatus`，可能会与正常的历史同步流程冲突，导致同步卡住。`deviceStatusStream` 会在连接成功后收到一次初始状态，之后随设备主动推送持续更新，无需主动查询。只有同步相关的流程才需要 `queryDeviceStatus`，且 `syncHistory` 内部已经包含了这次触发，不要在同步前额外调用。

**Q: 历史同步完成后 CSV 文件在哪里？为什么"可同步"徽章会自动变化？**
A: CSV 文件写在 `<用户可访问目录>/history_sync/` 子目录下（Android 为应用外部存储目录，iOS 为 Files App 可见的文档目录），文件名形如 `history_2026-07-06_10-30-00_Measurement.csv`；只有本次实际收到数据的类型才会生成文件。写出成功后，页面「同步进度」卡片会列出文件名并提供「分享」按钮可直接调起系统分享面板。同时，本地会把对应类型的「可同步」标志清掉，所以状态卡片的徽章会立即变为"无数据"——这只是本地即时刷新，设备自身之后推送的状态仍会覆盖它。
