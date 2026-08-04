English | [中文](README.zh-CN.md)

# Alloop Kit Demo

Welcome to the hackathon! This repository is a Flutter demo project built around the **Alloop Kit smart ring**. It ships four core features out of the box — Scan, Connect, SpO2 Verification, and History Data Sync — as a foundation for you to build on top of.

---

## Table of Contents

1. [Product & Demo Overview](#1-product--demo-overview)
2. [Prerequisites](#2-prerequisites)
3. [Quick Start](#3-quick-start)
4. [Project Structure Tour](#4-project-structure-tour)
5. [API Reference](#5-api-reference)
6. [Code Example](#6-code-example)
7. [Development Suggestions](#7-development-suggestions)
8. [FAQ & Notes](#8-faq--notes)

---

## 1. Product & Demo Overview

**Alloop Kit** is a smart ring product with multiple physiological and motion monitoring capabilities, including heart rate, blood oxygen (SpO2), and activity levels. It communicates with a phone app over Bluetooth (BLE) to acquire sensor data in real time and sync historical records.

This demo is a trimmed-down Flutter test app (app name **Alloop Kit Demo**), focused on the following four features:

| Feature | Description |
| --- | --- |
| **Scan** | Search for nearby connectable Alloop Kit devices, showing device name and signal strength (RSSI) |
| **Connect** | Connect to a selected device and, on the device detail page, display connection state and basic device info (firmware version, battery, etc.); the feature entry card on the detail page is titled "Features" |
| **SpO2 Verification** | Trigger a device blood oxygen (SpO2) measurement, showing the SpO2 value in real time along with the four raw PPG channels (ledG/ledGAmb/ledRedAmb/ledIr) and the three raw ACC axes (x/y/z), displayed per channel across two tabs: PPG / ACC |
| **History Data Sync** | Pull historical measurement / activity / sport data from the device and display sync progress and results; this page's UI title is "History Data" |

> Screenshots: visible once running (you can see the actual UI the first time the demo runs, so no extra images are included here).

The demo has already handled the low-level work for you — Bluetooth connection, protocol parsing, data stream wrapping — so you only need to call clean Dart interfaces to obtain structured data entities and can focus your energy on **application-layer innovation** (visualization, algorithms, interaction).

### Read the Challenge Brief First

Before you start coding, read the official challenge document under the [`docs/`](docs/) directory:

```
docs/Physical_AI_Hackathon_Sense_and_Reason赛道_alloop赛题说明文档.zip
```

Unzip it to read the full **"Sense and Reason" track** brief from the organizers — the challenge theme, what you are expected to build, the judging criteria, and submission requirements. **This demo is only your starting scaffold; the challenge document defines what actually wins.**

---

## 2. Prerequisites

| Item | Requirement |
| --- | --- |
| Flutter | 3.x stable (run `flutter --version` to confirm you are on the stable channel) |
| IDE | Android Studio (recommended) or VS Code with the Flutter/Dart plugins |
| Android SDK | Compile/Target SDK 34 |
| Test device | A **physical device**, Android 8.0 (API 26) or above, with BLE (Bluetooth Low Energy) support |
| Hardware | One Alloop Kit smart ring (provided by the event organizers) |

> This demo supports Android only — no iOS / desktop, and no emulators (emulators cannot access real Bluetooth hardware).

### Bluetooth Permissions

The demo already declares the required permissions in `AndroidManifest.xml` and requests them from the user on first run. Please tap "Allow" in the on-device prompts:

- **Android 12 (API 31) and above**: requires the `BLUETOOTH_SCAN` and `BLUETOOTH_CONNECT` runtime permissions.
- **Android 11 (API 30) and below**: BLE scanning depends on location permission, so the `ACCESS_FINE_LOCATION` runtime permission is required (this is a historical Android system restriction, unrelated to whether location data is actually used).

If a permission is denied or manually revoked while running, the scan/connect features will be unavailable — please re-grant it in system settings.

---

## 3. Quick Start

Goal: get "Scan + Connect" running within 5 minutes.

```bash
# 1. Unzip the delivery package and enter the project directory
cd alloop-hackathon-demo

# 2. Fetch dependencies (includes the bundled device communication SDK, no extra config needed)
flutter pub get

# 3. Connect an Android physical device via cable and confirm USB debugging is enabled
flutter devices   # confirm the physical device is recognized

# 4. Run
flutter run
```

After the app launches:

1. Turn on Bluetooth on the phone.
2. On the home page, tap "Scan Devices" to open the scan page; scanning starts automatically. Wait for your Alloop Kit device to appear in the list (tap "Start Scan" to rescan if needed).
3. Tap the device to enter the detail page, then tap "Connect".
4. Once connected, use the "Features" card to enter the SpO2 Verification or History Data page.

---

## 4. Project Structure Tour

```
lib/
├── main.dart       # Application entry point
├── core/           # Common utilities (files, permissions, CSV, state conversion, etc.)
├── features/       # Business feature modules (layered per Clean Architecture)
│   ├── main/                  # Launch page and main navigation
│   ├── scan/                  # Device scanning
│   ├── device_detail/         # Device detail / connection management
│   ├── algorithm_verify/      # SpO2 algorithm verification (values + PPG/ACC waveforms)
│   ├── history_sync_debug/    # History data sync
│   └── common/                # Cross-feature shared device status management
├── foundations/    # Infrastructure wrappers (logging, navigation, error handling, UI prompts)
└── widgets/        # Reusable UI components (e.g. real-time waveform charts)

packages/
└── alloop_blue_lite/   # Device communication SDK (Flutter plugin)
```

Each `features/xxx` module follows a consistent layering internally:

- `data/`: data sources and repositories, responsible for calling the SDK
- `domain/`: model definitions
- `presentation/`: GetX Controller + pages + widgets

### What is `packages/alloop_blue_lite`

This is the **device communication SDK** bundled with the demo, provided as a Flutter plugin. Its core implementation is a **closed-source binary (Android AAR)** that handles the low-level details of Bluetooth communication and protocol parsing with the Alloop Kit device.

For you, **you only need to care about the Dart interfaces it exposes** (the `AlloopBlueLite` class and its accompanying data entities / exception types) — call a method or subscribe to a Stream and you get structured business data (such as `Spo2Result`, `PpgWave`), with no need — and no way — to touch the low-level communication details. When building on top of the demo, focus your changes on the `lib/features/` layer.

---

## 5. API Reference

All types are exported by `import 'package:alloop_blue_lite/alloop_blue_lite.dart';`. The entry point is the singleton `AlloopBlueLite.instance`.

### 5.1 `AlloopBlueLite` Method Overview

| Method | Parameters | Returns | Description |
| --- | --- | --- | --- |
| `initialize()` | none | `Future<void>` | Initializes the low-level communication module; must be called once before any other method |
| `startScan()` | `Duration? timeout`, `String? nameFilter` | `Future<void>` | Starts scanning for nearby devices; stops automatically when `timeout` elapses; `nameFilter` filters by device name |
| `stopScan()` | none | `Future<void>` | Stops scanning |
| `deviceDiscoveredStream` | — | `Stream<LiteDevice>` | Fires once for each device discovered during scanning |
| `isScanningStream` | — | `Stream<bool>` | Scan state changes |
| `isScanning` | — | `bool` | Whether currently scanning (synchronous read) |
| `connect(deviceId)` | `String deviceId` | `Future<void>` | Connects to the specified device; connection progress and result are obtained via `connectionStateStream` |
| `disconnect(deviceId)` | `String deviceId` | `Future<void>` | Disconnects the specified device |
| `connectedDevicesStream` | — | `Stream<List<LiteDevice>>` | List of currently connected devices (this demo is limited to a single device, so the list length is 0 or 1) |
| `connectionStateStream(deviceId)` | `String deviceId` | `Stream<LiteConnectionState>` | Connection state changes for the specified device |
| `getDeviceInfo(deviceId)` | `String deviceId` | `Future<LiteDeviceInfo>` | Queries static device info (firmware version, battery, device state) |
| `queryDeviceStatus(deviceId)` | `String deviceId` | `Future<LiteDeviceStatus>` | Actively queries the device status once. **Note**: querying device status also triggers the device to start reporting history data, so for displaying status on a page use `deviceStatusStream` instead; only sync-type flows need to call this directly, and `syncHistory` already triggers it internally — do not call it again before syncing |
| `deviceStatusStream(deviceId)` | `String deviceId` | `Stream<LiteDeviceStatus>` | Continuous device status updates (battery, status code, changes to which history data types are syncable); recommended for all pages that display status, instead of `queryDeviceStatus` |
| `startSpo2Verification(deviceId)` | `String deviceId` | `Future<void>` | Starts an SpO2 verification measurement |
| `stopMeasurement(deviceId)` | `String deviceId` | `Future<void>` | Stops the current measurement |
| `spo2ResultStream(deviceId)` | `String deviceId` | `Stream<Spo2Result>` | SpO2 measurement results (values) |
| `ppgWaveStream(deviceId)` | `String deviceId` | `Stream<PpgWave>` | Raw PPG waveform data during SpO2 measurement, for visualization or custom algorithms |
| `accStream(deviceId)` | `String deviceId` | `Stream<AccWave>` | Raw three-axis ACC acceleration waveforms during SpO2 measurement, for visualization or custom algorithms |
| `syncHistory(deviceId)` | `String deviceId` | `Stream<HistorySyncEvent>` | Triggers a history data sync and returns a progress event stream; closes automatically once the sync ends (success or failure) |

> Note: `deviceId` always refers to the `LiteDevice.id` discovered via `startScan`.

### 5.2 Data Entity Field Tables

**`LiteDevice`** (device discovered during scanning)

| Field | Type | Description |
| --- | --- | --- |
| `id` | `String` | Unique device identifier, used for subsequent `connect`/`disconnect` calls |
| `name` | `String` | Device advertised name |
| `rssi` | `int` | Signal strength, in dBm |

**`LiteConnectionState`** (connection state)

| Field | Type | Description |
| --- | --- | --- |
| `state` | `LiteConnectionStateValue` | Enum: `connecting` / `connected` / `disconnected` |
| `errorCode` | `String?` | Error code carried when `state == disconnected` and the disconnection was caused by an error (see 5.3) |

**`LiteDeviceInfo`** (static device info)

| Field | Type | Description |
| --- | --- | --- |
| `firmwareVersion` | `String` | Firmware version number |
| `batteryPercent` | `int` | Battery percentage, range 0~100 |
| `deviceState` | `int` | Device state code (see the in-app display text for its business meaning) |
| `hasMeasurementHistory` | `bool` | Whether the device has measurement data (HR/SpO2) pending sync |
| `hasActivityHistory` | `bool` | Whether the device has activity data pending sync |
| `hasSportHistory` | `bool` | Whether the device has sport data pending sync |

**`LiteDeviceStatus`** (dynamic device status)

| Field | Type | Description |
| --- | --- | --- |
| `batteryPercent` | `int` | Battery percentage, range 0~100 |
| `deviceState` | `int` | Device state code |
| `hasMeasurementHistory` | `bool` | Whether the device has measurement data (HR/SpO2) pending sync |
| `hasActivityHistory` | `bool` | Whether the device has activity data pending sync |
| `hasSportHistory` | `bool` | Whether the device has sport data pending sync |

**`Spo2Result`** (SpO2 result, covering both real-time measurement and final result sources, distinguished by `isVerified`)

| Field | Type | Description |
| --- | --- | --- |
| `spo2` | `int?` | Blood oxygen saturation, in %, range 0~100 |
| `hr` | `int?` | Heart rate, in bpm (only some sources carry it) |
| `success` | `bool?` | Whether this reading was judged valid by the device |
| `measuredAt` | `DateTime?` | Measurement time (standard UTC time, only some sources carry it) |
| `isVerified` | `bool` | `true` indicates a timestamped verification sample, `false` indicates a real-time measurement result |

**`PpgWave`** (a batch of raw PPG waveform samples)

| Field | Type | Description |
| --- | --- | --- |
| `packCount` | `int` | Packet sequence number, usable for packet-loss detection |
| `captureTime` | `int` | Capture timestamp, standard Unix seconds |
| `samples` | `List<PpgSample>` | List of sample points in this batch |

`PpgSample` fields:

| Field | Type | Description |
| --- | --- | --- |
| `ledG` | `int` | Green channel raw value, 20-bit signed integer, range -524288 ~ +524287, sampling rate 100Hz |
| `ledGAmb` | `int` | Green ambient-light channel raw value, same range as above |
| `ledRedAmb` | `int` | Red ambient-light channel raw value, same range as above |
| `ledIr` | `int` | Infrared channel raw value, same range as above |

**`AccWave`** (a batch of raw ACC acceleration samples)

| Field | Type | Description |
| --- | --- | --- |
| `packCount` | `int` | Packet sequence number, usable for packet-loss detection |
| `captureTime` | `int` | Sampling time base sequence number |
| `samples` | `List<AccSample3>` | List of sample points in this packet |

`AccSample3` fields:

| Field | Type | Description |
| --- | --- | --- |
| `x` | `int` | Acceleration X-axis component, range -7995 ~ +7995, sampling rate ~25Hz |
| `y` | `int` | Acceleration Y-axis component, same range as above |
| `z` | `int` | Acceleration Z-axis component, same range as above |

**`HistorySyncEvent`** (history sync process event, a sealed type handled with `switch` pattern matching)

| Subtype | Key fields | Description |
| --- | --- | --- |
| `HistoryTypeStarted` | `type` (`measurement`/`sport`/`activity`), `total` (estimated count, may be `null`) | Sync started for a given history data type |
| `HistoryRecordReceived` | `type`, `record` (see below), `index`, `total` | A record was received |
| `HistoryTypeCompleted` | `type`, `count` | Sync completed for a given history data type; `count` is the actual number of records |
| `HistoryAllCompleted` | `counts` (`Map<String,int>`, per-type record count summary) | All types finished syncing; the stream then closes |
| `HistorySyncError` | `code`, `message` | Sync failed; the stream then closes |

The `record` field is one of the following three, depending on the value of `type`:

- `MeasurementRecord`: `unixSec` (Unix seconds), `hr` (heart rate bpm), `hrv`, `spo2` (%), `respRate` (respiratory rate), `hrSuccess`, `spo2Success`
- `SportRecord`: `unixSec`, `hr`, `steps`, `activityCount`
- `ActivityRecord`: `unixSec`, `batteryPercent` (%), `steps`, `activeSeconds` (active seconds), `temperaturesC` (`List<double>`, degrees Celsius)

> All timestamp fields are **standard Unix seconds/milliseconds** (`unixSec` is in seconds; the `measuredAt`/`DateTime` series are already converted to standard time objects), so there is no need to convert the epoch yourself.

**CSV Export and Sharing After History Sync** (`history_sync_debug` module)

Once the sync ends (whether completed, or interrupted by an error but with some data already received), the demo automatically writes the received records out to CSV files by type, at the path:

```
<user-accessible directory>/history_sync/history_<yyyy-MM-dd_HH-mm-ss>_<Type>.csv
```

where `<Type>` is `Measurement` / `Sport` / `Activity`, and a file is generated only for types that actually received at least 1 record. The CSV headers for each type are as follows:

| Type | Header | Description |
| --- | --- | --- |
| Measurement | `time,hr,hrv,spo2,respRate,hrSuccess,spo2Success` | `time` is an ISO8601 UTC time string |
| Sport | `time,hr,steps,activityCount` | `time` as above |
| Activity | `time,batteryPercent,steps,activeSeconds,temperaturesC` | `time` as above; `temperaturesC` is multiple temperature values joined by a semicolon (`;`) |

After a successful write:

- The page's "Sync Progress" card displays the list of exported file names and provides a "Share" button (based on `share_plus`, which brings up the system share sheet);
- The local "syncable" flag for the corresponding type is cleared immediately (i.e. the badge on the status card changes to "No data"), without waiting for the device's next status push — but the device's own status pushes remain the ultimate source of truth, so if a new push arrives later it will override this local update.

**SpO2 Verification Data Export** (`algorithm_verify` module)

The SpO2 verification page provides a save icon button at the top (tooltip "Export Data"). When tapped, the data collected during this measurement is written to the `algorithm_verify/` subdirectory under the app's external storage directory, with a base name of `spo2_<timestamp>` (the timestamp is the start time of this measurement). The following CSVs are generated by data category (a file is generated only for categories that actually collected data):

| File | Header | Description |
| --- | --- | --- |
| `<base>_SpO2.csv` | `timestamp,spo2,hr,success,isVerified` | SpO2 value sequence; `timestamp` is a standard time string |
| `<base>_PPG.csv` | `elapsedSeconds,ledG,ledGAmb,ledRedAmb,ledIr` | Raw four-channel PPG waveform; `elapsedSeconds` is the relative seconds from measurement start |
| `<base>_ACC.csv` | `timestamp,x,y,z` | Raw three-axis ACC waveform; the first column is the relative seconds from measurement start |

### 5.3 Error Code Table

All exceptions are thrown in the form `AlloopBlueLiteException(code, message)` (`code` is a string from the table below, `message` is an English description intended for debugging reference only and should not be shown to end users).

| Error code | Meaning | Suggested handling |
| --- | --- | --- |
| `NOT_INITIALIZED` | `initialize()` must be called before calling any method | Call `AlloopBlueLite.instance.initialize()` once at app startup |
| `BLUETOOTH_UNAVAILABLE` | The device does not support Bluetooth or Bluetooth is unavailable | Tell the user this device does not support Bluetooth |
| `NOT_CONNECTED` | The device is not connected or has been disconnected | Tell the user to reconnect the device and retry |
| `BUSY` | The device or SDK is currently busy (e.g. measurement and history sync are mutually exclusive) | Tell the user to retry later; stop the current operation before starting a new one |
| `CONNECT_TIMEOUT` | Connecting to the device timed out | Tell the user to move closer to the device, confirm it is advertising over Bluetooth, and retry |
| `CONNECT_FAILED` | Bluetooth connection failed | Tell the user to retry; check that the device is available |
| `SERVICE_DISCOVERY_FAILED` | Service discovery failed | Retry connecting; if it still fails, it may be a device firmware issue |
| `SERVICE_DISCOVERY_START_FAILED` | Service discovery failed to start | Retry the connect operation |
| `POST_CONNECT_READ_FAILED` | Reading device info after connecting failed | Retry the connect operation; ensure the device is working properly |
| `NOTIFY_SETUP_FAILED` | Setting up data notifications failed | Retry connecting; it may be a Bluetooth pairing issue |
| `WRITE_FAILED` | Writing a command to the device failed | Retry the operation; if it fails repeatedly, reconnect |
| `COMM_ERROR` | Device communication error | Retry the current operation; contact technical support |
| `RING_IN_BOX` | The device is currently in its case or a similar non-measurable state | Tell the user to take the device out and retry |
| `OFFLINE_DATA_PENDING` | The device has offline data pending and cannot execute this request for now | Tell the user to complete history data sync first |
| `SPORT_MODE_ACTIVE` | The device is in sport mode, which conflicts with this request | Tell the user to exit sport mode and retry |
| `MEASUREMENT_START_FAILED` | Measurement failed to start | Check device state and retry |
| `MEASUREMENT_STOP_FAILED` | Stopping the measurement failed | Retry the stop operation or reconnect the device |
| `STATUS_PARSE_FAILED` | Parsing device status failed | Retry querying device status |
| `WORK_MODE_FAILED` | Switching the device work mode failed | Retry the operation or reconnect the device |
| `AUTH_FAILED` | Device authentication failed | Check device firmware; re-pairing may be required |
| `CANCELLED` | The operation was cancelled | Start the operation again |
| `COMMAND_TIMEOUT` | Command response timed out | Check the connection and retry |
| `HISTORY_SYNC_FAILED` | History data sync failed | Start the sync again; confirm the device is at rest and syncable |
| `INVALID_ARGUMENT` | A call argument is missing or invalid | Check the passed `deviceId` and other arguments |
| `CORE_ERROR` | Internal error in the low-level communication module (uncategorized fallback error code) | Log it and tell the user to retry; if it persists, restart the app |

---

## 6. Code Example

The snippet below matches the actual code style of the demo, showing a minimal runnable chain of "scan → connect → measure SpO2 → history sync".

```dart
import 'package:alloop_blue_lite/alloop_blue_lite.dart';

final blue = AlloopBlueLite.instance;

Future<void> quickStart() async {
  // 0. Initialize (run once at app startup)
  await blue.initialize();

  // 1. Scan
  blue.deviceDiscoveredStream.listen((device) {
    print('discovered: ${device.name} (${device.id}), rssi=${device.rssi}');
  });
  await blue.startScan(timeout: const Duration(seconds: 15));

  // Assume the target device id has been obtained from the scan results
  const deviceId = 'YOUR_DEVICE_ID';

  // 2. Connect
  blue.connectionStateStream(deviceId).listen((state) {
    print('connection state: ${state.state}');
  });
  await blue.connect(deviceId);

  // 3. SpO2 verification: value + PPG waveform
  blue.spo2ResultStream(deviceId).listen((result) {
    print('spo2=${result.spo2}%, success=${result.success}');
  });
  blue.ppgWaveStream(deviceId).listen((wave) {
    print('ppg batch: packCount=${wave.packCount}, samples=${wave.samples.length}');
  });
  await blue.startSpo2Verification(deviceId);
  // ... display for a while, then stop
  await blue.stopMeasurement(deviceId);

  // 4. History data sync
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

In the actual demo project, these calls are wrapped inside the `data/` layer repositories of each feature module, for example:

- `lib/features/scan/data/scan_repository.dart` — Scan
- `lib/features/device_detail/data/device_detail_repository.dart` — Connect
- `lib/features/algorithm_verify/data/repositories/algorithm_verify_repository.dart` — SpO2 verification
- `lib/features/history_sync_debug/presentation/controllers/history_sync_debug_controller.dart` — History sync

When building on top of the demo, we recommend reading these files first to understand the existing call patterns before extending them.

---

## 7. Development Suggestions

The demo only implements the most basic display logic. The following directions are all worth exploring:

- **SpO2 / PPG visualization enhancements**: the raw waveforms currently provided by `ppgWaveStream` are shown as simple line charts — try richer visualizations (multi-channel overlays, frequency-domain analysis, heart rate variability derivation, etc.).
- **Custom algorithms**: based on the raw `PpgWave` samples, try your own signal processing or algorithms (filtering, peak detection, confidence estimation, etc.) and compare against the official `spo2ResultStream` results. During measurement you can also obtain three-axis `AccWave` acceleration data via `accStream`, useful for motion-related algorithms such as motion-artifact suppression and activity recognition.
- **Historical data statistics & analysis**: the `MeasurementRecord` / `SportRecord` / `ActivityRecord` pulled by `syncHistory` can be processed into trend charts, daily/weekly reports, health scores, and more. The `sample_data/` directory is intended to hold officially provided real 14-day continuous wear history data CSVs (in the same format as the app's history sync export); if it is not yet included, you can use the app's history sync feature to export data yourself for development.
- **Multi-device management UI**: although this demo is limited to a single-device connection, you can design a more complete device list management, favorites, rename, and other interaction experiences (limited by the SDK's single-device connection capability, concurrent multi-device connections are out of scope for this event).
- **Interaction & experience improvements**: connection onboarding flows, error prompt wording, animated feedback during measurement, etc. — all of these may be bonus points that judges look at.

### Modification Entry Points

- To change **data acquisition logic**: modify the repository under each `features/xxx/data/` (they are the only places that call `AlloopBlueLite` directly).
- To change **page interaction / state management**: modify `features/xxx/presentation/controllers/` (GetX Controllers) along with `presentation/pages/` and `presentation/widgets/`.
- To change **chart rendering**: refer to the existing real-time waveform chart components under `widgets/`.
- To add a new feature module: follow the three-layer structure (`data/domain/presentation`) of the existing `features/xxx` directories to create a new one — no need to touch `packages/alloop_blue_lite`.

---

## 8. FAQ & Notes

**Q: What if no device is found during scanning?**
A: Check in order: whether phone Bluetooth is on; whether the app has been granted the Bluetooth-related permissions (see Section 2); on Android 11 and below, whether location permission was granted; whether the device is powered on and not already connected to another phone; and retry while close to the device (within 1 meter).

**Q: What if connection fails / times out?**
A: Common causes are the device being too far away, the device already being occupied by another phone, or strong Bluetooth interference. Move closer to the device and retry; if it still fails, restart Bluetooth or restart the app.

**Q: If the connection drops midway, will the app reconnect automatically?**
A: No. This demo only reports the disconnected state (`LiteConnectionState.disconnected`) and does no automatic reconnection — the user needs to manually initiate a reconnect within the app.

**Q: Can I connect to multiple devices at once?**
A: No. This demo and its bundled SDK support single-device connection only. Although `connectedDevicesStream` is a list type, there is at most one element at any given moment.

**Q: Can measurement and history sync run at the same time?**
A: No, they are mutually exclusive. If you start a history sync while an SpO2 measurement is in progress (or vice versa), you will get a `BUSY` error — stop the current operation before switching. If the device syncs for a long time with no data, it will end with an error event; prompt the user to keep the device at rest and retry later.

**Q: What should I do if `CORE_ERROR` occurs?**
A: This is the fallback error code from the low-level communication module, representing an uncategorized internal error. Retry first; if it persists, try restarting the app or retrying with a different device, and log it to aid reproduction.

**Q: To display device status on a page, should I use `queryDeviceStatus` or `deviceStatusStream`?**
A: Use `deviceStatusStream`. Querying device status also triggers the device to start reporting history data, so if a page calls `queryDeviceStatus` frequently or repeatedly, it may conflict with the normal history sync flow and cause the sync to stall. `deviceStatusStream` delivers an initial status once after a successful connection, then keeps updating as the device pushes proactively — no active querying needed. Only sync-related flows need `queryDeviceStatus`, and `syncHistory` already includes that trigger internally, so do not call it separately before syncing.

**Q: Where are the CSV files after a history sync completes? Why does the "syncable" badge change automatically?**
A: The CSV files are written under the `<user-accessible directory>/history_sync/` subdirectory (on Android this is the app's external storage directory; on iOS it is the documents directory visible in the Files app), with names like `history_2026-07-06_10-30-00_Measurement.csv`; a file is generated only for types that actually received data this time. After a successful write, the page's "Sync Progress" card lists the file names and provides a "Share" button that brings up the system share sheet directly. At the same time, the local "syncable" flag for the corresponding type is cleared, so the badge on the status card immediately changes to "No data" — this is only a local instant refresh, and any status the device pushes afterward will still override it.
