import 'dart:async';

import 'package:alloop_blue_lite/alloop_blue_lite.dart';

class BridgeSdkEvent {
  const BridgeSdkEvent(this.event, this.data);

  final String event;
  final Map<String, dynamic> data;

  Map<String, dynamic> toJson() => {'event': event, 'data': data};
}

abstract class BridgeRingOperations {
  Stream<BridgeSdkEvent> get events;
  bool get ringConnected;
  String? get activeOperation;
  Iterable<BridgeSdkEvent> get snapshotEvents;

  Future<void> initialize();
  Future<void> startScan({Duration? timeout, String? nameFilter});
  Future<void> stopScan();
  Future<void> connect(String deviceId);
  Future<void> disconnect(String deviceId);
  Future<Map<String, dynamic>> getDeviceInfo(String deviceId);
  Future<void> startSpo2Verification(String deviceId);
  Future<void> stopMeasurement(String deviceId);
  Future<void> syncHistory(String deviceId);
  Future<void> dispose();
}

abstract class AlloopSdkClient {
  Stream<LiteDevice> get deviceDiscoveredStream;
  Stream<bool> get isScanningStream;

  Future<void> initialize();
  Future<void> startScan({Duration? timeout, String? nameFilter});
  Future<void> stopScan();
  Future<void> connect(String deviceId);
  Future<void> disconnect(String deviceId);
  Future<LiteDeviceInfo> getDeviceInfo(String deviceId);
  Stream<LiteConnectionState> connectionStateStream(String deviceId);
  Stream<LiteDeviceStatus> deviceStatusStream(String deviceId);
  Future<void> startSpo2Verification(String deviceId);
  Future<void> stopMeasurement(String deviceId);
  Stream<Spo2Result> spo2ResultStream(String deviceId);
  Stream<PpgWave> ppgWaveStream(String deviceId);
  Stream<AccWave> accStream(String deviceId);
  Stream<HistorySyncEvent> syncHistory(String deviceId);
}

class AlloopBlueLiteSdkClient implements AlloopSdkClient {
  AlloopBlueLiteSdkClient([AlloopBlueLite? sdk])
    : _sdk = sdk ?? AlloopBlueLite.instance;

  final AlloopBlueLite _sdk;

  @override
  Stream<LiteDevice> get deviceDiscoveredStream => _sdk.deviceDiscoveredStream;

  @override
  Stream<bool> get isScanningStream => _sdk.isScanningStream;

  @override
  Future<void> initialize() => _sdk.initialize();

  @override
  Future<void> startScan({Duration? timeout, String? nameFilter}) =>
      _sdk.startScan(timeout: timeout, nameFilter: nameFilter);

  @override
  Future<void> stopScan() => _sdk.stopScan();

  @override
  Future<void> connect(String deviceId) => _sdk.connect(deviceId);

  @override
  Future<void> disconnect(String deviceId) => _sdk.disconnect(deviceId);

  @override
  Future<LiteDeviceInfo> getDeviceInfo(String deviceId) =>
      _sdk.getDeviceInfo(deviceId);

  @override
  Stream<LiteConnectionState> connectionStateStream(String deviceId) =>
      _sdk.connectionStateStream(deviceId);

  @override
  Stream<LiteDeviceStatus> deviceStatusStream(String deviceId) =>
      _sdk.deviceStatusStream(deviceId);

  @override
  Future<void> startSpo2Verification(String deviceId) =>
      _sdk.startSpo2Verification(deviceId);

  @override
  Future<void> stopMeasurement(String deviceId) =>
      _sdk.stopMeasurement(deviceId);

  @override
  Stream<Spo2Result> spo2ResultStream(String deviceId) =>
      _sdk.spo2ResultStream(deviceId);

  @override
  Stream<PpgWave> ppgWaveStream(String deviceId) =>
      _sdk.ppgWaveStream(deviceId);

  @override
  Stream<AccWave> accStream(String deviceId) => _sdk.accStream(deviceId);

  @override
  Stream<HistorySyncEvent> syncHistory(String deviceId) =>
      _sdk.syncHistory(deviceId);
}

class AlloopBridgeAdapter implements BridgeRingOperations {
  AlloopBridgeAdapter({AlloopSdkClient? sdk})
    : _sdk = sdk ?? AlloopBlueLiteSdkClient();

  final AlloopSdkClient _sdk;
  final StreamController<BridgeSdkEvent> _eventController =
      StreamController<BridgeSdkEvent>.broadcast();
  final Map<String, LiteDevice> _currentScanDevices = <String, LiteDevice>{};
  final Map<String, LiteConnectionState> _connectionStates =
      <String, LiteConnectionState>{};
  final Map<String, LiteDeviceStatus> _deviceStatuses =
      <String, LiteDeviceStatus>{};
  final Map<String, StreamSubscription<LiteConnectionState>>
  _connectionSubscriptions = {};
  final Map<String, StreamSubscription<LiteDeviceStatus>>
  _deviceStatusSubscriptions = {};
  final List<BridgeSdkEvent> _historySnapshot = <BridgeSdkEvent>[];

  StreamSubscription<LiteDevice>? _deviceSubscription;
  StreamSubscription<bool>? _scanSubscription;
  StreamSubscription<HistorySyncEvent>? _historySubscription;
  StreamSubscription<Spo2Result>? _spo2Subscription;
  StreamSubscription<PpgWave>? _ppgSubscription;
  StreamSubscription<AccWave>? _accSubscription;
  bool _initialized = false;
  bool _ringConnected = false;
  bool _historyTerminalReceived = false;
  int _historySequence = 0;
  String? _activeOperation;
  String? _activeHistorySyncId;
  String? _activeHistoryDeviceId;
  final Map<String, Set<int>> _historyIndexes = {
    'measurement': <int>{},
    'sport': <int>{},
    'activity': <int>{},
  };

  @override
  Stream<BridgeSdkEvent> get events => _eventController.stream;

  @override
  bool get ringConnected => _ringConnected;

  @override
  String? get activeOperation => _activeOperation;

  @override
  Iterable<BridgeSdkEvent> get snapshotEvents sync* {
    for (final device in _currentScanDevices.values) {
      yield _deviceEvent(device);
    }
    for (final entry in _connectionStates.entries) {
      if (_currentScanDevices.containsKey(entry.key)) {
        yield _connectionEvent(entry.key, entry.value);
      }
    }
    for (final entry in _deviceStatuses.entries) {
      if (_currentScanDevices.containsKey(entry.key)) {
        yield _deviceStatusEvent(entry.key, entry.value);
      }
    }
    yield* _historySnapshot;
  }

  @override
  Future<void> initialize() async {
    if (_initialized) return;
    _deviceSubscription = _sdk.deviceDiscoveredStream.listen(
      _handleDeviceDiscovered,
      onError: _handleStreamError,
    );
    _scanSubscription = _sdk.isScanningStream.listen(
      (isScanning) => _emit('scanState', {'scanning': isScanning}),
      onError: _handleStreamError,
    );
    await _sdk.initialize();
    _initialized = true;
  }

  @override
  Future<void> startScan({Duration? timeout, String? nameFilter}) async {
    await initialize();
    _currentScanDevices.clear();
    await _sdk.startScan(timeout: timeout, nameFilter: nameFilter);
  }

  @override
  Future<void> stopScan() => _sdk.stopScan();

  @override
  Future<void> connect(String deviceId) async {
    _validateDeviceId(deviceId);
    await _runExclusive('connect', () async {
      await initialize();
      await _connectionSubscriptions[deviceId]?.cancel();
      _connectionSubscriptions[deviceId] = _sdk
          .connectionStateStream(deviceId)
          .listen(
            (state) => _handleConnectionState(deviceId, state),
            onError: _handleStreamError,
          );
      await _sdk.connect(deviceId);
    });
  }

  @override
  Future<void> disconnect(String deviceId) async {
    _validateDeviceId(deviceId);
    await _runExclusive('disconnect', () => _sdk.disconnect(deviceId));
  }

  @override
  Future<Map<String, dynamic>> getDeviceInfo(String deviceId) async {
    _validateDeviceId(deviceId);
    final info = await _sdk.getDeviceInfo(deviceId);
    return {
      'firmwareVersion': info.firmwareVersion,
      'batteryPercent': info.batteryPercent,
      'deviceState': info.deviceState,
      'hasMeasurementHistory': info.hasMeasurementHistory,
      'hasActivityHistory': info.hasActivityHistory,
      'hasSportHistory': info.hasSportHistory,
    };
  }

  @override
  Future<void> startSpo2Verification(String deviceId) async {
    _validateConnectedDevice(deviceId, operation: 'measurement');
    _claimOperation('spo2Measurement');
    try {
      await _cancelMeasurementSubscriptions();
      _spo2Subscription = _sdk
          .spo2ResultStream(deviceId)
          .listen(
            (result) => _emit('spo2Result', {
              'deviceId': deviceId,
              'spo2': result.spo2,
              'hr': result.hr,
              'success': result.success,
              'isVerified': result.isVerified,
              if (result.measuredAt != null)
                'measuredAt': result.measuredAt!.toUtc().toIso8601String(),
            }),
            onError: (Object error, StackTrace stackTrace) =>
                _handleMeasurementStreamError(deviceId, 'spo2', error),
          );
      _ppgSubscription = _sdk
          .ppgWaveStream(deviceId)
          .listen(
            (wave) => _emit('ppgWave', {
              'deviceId': deviceId,
              'packCount': wave.packCount,
              'captureTime': wave.captureTime,
              'samples': [
                for (final sample in wave.samples)
                  {
                    'ledG': sample.ledG,
                    'ledGAmb': sample.ledGAmb,
                    'ledRedAmb': sample.ledRedAmb,
                    'ledIr': sample.ledIr,
                  },
              ],
            }),
            onError: (Object error, StackTrace stackTrace) =>
                _handleMeasurementStreamError(deviceId, 'ppg', error),
          );
      _accSubscription = _sdk
          .accStream(deviceId)
          .listen(
            (wave) => _emit('accWave', {
              'deviceId': deviceId,
              'packCount': wave.packCount,
              'captureTime': wave.captureTime,
              'samples': [
                for (final sample in wave.samples)
                  {'x': sample.x, 'y': sample.y, 'z': sample.z},
              ],
            }),
            onError: (Object error, StackTrace stackTrace) =>
                _handleMeasurementStreamError(deviceId, 'acc', error),
          );
      await _sdk.startSpo2Verification(deviceId);
    } catch (_) {
      await _finishMeasurement();
      rethrow;
    }
  }

  @override
  Future<void> stopMeasurement(String deviceId) async {
    _validateConnectedDevice(deviceId, operation: 'measurement');
    if (_activeOperation != null && _activeOperation != 'spo2Measurement') {
      throw AlloopBlueLiteException(
        'BRIDGE_BUSY',
        'Bridge is busy with $_activeOperation',
      );
    }
    try {
      await _sdk.stopMeasurement(deviceId);
    } finally {
      await _finishMeasurement();
    }
  }

  @override
  Future<void> syncHistory(String deviceId) async {
    _validateDeviceId(deviceId);
    _validateConnectedDevice(deviceId, operation: 'history sync');
    _claimOperation('syncHistory');

    final syncId =
        'history-${DateTime.now().toUtc().microsecondsSinceEpoch}-${++_historySequence}';
    _activeHistorySyncId = syncId;
    _activeHistoryDeviceId = deviceId;
    _historyTerminalReceived = false;
    _historySnapshot.clear();
    for (final indexes in _historyIndexes.values) {
      indexes.clear();
    }

    try {
      _historySubscription = _sdk
          .syncHistory(deviceId)
          .listen(
            (event) => _handleHistoryEvent(deviceId, syncId, event),
            onError: (Object error, StackTrace stackTrace) {
              _handleHistoryStreamError(deviceId, syncId, error);
            },
            onDone: () => _handleHistoryDone(deviceId, syncId),
          );
    } catch (_) {
      _finishHistorySync(syncId);
      rethrow;
    }
  }

  void _validateDeviceId(String deviceId) {
    if (!_currentScanDevices.containsKey(deviceId)) {
      throw const AlloopBlueLiteException(
        'BRIDGE_INVALID_DEVICE_ID',
        'deviceId must come from the current Android SDK scan session',
      );
    }
  }

  void _validateConnectedDevice(String deviceId, {required String operation}) {
    _validateDeviceId(deviceId);
    if (_connectionStates[deviceId]?.state !=
        LiteConnectionStateValue.connected) {
      throw AlloopBlueLiteException(
        'BRIDGE_RING_NOT_CONNECTED',
        'The ring must be connected before $operation',
      );
    }
  }

  void _handleDeviceDiscovered(LiteDevice device) {
    _currentScanDevices[device.id] = device;
    _emitEvent(_deviceEvent(device));
  }

  BridgeSdkEvent _deviceEvent(LiteDevice device) {
    return BridgeSdkEvent('deviceDiscovered', {
      'deviceId': device.id,
      'name': device.name,
      'rssi': device.rssi,
    });
  }

  void _handleConnectionState(String deviceId, LiteConnectionState connection) {
    _connectionStates[deviceId] = connection;
    _ringConnected = connection.state == LiteConnectionStateValue.connected;
    if (_ringConnected) {
      _subscribeToDeviceStatus(deviceId);
    } else if (connection.state == LiteConnectionStateValue.disconnected) {
      _deviceStatuses.remove(deviceId);
      unawaited(_deviceStatusSubscriptions.remove(deviceId)?.cancel());
      unawaited(_finishMeasurement());
      final syncId = _activeHistorySyncId;
      if (_activeHistoryDeviceId == deviceId && syncId != null) {
        _failHistorySync(
          deviceId,
          syncId,
          code: 'BRIDGE_RING_DISCONNECTED',
          message: 'The ring disconnected during history sync',
        );
      }
    }
    _emitEvent(_connectionEvent(deviceId, connection));
  }

  void _subscribeToDeviceStatus(String deviceId) {
    unawaited(_deviceStatusSubscriptions.remove(deviceId)?.cancel());
    _deviceStatusSubscriptions[deviceId] = _sdk
        .deviceStatusStream(deviceId)
        .listen((status) {
          _deviceStatuses[deviceId] = status;
          _emitEvent(_deviceStatusEvent(deviceId, status));
        }, onError: _handleStreamError);
  }

  BridgeSdkEvent _deviceStatusEvent(String deviceId, LiteDeviceStatus status) {
    return BridgeSdkEvent('deviceStatus', {
      'deviceId': deviceId,
      'battery': status.batteryPercent,
      'state': status.deviceState,
      'hasMeasurement': status.hasMeasurementHistory,
      'hasActivity': status.hasActivityHistory,
      'hasSport': status.hasSportHistory,
    });
  }

  BridgeSdkEvent _connectionEvent(
    String deviceId,
    LiteConnectionState connection,
  ) {
    final state = switch (connection.state) {
      LiteConnectionStateValue.connecting => 'connecting',
      LiteConnectionStateValue.connected => 'connected',
      LiteConnectionStateValue.disconnected => 'disconnected',
    };
    return BridgeSdkEvent('connectionState', {
      'deviceId': deviceId,
      'state': state,
      if (connection.errorCode != null) 'errorCode': connection.errorCode,
    });
  }

  void _handleStreamError(Object error, StackTrace stackTrace) {
    final code = error is AlloopBlueLiteException
        ? error.code
        : 'BRIDGE_INTERNAL_ERROR';
    final message = error is AlloopBlueLiteException
        ? error.message ?? error.code
        : error.toString();
    _emit('bridgeError', {'code': code, 'message': message});
  }

  void _handleMeasurementStreamError(
    String deviceId,
    String stream,
    Object error,
  ) {
    if (_activeOperation != 'spo2Measurement') return;
    final code = error is AlloopBlueLiteException
        ? error.code
        : 'BRIDGE_INTERNAL_ERROR';
    final message = error is AlloopBlueLiteException
        ? error.message ?? error.code
        : error.toString();
    _emit('bridgeError', {
      'deviceId': deviceId,
      'operation': 'spo2Measurement',
      'stream': stream,
      'code': code,
      'message': message,
    });
    unawaited(_stopMeasurementAfterStreamError(deviceId));
  }

  Future<void> _stopMeasurementAfterStreamError(String deviceId) async {
    try {
      await _sdk.stopMeasurement(deviceId);
    } catch (_) {
      // Preserve the original stream error; the SDK is already unhealthy.
    } finally {
      await _finishMeasurement();
    }
  }

  Future<void> _cancelMeasurementSubscriptions() async {
    await _spo2Subscription?.cancel();
    await _ppgSubscription?.cancel();
    await _accSubscription?.cancel();
    _spo2Subscription = null;
    _ppgSubscription = null;
    _accSubscription = null;
  }

  Future<void> _finishMeasurement() async {
    await _cancelMeasurementSubscriptions();
    if (_activeOperation == 'spo2Measurement') _activeOperation = null;
  }

  void _handleHistoryEvent(
    String deviceId,
    String syncId,
    HistorySyncEvent event,
  ) {
    if (_activeHistorySyncId != syncId) return;
    try {
      if (event case HistoryRecordReceived(:final type, :final index)) {
        final indexes = _historyIndexes[type];
        if (indexes == null || index < 0) {
          throw StateError('Invalid history record index: $type[$index]');
        }
        if (!indexes.add(index)) return;
      }
      if (event case HistoryTypeCompleted(:final type, :final count)) {
        _validateHistoryCount(type, count);
      }
      if (event case HistoryAllCompleted(:final counts)) {
        for (final type in _historyIndexes.keys) {
          final count = counts[type];
          if (count == null) {
            throw StateError('History completion omitted $type count');
          }
          _validateHistoryCount(type, count);
        }
      }
      final bridgeEvent = switch (event) {
        HistoryTypeStarted() => BridgeSdkEvent('historyProgress', {
          'deviceId': deviceId,
          'syncId': syncId,
          'phase': 'typeStarted',
          'type': event.type,
          'total': event.total,
        }),
        HistoryRecordReceived() => BridgeSdkEvent('historyRecord', {
          'deviceId': deviceId,
          'syncId': syncId,
          'type': event.type,
          'index': event.index,
          'total': event.total,
          'record': _historyRecordToJson(event.record),
        }),
        HistoryTypeCompleted() => BridgeSdkEvent('historyProgress', {
          'deviceId': deviceId,
          'syncId': syncId,
          'phase': 'typeCompleted',
          'type': event.type,
          'count': event.count,
        }),
        HistoryAllCompleted() => BridgeSdkEvent('historyProgress', {
          'deviceId': deviceId,
          'syncId': syncId,
          'phase': 'allCompleted',
          'counts': event.counts,
        }),
        HistorySyncError() => BridgeSdkEvent('bridgeError', {
          'deviceId': deviceId,
          'syncId': syncId,
          'operation': 'syncHistory',
          'code': event.code,
          'message': event.message ?? event.code,
        }),
      };
      _emitHistoryEvent(bridgeEvent);
      if (event is HistoryAllCompleted || event is HistorySyncError) {
        _historyTerminalReceived = true;
        _finishHistorySync(syncId);
      }
    } catch (error) {
      _failHistorySync(
        deviceId,
        syncId,
        code: 'BRIDGE_HISTORY_INCOMPLETE',
        message: error.toString(),
      );
    }
  }

  void _validateHistoryCount(String type, int count) {
    final indexes = _historyIndexes[type];
    if (indexes == null || count < 0) {
      throw StateError('Invalid history completion count: $type=$count');
    }
    if (indexes.length != count ||
        indexes.any((index) => index < 0 || index >= count)) {
      throw StateError(
        'History $type is incomplete: received indexes '
        '${indexes.toList()..sort()}, reported count $count',
      );
    }
  }

  Map<String, dynamic> _historyRecordToJson(Object record) {
    return switch (record) {
      MeasurementRecord() => {
        'unixSec': record.unixSec,
        'hr': record.hr,
        'hrv': record.hrv,
        'spo2': record.spo2,
        'respRate': record.respRate,
        'hrSuccess': record.hrSuccess,
        'spo2Success': record.spo2Success,
      },
      SportRecord() => {
        'unixSec': record.unixSec,
        'hr': record.hr,
        'steps': record.steps,
        'activityCount': record.activityCount,
      },
      ActivityRecord() => {
        'unixSec': record.unixSec,
        'batteryPercent': record.batteryPercent,
        'steps': record.steps,
        'activeSeconds': record.activeSeconds,
        'temperaturesC': record.temperaturesC,
      },
      _ => throw ArgumentError.value(
        record,
        'record',
        'Unsupported history record type',
      ),
    };
  }

  void _handleHistoryStreamError(String deviceId, String syncId, Object error) {
    if (_activeHistorySyncId != syncId) return;
    final code = error is AlloopBlueLiteException
        ? error.code
        : 'BRIDGE_INTERNAL_ERROR';
    final message = error is AlloopBlueLiteException
        ? error.message ?? error.code
        : error.toString();
    _failHistorySync(deviceId, syncId, code: code, message: message);
  }

  void _failHistorySync(
    String deviceId,
    String syncId, {
    required String code,
    required String message,
  }) {
    if (_activeHistorySyncId != syncId) return;
    _emitHistoryEvent(
      BridgeSdkEvent('bridgeError', {
        'deviceId': deviceId,
        'syncId': syncId,
        'operation': 'syncHistory',
        'code': code,
        'message': message,
      }),
    );
    _historyTerminalReceived = true;
    final subscription = _historySubscription;
    _finishHistorySync(syncId);
    unawaited(subscription?.cancel());
  }

  void _handleHistoryDone(String deviceId, String syncId) {
    if (_activeHistorySyncId != syncId) return;
    if (!_historyTerminalReceived) {
      _emitHistoryEvent(
        BridgeSdkEvent('bridgeError', {
          'deviceId': deviceId,
          'syncId': syncId,
          'operation': 'syncHistory',
          'code': 'BRIDGE_HISTORY_INCOMPLETE',
          'message': 'History stream closed without a terminal event',
        }),
      );
    }
    _finishHistorySync(syncId);
  }

  void _emitHistoryEvent(BridgeSdkEvent event) {
    _historySnapshot.add(event);
    _emitEvent(event);
  }

  void _claimOperation(String operation) {
    if (_activeOperation != null) {
      throw AlloopBlueLiteException(
        'BRIDGE_BUSY',
        'Bridge is busy with $_activeOperation',
      );
    }
    _activeOperation = operation;
  }

  Future<T> _runExclusive<T>(
    String operation,
    Future<T> Function() callback,
  ) async {
    _claimOperation(operation);
    try {
      return await callback();
    } finally {
      if (_activeOperation == operation) _activeOperation = null;
    }
  }

  void _finishHistorySync(String syncId) {
    if (_activeHistorySyncId != syncId) return;
    _activeHistorySyncId = null;
    _activeHistoryDeviceId = null;
    _historySubscription = null;
    if (_activeOperation == 'syncHistory') _activeOperation = null;
  }

  void _emit(String event, Map<String, dynamic> data) {
    _emitEvent(BridgeSdkEvent(event, data));
  }

  void _emitEvent(BridgeSdkEvent event) {
    if (!_eventController.isClosed) {
      _eventController.add(event);
    }
  }

  @override
  Future<void> dispose() async {
    await _deviceSubscription?.cancel();
    await _scanSubscription?.cancel();
    for (final subscription in _connectionSubscriptions.values) {
      await subscription.cancel();
    }
    _connectionSubscriptions.clear();
    for (final subscription in _deviceStatusSubscriptions.values) {
      await subscription.cancel();
    }
    _deviceStatusSubscriptions.clear();
    await _historySubscription?.cancel();
    _historySubscription = null;
    await _finishMeasurement();
    await _eventController.close();
  }
}
