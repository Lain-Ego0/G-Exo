import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'models/acc_wave.dart';
import 'models/history_sync_event.dart';
import 'models/lite_connection_state.dart';
import 'models/lite_device.dart';
import 'models/lite_device_info.dart';
import 'models/lite_device_status.dart';
import 'models/lite_exception.dart';
import 'models/ppg_wave.dart';
import 'models/spo2_result.dart';

/// Entry point for the Alloop Blue Lite plugin.
///
/// Provides a thin, stream-based Dart API over the native Alloop Kit
/// connectivity core: scanning, connecting, reading device status and
/// running SpO2 verification / history sync. The app targets a single
/// actively-connected device at a time; per-device streams filter events by
/// the requested device id.
class AlloopBlueLite {
  AlloopBlueLite._();

  /// The shared singleton instance.
  static final AlloopBlueLite instance = AlloopBlueLite._();

  static const MethodChannel _methodChannel = MethodChannel('alloop_blue_lite/methods');

  static const EventChannel _scanChannel = EventChannel('alloop_blue_lite/events/scan');
  static const EventChannel _connectionChannel = EventChannel('alloop_blue_lite/events/connection');
  static const EventChannel _deviceStatusChannel = EventChannel('alloop_blue_lite/events/device_status');
  static const EventChannel _spo2Channel = EventChannel('alloop_blue_lite/events/spo2');
  static const EventChannel _ppgChannel = EventChannel('alloop_blue_lite/events/ppg');
  static const EventChannel _historyChannel = EventChannel('alloop_blue_lite/events/history');

  StreamController<LiteDevice>? _deviceDiscoveredController;
  StreamController<bool>? _isScanningController;
  StreamController<List<LiteDevice>>? _connectedDevicesController;
  StreamController<Map<dynamic, dynamic>>? _connectionController;
  StreamController<Map<dynamic, dynamic>>? _deviceStatusController;
  StreamController<Map<dynamic, dynamic>>? _spo2Controller;
  StreamController<Map<dynamic, dynamic>>? _ppgController;
  StreamController<Map<dynamic, dynamic>>? _accController;
  StreamController<Map<dynamic, dynamic>>? _historyController;

  StreamSubscription<dynamic>? _scanSubscription;
  StreamSubscription<dynamic>? _connectionSubscription;
  StreamSubscription<dynamic>? _deviceStatusSubscription;
  StreamSubscription<dynamic>? _spo2Subscription;
  StreamSubscription<dynamic>? _ppgSubscription;
  StreamSubscription<dynamic>? _historySubscription;

  bool _isScanning = false;
  LiteDevice? _connectedDevice;
  Timer? _scanTimeoutTimer;

  /// Last known connection state per device id, used to replay state to late
  /// subscribers of [connectionStateStream] (e.g. a page that re-enters
  /// after the connection was already established).
  final Map<String, LiteConnectionState> _lastConnectionStateByDevice = {};

  /// Display info (name/rssi) remembered from scan results, keyed by device
  /// id, so connection events — which carry only the id — can be enriched.
  final Map<String, LiteDevice> _knownDevices = {};

  /// Device ids currently considered connected, mirrors [_connectedDevice]
  /// but expressed as a set so [connectedDevicesStream] replay logic reads
  /// naturally even though only a single device is supported today.
  final Set<String> _connectedIds = {};

  /// Resets all cached listeners and derived state.
  ///
  /// Intended for tests only, so each test starts from a clean slate against
  /// a fresh mock channel handler.
  @visibleForTesting
  void resetForTest() {
    _scanSubscription?.cancel();
    _connectionSubscription?.cancel();
    _deviceStatusSubscription?.cancel();
    _spo2Subscription?.cancel();
    _ppgSubscription?.cancel();
    _historySubscription?.cancel();
    _scanTimeoutTimer?.cancel();

    _scanSubscription = null;
    _connectionSubscription = null;
    _deviceStatusSubscription = null;
    _spo2Subscription = null;
    _ppgSubscription = null;
    _historySubscription = null;
    _scanTimeoutTimer = null;

    _deviceDiscoveredController?.close();
    _isScanningController?.close();
    _connectedDevicesController?.close();
    _connectionController?.close();
    _deviceStatusController?.close();
    _spo2Controller?.close();
    _ppgController?.close();
    _accController?.close();
    _historyController?.close();

    _deviceDiscoveredController = null;
    _isScanningController = null;
    _connectedDevicesController = null;
    _connectionController = null;
    _deviceStatusController = null;
    _spo2Controller = null;
    _ppgController = null;
    _accController = null;
    _historyController = null;

    _isScanning = false;
    _connectedDevice = null;
    _lastConnectionStateByDevice.clear();
    _connectedIds.clear();
    _knownDevices.clear();
  }

  StreamController<LiteDevice> get _deviceDiscovered =>
      _deviceDiscoveredController ??= StreamController<LiteDevice>.broadcast();
  StreamController<bool> get _isScanningCtl => _isScanningController ??= StreamController<bool>.broadcast();
  StreamController<List<LiteDevice>> get _connectedDevices =>
      _connectedDevicesController ??= StreamController<List<LiteDevice>>.broadcast();

  /// Devices discovered while a scan is in progress.
  Stream<LiteDevice> get deviceDiscoveredStream => _deviceDiscovered.stream;

  /// Whether a scan is currently in progress.
  ///
  /// Derived locally: becomes `true` on [startScan] and `false` on
  /// [stopScan] or scan timeout. When [startScan] is called with a non-null
  /// `timeout`, a local [Timer] mirrors the native scanner's own timeout
  /// contract (the native side auto-stops scanning after the same
  /// duration) so this flag flips back to `false` without requiring a
  /// round-trip through a native event.
  Stream<bool> get isScanningStream => _isScanningCtl.stream;

  /// Current scanning state (synchronous snapshot of [isScanningStream]).
  bool get isScanning => _isScanning;

  /// Devices currently connected, derived from connection events.
  ///
  /// Since only a single device is supported at a time, this is either an
  /// empty list or a list with exactly one device.
  ///
  /// The [LiteDevice] entries here are placeholders: they carry only the
  /// [LiteDevice.id] (with `name` empty and `rssi` 0) because native
  /// connection events don't include display data. Consumers that need the
  /// name/rssi should resolve it from a prior [deviceDiscoveredStream] scan
  /// result or by calling [getDeviceInfo].
  ///
  /// Late subscribers (e.g. a scan page re-entered after a device is already
  /// connected) immediately receive the current derived list before any
  /// subsequent live events, so they never observe a stale empty list.
  Stream<List<LiteDevice>> get connectedDevicesStream {
    _ensureConnectionListener();
    late StreamController<List<LiteDevice>> controller;
    StreamSubscription<List<LiteDevice>>? subscription;
    controller = StreamController<List<LiteDevice>>(
      onListen: () {
        controller.add(_currentConnectedDevices());
        subscription = _connectedDevices.stream.listen(
          controller.add,
          onError: controller.addError,
          onDone: controller.close,
        );
      },
      onCancel: () => subscription?.cancel(),
    );
    return controller.stream;
  }

  List<LiteDevice> _currentConnectedDevices() =>
      _connectedIds.isNotEmpty && _connectedDevice != null ? [_connectedDevice!] : const [];

  /// Prepares the native connectivity core for use. Call once before any
  /// other method.
  ///
  /// Eagerly attaches the persistent connection and device-status channel
  /// listeners (rather than waiting for the first [connectionStateStream] /
  /// [deviceStatusStream] subscriber) so that state replay caches such as
  /// [_lastConnectionStateByDevice] start populating as soon as possible,
  /// and so a scan/connect race can never leave those channels unheard.
  Future<void> initialize() {
    _ensureConnectionListener();
    _ensureDeviceStatusListener();
    return _invoke('initialize', const {});
  }

  /// Starts scanning for nearby devices.
  ///
  /// Discovered devices are delivered via [deviceDiscoveredStream].
  Future<void> startScan({Duration? timeout, String? nameFilter}) async {
    _scanTimeoutTimer?.cancel();
    _scanTimeoutTimer = null;

    // Attach the scan-channel fan-out listener BEFORE invoking the native
    // method. Both the listen registration (EventChannel) and the method
    // invocation (MethodChannel) travel over the same platform messenger, in
    // order, so establishing the listen first guarantees it is registered
    // before native scanning starts — otherwise a scan result emitted
    // immediately after the native call returns could be missed if the Dart
    // side only subscribed afterwards (e.g. via deviceDiscoveredStream).
    _ensureScanPipeline();

    await _invoke('startScan', {
      'nameFilter': nameFilter,
      'timeoutMs': timeout?.inMilliseconds,
    });
    _isScanning = true;
    _isScanningCtl.add(true);

    if (timeout != null) {
      _scanTimeoutTimer = Timer(timeout, () {
        _scanTimeoutTimer = null;
        _isScanning = false;
        _isScanningCtl.add(false);
      });
    }
  }

  void _ensureScanPipeline() {
    _scanSubscription ??= _scanChannel.receiveBroadcastStream().listen((event) {
      final map = event as Map<dynamic, dynamic>;
      final device = LiteDevice.fromMap(map);
      // Remember display info so connected-device entries (whose events carry
      // only an id) can surface the advertised name instead of a blank one.
      _knownDevices[device.id] = device;
      _deviceDiscovered.add(device);
    });
  }

  /// Stops an in-progress scan.
  Future<void> stopScan() async {
    _scanTimeoutTimer?.cancel();
    _scanTimeoutTimer = null;
    await _invoke('stopScan', const {});
    _isScanning = false;
    _isScanningCtl.add(false);
  }

  /// Connects to the device identified by [deviceId].
  ///
  /// Completes once the native call returns; connection progress and the
  /// final outcome are delivered via [connectionStateStream].
  Future<void> connect(String deviceId) {
    _ensureConnectionListener();
    return _invoke('connect', {'deviceId': deviceId});
  }

  /// Disconnects the device identified by [deviceId].
  Future<void> disconnect(String deviceId) {
    return _invoke('disconnect', {'deviceId': deviceId});
  }

  /// Connection state changes for [deviceId].
  ///
  /// Late subscribers immediately receive the last known state for
  /// [deviceId] (if any was ever observed) before any subsequent live
  /// events, so a page that re-enters after a connection was already
  /// established (or lost) doesn't have to wait for the next native event to
  /// find out.
  Stream<LiteConnectionState> connectionStateStream(String deviceId) {
    _ensureConnectionListener();

    late StreamController<LiteConnectionState> controller;
    StreamSubscription<LiteConnectionState>? subscription;
    controller = StreamController<LiteConnectionState>(
      onListen: () {
        final cached = _lastConnectionStateByDevice[deviceId];
        if (cached != null) {
          controller.add(cached);
        }
        subscription = _connectionController!.stream
            .where((map) => map['deviceId'] == deviceId)
            .map(LiteConnectionState.fromMap)
            .listen(
              controller.add,
              onError: controller.addError,
              onDone: controller.close,
            );
      },
      onCancel: () => subscription?.cancel(),
    );
    return controller.stream;
  }

  void _ensureConnectionListener() {
    _connectionController ??= StreamController<Map<dynamic, dynamic>>.broadcast();
    _connectionSubscription ??= _connectionChannel.receiveBroadcastStream().listen((event) {
      final map = event as Map<dynamic, dynamic>;
      final deviceId = map['deviceId'] as String;
      final state = LiteConnectionState.fromMap(map);
      _lastConnectionStateByDevice[deviceId] = state;
      switch (state.state) {
        case LiteConnectionStateValue.connected:
          final known = _knownDevices[deviceId];
          _connectedDevice = LiteDevice(
            id: deviceId,
            name: known?.name ?? '',
            rssi: known?.rssi ?? 0,
          );
          _connectedIds
            ..clear()
            ..add(deviceId);
          _connectedDevices.add([_connectedDevice!]);
        case LiteConnectionStateValue.connecting:
          break;
        case LiteConnectionStateValue.disconnected:
          if (_connectedDevice?.id == deviceId) {
            _connectedDevice = null;
            _connectedIds.remove(deviceId);
            _connectedDevices.add(const []);
          }
      }
      _connectionController!.add(map);
    });
  }

  /// Fetches static device information (firmware version, battery, state).
  Future<LiteDeviceInfo> getDeviceInfo(String deviceId) async {
    final result = await _invoke('getDeviceInfo', {'deviceId': deviceId});
    return LiteDeviceInfo.fromMap(result as Map<dynamic, dynamic>);
  }

  /// Fetches the current device status (battery, state) once.
  ///
  /// Warning: this also triggers the device to start uploading its pending
  /// history data as a side effect. Normal UI code that just wants to display
  /// status should subscribe to [deviceStatusStream] instead (it's kept
  /// current via push updates and an initial snapshot after connect, with no
  /// query needed). Only sync flows should call this directly, and
  /// [syncHistory] already triggers it internally — do not call this
  /// separately before a sync.
  Future<LiteDeviceStatus> queryDeviceStatus(String deviceId) async {
    final result = await _invoke('queryDeviceStatus', {'deviceId': deviceId});
    return LiteDeviceStatus.fromMap(result as Map<dynamic, dynamic>);
  }

  /// Device status updates for [deviceId] as they arrive from the device.
  Stream<LiteDeviceStatus> deviceStatusStream(String deviceId) {
    _ensureDeviceStatusListener();
    return _deviceStatusController!.stream
        .where((map) => map['deviceId'] == deviceId)
        .map(LiteDeviceStatus.fromMap);
  }

  void _ensureDeviceStatusListener() {
    _deviceStatusController ??= StreamController<Map<dynamic, dynamic>>.broadcast();
    _deviceStatusSubscription ??= _deviceStatusChannel.receiveBroadcastStream().listen((event) {
      _deviceStatusController!.add(event as Map<dynamic, dynamic>);
    });
  }

  /// Starts SpO2 verification on [deviceId].
  Future<void> startSpo2Verification(String deviceId) {
    return _invoke('startSpo2Verification', {'deviceId': deviceId});
  }

  /// Stops the current measurement on [deviceId].
  Future<void> stopMeasurement(String deviceId) {
    return _invoke('stopMeasurement', {'deviceId': deviceId});
  }

  /// SpO2 readings for [deviceId], covering both live results and
  /// verification samples (see [Spo2Result.isVerified]).
  ///
  /// Note: the spo2 payload does not itself carry a deviceId (only a single
  /// device is ever active), so all events on this channel are forwarded.
  Stream<Spo2Result> spo2ResultStream(String deviceId) {
    _spo2Controller ??= StreamController<Map<dynamic, dynamic>>.broadcast();
    _spo2Subscription ??= _spo2Channel.receiveBroadcastStream().listen((event) {
      _spo2Controller!.add(event as Map<dynamic, dynamic>);
    });
    return _spo2Controller!.stream.map(Spo2Result.fromMap);
  }

  /// PPG waveform packets for [deviceId].
  ///
  /// The underlying channel also carries ACC samples (discriminated by a
  /// `kind` key); those are routed to [accStream] instead and filtered out
  /// here.
  Stream<PpgWave> ppgWaveStream(String deviceId) {
    _ensurePpgPipeline();
    return _ppgController!.stream.where((map) => map['kind'] == 'ppg').map(PpgWave.fromMap);
  }

  /// ACC waveform packets for [deviceId].
  ///
  /// Delivered over the same native channel as [ppgWaveStream] (discriminated
  /// by a `kind` key). Like [ppgWaveStream], this is not filtered by
  /// [deviceId]: only a single device is ever active at a time, so all events
  /// on this channel belong to it.
  Stream<AccWave> accStream(String deviceId) {
    _ensurePpgPipeline();
    return _accController!.stream.where((map) => map['kind'] == 'acc').map(AccWave.fromMap);
  }

  void _ensurePpgPipeline() {
    _ppgController ??= StreamController<Map<dynamic, dynamic>>.broadcast();
    _accController ??= StreamController<Map<dynamic, dynamic>>.broadcast();
    _ppgSubscription ??= _ppgChannel.receiveBroadcastStream().listen((event) {
      final map = event as Map<dynamic, dynamic>;
      if (map['kind'] == 'acc') {
        _accController!.add(map);
      } else {
        _ppgController!.add(map);
      }
    });
  }

  /// Starts a history sync for [deviceId] and returns a broadcast stream of
  /// progress events. The stream closes after [HistoryAllCompleted] or
  /// [HistorySyncError].
  ///
  /// Like the other event channels, the underlying
  /// `_historyChannel.receiveBroadcastStream()` is listened to exactly once
  /// for the lifetime of the channel and fanned out through a shared
  /// broadcast [StreamController] (see [_historyController]). Each call to
  /// [syncHistory] returns its own derived stream — via a fresh
  /// per-call [StreamController] that listens to the shared broadcast and
  /// cancels itself on the next terminal event — rather than re-registering
  /// a native listener, which would silently steal the native handler
  /// registration from any in-flight sync.
  ///
  /// The native `syncHistory` method invocation happens inside the derived
  /// stream's `onListen`, so if a sync is already in progress and the native
  /// side rejects this call (e.g. with a `BUSY` platform exception), that
  /// error surfaces as an error on the returned stream.
  Stream<HistorySyncEvent> syncHistory(String deviceId) {
    _historyController ??= StreamController<Map<dynamic, dynamic>>.broadcast();
    _historySubscription ??= _historyChannel.receiveBroadcastStream().listen(
      (event) {
        _historyController!.add(event as Map<dynamic, dynamic>);
      },
      onError: (Object error, StackTrace stackTrace) {
        _historyController!.addError(_toLiteException(error), stackTrace);
      },
    );

    late StreamController<HistorySyncEvent> controller;
    StreamSubscription<Map<dynamic, dynamic>>? subscription;

    controller = StreamController<HistorySyncEvent>(
      onListen: () {
        subscription = _historyController!.stream.listen(
          (event) {
            final syncEvent = HistorySyncEvent.fromMap(event);
            controller.add(syncEvent);
            if (syncEvent is HistoryAllCompleted || syncEvent is HistorySyncError) {
              subscription?.cancel();
              controller.close();
            }
          },
          onError: (Object error, StackTrace stackTrace) {
            controller.addError(error, stackTrace);
            subscription?.cancel();
            controller.close();
          },
        );
        unawaited(
          _invoke('syncHistory', {'deviceId': deviceId}).catchError((Object error, StackTrace stackTrace) async {
            controller.addError(error, stackTrace);
            await subscription?.cancel();
            await controller.close();
          }),
        );
      },
      onCancel: () => subscription?.cancel(),
    );

    return controller.stream;
  }

  Future<dynamic> _invoke(String method, Map<String, dynamic> args) async {
    try {
      return await _methodChannel.invokeMethod(method, args);
    } on PlatformException catch (error) {
      throw _toLiteException(error);
    }
  }

  AlloopBlueLiteException _toLiteException(Object error) {
    if (error is PlatformException) {
      return AlloopBlueLiteException(error.code, error.message);
    }
    return AlloopBlueLiteException('UNKNOWN', error.toString());
  }
}
