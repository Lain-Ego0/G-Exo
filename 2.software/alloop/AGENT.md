# Alloop Android BLE Bridge + Windows Web 开发规范

## 1. 目标与结论

本项目的目标是在 Windows Chrome/Edge 网页中操作 Alloop 戒指，并获得完整数据：

- 固件版本与 System ID
- 电量、设备状态、历史数据标志
- 历史 Measurement / Sport / Activity 数据
- SpO2、PPG、ACC 实时数据

完整功能采用以下架构：

```text
Alloop 戒指
    | BLE
    v
Android App（官方 AlloopCore AAR）
    | WebSocket（同一局域网）
    v
Windows Chrome/Edge 网页
```

不得把“先在 Windows 设置中手动配对戒指”作为正式方案。官方 Android SDK 会在连接流程内检查绑定状态并调用 Android `createBond()`；Web Bluetooth 没有等价 API，而且该戒指可能无法通过 Windows 设置独立完成配对。

纯 Web Bluetooth 只能作为受限诊断通道。当前已确认它能读取固件版本和 System ID，但在 Windows 的 `startNotifications()` / CCCD 阶段返回 `Connection already in progress`，无法进入 SM3 认证，因此无法取得电量、状态和历史标志。

## 2. 代码库职责

### `code/`

官方 Flutter/Android 仓库，负责 Android BLE 桥接服务：

- 继续使用 `packages/alloop_blue_lite` 和官方闭源 `core-1.0.0.aar`。
- 不修改、重打包或移植官方 AAR。
- 新功能放在 `code/lib/features/web_bridge/`，遵循官方 `data/domain/presentation` 分层。
- 通过 `AlloopBlueLite.instance` 的公开 Dart API 操作戒指。
- Android 负责扫描、连接、绑定、Notify、认证、协议解析和数据同步。

### `alloop_hackathon-main/`

Windows 网页端，负责界面、操作和数据展示：

- 继续迭代现有 `web_ble/index.html`。
- 新增 Android WebSocket 桥接传输层，并将其作为默认完整连接方式。
- 保留 Web Bluetooth，但明确标记为“诊断模式”；只展示实际读取成功的固件版本和 System ID。
- 桥接模式下不得在网页重复实现或发送 `0x01`、`0x02`、`0x4B` 等底层协议帧，协议由官方 Android SDK 负责。

两个目录保持独立，通过本文定义的 WebSocket 协议协作。不要把网页迁入官方仓库，也不要把 Android SDK 复制进网页仓库。

## 3. 已确认的官方实现事实

- `alloop_blue_lite` 是 Android-only Flutter 插件；其 `pubspec.yaml` 只注册 `android` 平台。
- Dart 层通过 MethodChannel/EventChannel 调用 Android `AlloopBlueLitePlugin.kt`。
- 真正 BLE 状态机位于闭源 AAR：
  `code/packages/alloop_blue_lite/android/repo/com/alloop/core/1.0.0/core-1.0.0.aar`。
- AAR 的连接顺序为：GATT 连接、发现服务、读取 System ID、读取固件、尝试 MTU 512、检查绑定并在需要时调用 `createBond()`、设置 Notify、认证。
- MTU 512 不是强制条件；官方实现请求失败或 3 秒超时后会使用默认 MTU继续。
- 电量、设备状态和历史标志来自 Notify/SM3 认证后的响应，不是 Device Information Service 的可读特征。
- 官方公开 API 和错误码以 `code/README.zh-CN.md` 为准，不凭网页端猜测修改协议。

## 4. Android 桥接设计

### 4.1 模块结构

```text
code/lib/features/web_bridge/
  data/
    bridge_server.dart
    bridge_rpc_router.dart
    alloop_bridge_adapter.dart
  domain/
    bridge_message.dart
    bridge_state.dart
  presentation/
    controllers/web_bridge_controller.dart
    pages/web_bridge_page.dart
    widgets/bridge_status_panel.dart
```

具体文件可按官方仓库现有命名模式调整，但模块边界不得改变：服务器和 SDK 适配属于 data，消息与状态属于 domain，页面与控制器属于 presentation。

### 4.2 服务运行方式

- 使用 Dart `HttpServer.bind(InternetAddress.anyIPv4, 8766)`。
- `/ws` 使用 `WebSocketTransformer.upgrade` 建立 WebSocket。
- 默认地址为 `ws://<ANDROID_LAN_IP>:8766/ws`。
- Android 与 Windows 必须处于同一局域网；需在 UI 中提示 AP 隔离会导致不可达。
- v1 只允许一个网页客户端和一个戒指连接。
- Android 页面提供：服务开关、局域网 IP、端口、临时令牌、网页连接状态、戒指连接状态和最近错误。
- App 进入后台后必须用 Android 前台服务维持 BLE 与 WebSocket；在前台服务完成前，UI 要明确提示桥接只在 App 前台可靠运行。

### 4.3 Android SDK 映射

桥接层只调用以下官方能力：

- `initialize()`
- `startScan()` / `stopScan()`
- `connect(deviceId)` / `disconnect(deviceId)`
- `getDeviceInfo(deviceId)`
- `queryDeviceStatus(deviceId)`
- `startSpo2Verification(deviceId)` / `stopMeasurement(deviceId)`
- `syncHistory(deviceId)`
- 对应的 scan、connection、deviceStatus、spo2、ppg、acc、history Streams

桥接层不得绕过 SDK 直接访问 Android GATT，也不得复制网页端逆向协议到 Android。

## 5. WebSocket 协议

### 5.1 通用请求

```json
{
  "id": "req-17",
  "method": "connect",
  "params": {
    "deviceId": "sdk-scan-result-id"
  }
}
```

- `id`：客户端生成的唯一字符串，用于关联响应。
- `method`：本文规定的方法名。
- `params`：对象；无参数时使用空对象 `{}`。

成功响应：

```json
{
  "id": "req-17",
  "ok": true,
  "result": null
}
```

失败响应：

```json
{
  "id": "req-17",
  "ok": false,
  "error": {
    "code": "NOTIFY_SETUP_FAILED",
    "message": "Setting up notifications failed"
  }
}
```

`error.code` 必须保留官方 `AlloopBlueLiteException.code`；未知错误使用 `BRIDGE_INTERNAL_ERROR`。不得只把错误压缩成“连接失败”。

### 5.2 v1 方法

| 方法 | 参数 | 结果 |
| --- | --- | --- |
| `authenticate` | `{ token }` | `{ bridgeVersion }`，且必须是 WebSocket 建连后的第一条请求 |
| `ping` | `{}` | `{ serverTime, bridgeVersion }` |
| `getBridgeState` | `{}` | 当前服务、客户端和戒指状态 |
| `startScan` | `{ timeoutMs?, nameFilter? }` | `null` |
| `stopScan` | `{}` | `null` |
| `connect` | `{ deviceId }` | `null`，最终状态看事件 |
| `disconnect` | `{ deviceId }` | `null` |
| `getDeviceInfo` | `{ deviceId }` | 官方设备信息对象 |
| `queryDeviceStatus` | `{ deviceId }` | 官方设备状态对象 |
| `startSpo2Verification` | `{ deviceId }` | `null` |
| `stopMeasurement` | `{ deviceId }` | `null` |
| `syncHistory` | `{ deviceId }` | `null`，记录与进度看事件 |

`deviceId` 必须来自本次 Android SDK 扫描结果，网页不得使用 Web Bluetooth 的 Origin-specific `BluetoothDevice.id`。

### 5.3 事件

```json
{
  "event": "deviceStatus",
  "data": {
    "deviceId": "sdk-scan-result-id",
    "battery": 82,
    "state": 1,
    "hasMeasurement": true,
    "hasActivity": false,
    "hasSport": true
  }
}
```

必须支持：

- `scanState`
- `deviceDiscovered`
- `connectionState`
- `deviceStatus`
- `spo2Result`
- `ppgWave`
- `accWave`
- `historyProgress`
- `historyRecord`
- `bridgeError`

阶段 4 的历史事件字段固定如下：

- `historyProgress`：`{ deviceId, syncId, phase, type?, total?, count?, counts? }`；`phase` 为 `typeStarted`、`typeCompleted` 或 `allCompleted`。
- `historyRecord`：`{ deviceId, syncId, type, index, total, record }`；`record` 保持官方 Measurement / Sport / Activity model 字段。
- 历史同步失败继续使用 `bridgeError`，并携带 `{ deviceId, syncId, operation: "syncHistory", code, message }`。

Android 端必须缓存当前或最近一轮历史同步事件。网页断开不能取消 SDK 同步；重新认证后按原顺序重放缓存事件。网页使用 `syncId + type + index` 对记录去重，新 `syncId` 才能清空上一轮数据。官方 SDK 未提供历史同步取消接口，因此 v1 不增加取消 RPC。

字段命名优先保持官方 Dart model 的语义。所有事件都携带 `deviceId`，即使 v1 只支持单戒指。

PPG/ACC 不得逐采样点发送。Android 端按 50-100 ms 或官方每包边界批量发送数组；如果 JSON 性能不足，再在后续版本引入二进制帧，v1 不提前增加 MessagePack 等依赖。

阶段 5 的实时事件字段固定如下：

- `spo2Result`：`{ deviceId, spo2, hr, success, isVerified, measuredAt? }`。
- `ppgWave`：`{ deviceId, packCount, captureTime, samples }`，`samples` 保持官方每包边界，每项为 `{ ledG, ledGAmb, ledRedAmb, ledIr }`。
- `accWave`：`{ deviceId, packCount, captureTime, samples }`，`samples` 保持官方每包边界，每项为 `{ x, y, z }`。
- 实时波形事件不进入重连快照；网页仅保留固定长度显示窗口，避免测量时内存随运行时间增长。

## 6. 网页传输层

网页建立统一接口，UI 不直接依赖 WebSocket 或 Web Bluetooth：

```js
class RingTransport {
  scan() {}
  connect(deviceId) {}
  disconnect(deviceId) {}
  getDeviceInfo(deviceId) {}
  queryDeviceStatus(deviceId) {}
  startSpo2Verification(deviceId) {}
  stopMeasurement(deviceId) {}
  syncHistory(deviceId) {}
  onEvent(handler) {}
}
```

实现：

- `AndroidBridgeTransport`：默认完整模式，连接 Android WebSocket。
- `WebBluetoothTransport`：受限诊断模式，只承诺固件版本和 System ID。

网页增加连接方式切换、Android IP、端口、令牌和桥接连接状态。连接桥接后，设备列表来自 Android 扫描事件。

页面仅在收到已认证/已连接状态和相应字段后显示电量、设备状态、历史标志及操作区。未知字段必须隐藏或显示“不可用”，不得伪造默认值。

## 7. 安全约束

- Android 桥接服务每次启动生成新的四位数字临时令牌（`0000`-`9999`）。这是用户为简化真机输入明确指定的可信局域网方案，不得用于公网暴露。
- WebSocket 建连时通过查询参数或首条认证消息提交令牌；推荐首条认证消息，避免令牌进入访问日志。
- 未认证客户端不能调用任何戒指方法，也不能订阅数据。
- 默认只监听局域网 IPv4，不开放公网端口，不实现云转发。
- v1 允许明文 `ws://`，前提是可信本地局域网和临时令牌。
- 若网页部署为 HTTPS，浏览器会阻止 `ws://` 混合内容；届时必须使用 `wss://` 或 Windows localhost 代理。
- 服务停止、令牌刷新或 App 退出时关闭全部 WebSocket，并按用户设置决定是否断开戒指。

## 8. 状态与错误处理

必须区分三层状态：

1. 网页到 Android 桥接是否连接。
2. Android SDK 到戒指是否连接和认证完成。
3. 当前测量或历史同步任务是否运行。

网络断开不等于戒指断开。网页重连桥接后首先调用 `getBridgeState` 恢复状态，不应盲目重新连接戒指。

Android SDK 错误原样映射。网页日志同时展示 RPC 方法、官方错误码和可读说明。`NOTIFY_SETUP_FAILED`、`AUTH_FAILED`、`CONNECT_TIMEOUT` 等不得统一包装为 Windows GATT 133。

同一时间只允许一个互斥操作：连接、测量启动/停止、历史同步。冲突返回官方 `BUSY` 或桥接层 `BRIDGE_BUSY`。

## 9. 开发阶段

### 阶段 1：最小桥接

- Android WebSocket 服务、令牌、`ping`、`getBridgeState`。
- 网页 `AndroidBridgeTransport` 建连、断线和请求超时。
- 验收：Windows 网页可稳定连接 Android 10 分钟并完成 100 次 `ping`。

### 阶段 2：扫描与连接

- 映射初始化、扫描、连接、断开和连接状态事件。
- 网页用 Android 扫描结果展示戒指。
- 验收：网页发起连接后，Android SDK 完成绑定、Notify 和认证，网页显示连接成功。

### 阶段 3：设备信息与状态

- 映射 `getDeviceInfo` 和 `deviceStatusStream`。
- 验收：网页显示固件、System ID（若官方 model 提供）、电量、状态和历史标志；断线后正确隐藏动态字段。

### 阶段 4：历史同步

- 映射同步进度、三类记录、完成和错误事件。
- 网页保留现有表格和 CSV 导出。
- 验收：结果条数与官方 Android 页面一致，中断和重连不会重复或静默丢记录。

### 阶段 5：实时测量

- 映射 SpO2、PPG、ACC，批量传输波形。
- 验收：连续运行 30 分钟，无明显积压、内存持续增长或 UI 卡顿。

### 阶段 6：后台可靠性

- Android 前台服务、唤醒策略、网络切换和网页自动恢复。
- 验收：手机锁屏和 App 进入后台后仍可维持桥接；Wi-Fi 短暂断开后网页能恢复状态。

## 10. 测试要求

- Android 单元测试：RPC 解析、参数校验、错误映射、令牌认证、单客户端限制。
- 网页单元测试：请求关联、超时、断线、事件分发、状态恢复。
- 契约测试：固定 JSON 样例在 Android 和网页两端都能解析。
- 真机集成测试：扫描、首次连接、重复连接、意外断开、App 后台、历史同步、SpO2/PPG/ACC。
- 网络测试：错误 IP、错误令牌、端口占用、Wi-Fi 切换、AP 隔离、网页刷新。
- 回归测试：Web Bluetooth 诊断模式仍能读取固件和 System ID，并且不会声称完整连接成功。

## 11. 非目标与后续路线

v1 不做：

- 将 Android AAR 移植到 Windows/Web。
- 公网或云端桥接。
- 多戒指、多网页客户端并发。
- 自定义二进制 WebSocket 协议。
- 让网页直接完成 Android SDK 的底层协议状态机。

若未来必须完全取消 Android 设备，应新增独立的 .NET 8 Windows Bridge，使用 WinRT `Windows.Devices.Bluetooth` 实现扫描、配对、GATT 和完整协议。该路线无法复用闭源 AAR，工作量和设备兼容风险显著更高，但应继续遵守本文 WebSocket RPC 契约，使网页无需重写。

## 12. 开发纪律

- 修改协议或字段前，优先阅读 `code/README.zh-CN.md`、插件 Kotlin 包装层和官方 AAR 行为。
- 不把 Flutter 自动生成的 `windows/`、`web/` 目录误认为官方提供了 Windows/Web 蓝牙 SDK。
- 不删除用户已有修改，不进行无关重构。
- 每一阶段先完成契约和测试，再接 UI。
- 新增公共 RPC 方法或事件时必须同步更新本文档。
- 真机未验证的行为必须标记为假设，不得写成已确认能力。

## 13. Git 分支与推送约束

本项目的目标远程仓库固定为：

```text
https://github.com/Lain-Ego0/G-Exo.git
```

所有 Alloop 开发必须在以下分支进行：

```text
feature/alloop
```

执行要求：

1. 开始任何功能开发前，先检查当前 Git 仓库、工作区状态和远程地址，确认目标远程指向上述仓库。
2. 从合适的现有基线创建或切换到 `feature/alloop`；如果远程分支已经存在，先获取远程状态并基于该分支继续，避免创建相互冲突的历史。
3. 在修改功能代码前，先将当前开发基线提交并推送到远程 `feature/alloop`，确保远程存在可恢复的起点。
4. 此后每完成一次代码或文档改动，都必须先执行相关检查或测试，再创建内容明确、范围单一的提交，并立即推送到远程 `feature/alloop`。
5. 推送前检查提交范围，不得包含访问令牌、密钥、个人配置、构建缓存、临时文件或与当前任务无关的用户改动。
6. 禁止对 `feature/alloop` 使用强制推送、重写远程历史或删除远程分支，除非用户针对该操作明确授权。
7. 推送失败时保留本地提交，先诊断权限、网络、远程更新或冲突；不得用强制推送绕过问题。
8. 每次任务交付时报告提交哈希、推送分支、测试结果；如果未能推送，必须明确说明原因和仍待执行的动作。

推荐的提交边界是一个可独立验证的逻辑改动，而不是每次保存文件。多个文件共同完成同一个功能时可以放在同一提交中，但完成该逻辑改动后必须立即推送。
