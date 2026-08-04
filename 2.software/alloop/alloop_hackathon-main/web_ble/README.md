# Alloop Kit Bridge Console

Windows 单文件网页客户端。默认通过同一局域网连接 Android App 提供的 WebSocket 桥接；原有 Web Bluetooth 直连保留为受限诊断模式。

## 阶段 5 能力

- 默认连接 `ws://<ANDROID_LAN_IP>:8766/ws`
- 使用 Android 页面每次启动服务时生成的四位数字临时令牌认证
- 支持 `ping` 和 `getBridgeState`
- 请求 ID 关联、8 秒超时、断线时清理全部待处理请求
- 明确区分网页到 Android、Android 到戒指、当前任务三层状态
- Web Bluetooth 诊断工具仅在手动切换模式后显示
- 通过 Android SDK 扫描戒指并实时显示名称、RSSI 和 SDK `deviceId`
- 只允许连接本次 Android 扫描返回的设备 ID
- 网页发起连接/断开，由 Android SDK 完成绑定、Notify 和认证
- 接收 `scanState`、`deviceDiscovered` 和 `connectionState` 事件
- 网页重连时重放最近设备与连接状态，已连接戒指无需再次广播即可恢复列表
- 通过 `getDeviceInfo` 展示固件版本、电量、设备状态和三类历史数据标志
- 接收并缓存 `deviceStatus` 推送，网页重连时恢复最近状态
- 戒指断开后清除固件并隐藏电量、状态和历史标志，避免显示过期数据
- Android SDK 公开的 `LiteDeviceInfo` 不含 System ID，桥接模式明确显示不可用
- 通过 `syncHistory` 同步 Measurement、Sport 和 Activity 历史记录
- 接收 `historyProgress`、`historyRecord` 和历史 `bridgeError` 事件
- 每轮同步使用稳定 `syncId`，网页按 `syncId + type + index` 去重
- 网页断开时 Android 继续同步；重新认证后重放本轮事件并补齐缺失记录
- 表格最多显示 200 行，但三类 CSV 均导出本轮完整记录
- 同步错误保留已接收记录；官方 SDK 不支持取消历史同步
- 通过官方 SDK 启动和停止 SpO2 验证测量
- 接收 `spo2Result`、`ppgWave` 和 `accWave` 实时事件
- PPG/ACC 保持官方包边界批量传输，不逐采样点发送 WebSocket 消息
- 每个波形通道只保留最近 1500 个采样点，统计文本最多每 250 ms 更新一次
- Bridge 短暂断开不停止 Android SDK 测量；重连后从 `activeOperation` 恢复测量状态

## 运行

在本目录启动静态服务器：

```powershell
python -m http.server 8000
```

使用 Windows Chrome 或 Edge 访问：

```text
http://localhost:8000
```

不要通过 HTTPS 托管当前页面。HTTPS 页面会阻止访问 Android 提供的明文 `ws://` 局域网服务。

## 连接 Android Bridge

1. 确保 Android 手机和 Windows 电脑位于同一可信局域网。
2. 在 Android App 首页打开 `Web Bridge`。
3. 启动 Bridge service，并保持 App 在前台。
4. 将 Android 页面显示的 IPv4 地址和四位数字临时令牌输入网页。
5. 点击“连接 Android”。网页会依次完成 WebSocket 建连、令牌认证、`ping` 和状态恢复。
6. 等待 Android SDK 扫描结果出现，点击目标戒指旁的“连接”。
7. 首次连接时在手机上接受系统配对提示；网页收到 `connected` 事件后才会显示戒指已连接。

如果无法连接，请检查 IP、令牌、Windows 防火墙和路由器 AP 隔离。服务每次重新启动都会生成新的四位数字令牌。该令牌仅适用于可信局域网，不得将桥接端口暴露到公网。

## WebSocket 契约

建立连接后的第一条消息必须认证：

```json
{
  "id": "web-1",
  "method": "authenticate",
  "params": { "token": "ANDROID_PAGE_TOKEN" }
}
```

成功响应：

```json
{
  "id": "web-1",
  "ok": true,
  "result": { "bridgeVersion": "1.0.0" }
}
```

阶段 5 RPC：

| 方法 | 参数 | 结果 |
| --- | --- | --- |
| `authenticate` | `{ token }` | `{ bridgeVersion }` |
| `ping` | `{}` | `{ serverTime, bridgeVersion }` |
| `getBridgeState` | `{}` | 当前服务、网页、戒指和任务状态 |
| `startScan` | `{ timeoutMs?, nameFilter? }` | `null` |
| `stopScan` | `{}` | `null` |
| `connect` | `{ deviceId }` | `null`，最终结果看事件 |
| `disconnect` | `{ deviceId }` | `null` |
| `getDeviceInfo` | `{ deviceId }` | `{ firmwareVersion, batteryPercent, deviceState, hasMeasurementHistory, hasActivityHistory, hasSportHistory }` |
| `startSpo2Verification` | `{ deviceId }` | `null`，实时结果和波形通过事件发送 |
| `stopMeasurement` | `{ deviceId }` | `null` |
| `syncHistory` | `{ deviceId }` | `null`，记录和完成状态通过事件发送 |

阶段 5 事件：`scanState`、`deviceDiscovered`、`connectionState`、`deviceStatus`、`spo2Result`、`ppgWave`、`accWave`、`historyProgress`、`historyRecord`、`bridgeError`。所有设备事件中的 `deviceId` 都来自 Android SDK，不能替换为 Web Bluetooth 的浏览器私有 ID。

历史进度事件携带 `syncId` 和 `phase`（`typeStarted`、`typeCompleted`、`allCompleted`）；记录事件携带 `syncId`、`type`、`index`、`total` 和官方记录对象。历史错误事件额外携带 `operation: "syncHistory"`。共享契约样例位于 `../../contracts/history_sync_v1.json`。

网页按 `syncId + type + index` 去重并按索引排序；只有三类索引均连续且收到条数与 `allCompleted.counts` 完全一致时才显示同步完成。索引缺口、越界或同索引内容冲突会显示 `BRIDGE_HISTORY_INCOMPLETE`，已收到的部分记录仍可导出 CSV。

实时 PPG/ACC 事件在单个 `samples` 数组中携带一整个官方 SDK 包。共享契约样例位于 `../../contracts/realtime_measurement_v1.json`。

认证前调用其他方法会返回 `BRIDGE_AUTH_REQUIRED` 并关闭连接；错误令牌返回 `BRIDGE_AUTH_FAILED`。v1 同时只允许一个网页客户端。

## Web Bluetooth 诊断

诊断模式要求安全上下文和桌面 Chrome/Edge。它只承诺读取固件版本与 System ID，不承诺 Notify、认证、电量、状态、历史数据或实时测量可用，也不应被视为完整连接成功。
