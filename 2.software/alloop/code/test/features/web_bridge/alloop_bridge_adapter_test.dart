import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:alloop/features/web_bridge/data/alloop_bridge_adapter.dart';
import 'package:alloop_blue_lite/alloop_blue_lite.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late FakeAlloopSdk sdk;
  late AlloopBridgeAdapter adapter;

  setUp(() {
    sdk = FakeAlloopSdk();
    adapter = AlloopBridgeAdapter(sdk: sdk);
  });

  tearDown(() async {
    await adapter.dispose();
    await sdk.dispose();
  });

  test('shared history contract fixture has the Stage 4 envelope', () async {
    final fixture =
        jsonDecode(
              await File('../contracts/history_sync_v1.json').readAsString(),
            )
            as Map<String, dynamic>;
    final events = fixture['events'] as List<dynamic>;

    expect(events.map((event) => event['event']), [
      'historyProgress',
      'historyRecord',
      'historyProgress',
    ]);
    expect(events[1]['data']['record'], containsPair('unixSec', 1785787200));
    expect(events[2]['data']['phase'], 'allCompleted');
  });

  test('shared realtime contract keeps waveform samples batched', () async {
    final fixture =
        jsonDecode(
              await File(
                '../contracts/realtime_measurement_v1.json',
              ).readAsString(),
            )
            as Map<String, dynamic>;
    final events = fixture['events'] as List<dynamic>;

    expect(events.map((event) => event['event']), [
      'spo2Result',
      'ppgWave',
      'accWave',
    ]);
    expect(events[1]['data']['samples'], hasLength(2));
    expect(events[2]['data']['samples'][0], {'x': -1, 'y': 2, 'z': 3});
  });

  test(
    'forwards scan and discovery events using Android SDK device id',
    () async {
      final events = <BridgeSdkEvent>[];
      final subscription = adapter.events.listen(events.add);

      await adapter.startScan(
        timeout: const Duration(seconds: 3),
        nameFilter: 'AlloopRing',
      );
      sdk.scanning.add(true);
      sdk.devices.add(
        const LiteDevice(id: 'android-42', name: 'Ring', rssi: -51),
      );
      await pumpEventQueue();

      expect(sdk.initializeCalls, 1);
      expect(sdk.lastTimeout, const Duration(seconds: 3));
      expect(sdk.lastNameFilter, 'AlloopRing');
      expect(
        events.map((event) => event.toJson()),
        containsAll([
          {
            'event': 'scanState',
            'data': {'scanning': true},
          },
          {
            'event': 'deviceDiscovered',
            'data': {'deviceId': 'android-42', 'name': 'Ring', 'rssi': -51},
          },
        ]),
      );

      await subscription.cancel();
    },
  );

  test('rejects ids not discovered in the current scan session', () async {
    await adapter.startScan();
    sdk.devices.add(const LiteDevice(id: 'old-id', name: 'Ring', rssi: -60));
    await pumpEventQueue();
    await adapter.startScan();

    await expectLater(
      adapter.connect('old-id'),
      throwsA(
        isA<AlloopBlueLiteException>().having(
          (error) => error.code,
          'code',
          'BRIDGE_INVALID_DEVICE_ID',
        ),
      ),
    );
  });

  test('subscribes before connect and forwards connection state', () async {
    final events = <BridgeSdkEvent>[];
    final subscription = adapter.events.listen(events.add);
    await adapter.startScan();
    sdk.devices.add(const LiteDevice(id: 'ring-1', name: 'Ring', rssi: -45));
    await pumpEventQueue();

    await adapter.connect('ring-1');
    expect(sdk.hadConnectionListenerWhenConnectCalled, isTrue);
    sdk.connections['ring-1']!.add(
      const LiteConnectionState(state: LiteConnectionStateValue.connected),
    );
    await pumpEventQueue();

    expect(adapter.ringConnected, isTrue);
    expect(events.last.toJson(), {
      'event': 'connectionState',
      'data': {'deviceId': 'ring-1', 'state': 'connected'},
    });
    expect(adapter.snapshotEvents.map((event) => event.toJson()), [
      {
        'event': 'deviceDiscovered',
        'data': {'deviceId': 'ring-1', 'name': 'Ring', 'rssi': -45},
      },
      {
        'event': 'connectionState',
        'data': {'deviceId': 'ring-1', 'state': 'connected'},
      },
    ]);

    sdk.connections['ring-1']!.add(
      const LiteConnectionState(
        state: LiteConnectionStateValue.disconnected,
        errorCode: 'AUTH_FAILED',
      ),
    );
    await pumpEventQueue();
    expect(adapter.ringConnected, isFalse);
    expect(events.last.data['errorCode'], 'AUTH_FAILED');

    await subscription.cancel();
  });

  test('maps device info and forwards cached device status', () async {
    final events = <BridgeSdkEvent>[];
    final subscription = adapter.events.listen(events.add);
    await adapter.startScan();
    sdk.devices.add(const LiteDevice(id: 'ring-1', name: 'Ring', rssi: -45));
    await pumpEventQueue();
    sdk.deviceInfos['ring-1'] = const LiteDeviceInfo(
      firmwareVersion: '1.2.3',
      batteryPercent: 82,
      deviceState: 1,
      hasMeasurementHistory: true,
      hasSportHistory: true,
    );

    await adapter.connect('ring-1');
    sdk.connections['ring-1']!.add(
      const LiteConnectionState(state: LiteConnectionStateValue.connected),
    );
    await pumpEventQueue();
    expect(sdk.statuses['ring-1']?.hasListener, isTrue);

    expect(await adapter.getDeviceInfo('ring-1'), {
      'firmwareVersion': '1.2.3',
      'batteryPercent': 82,
      'deviceState': 1,
      'hasMeasurementHistory': true,
      'hasActivityHistory': false,
      'hasSportHistory': true,
    });

    sdk.statuses['ring-1']!.add(
      const LiteDeviceStatus(
        batteryPercent: 81,
        deviceState: 2,
        hasActivityHistory: true,
      ),
    );
    await pumpEventQueue();
    expect(events.last.toJson(), {
      'event': 'deviceStatus',
      'data': {
        'deviceId': 'ring-1',
        'battery': 81,
        'state': 2,
        'hasMeasurement': false,
        'hasActivity': true,
        'hasSport': false,
      },
    });
    expect(adapter.snapshotEvents.map((event) => event.event), [
      'deviceDiscovered',
      'connectionState',
      'deviceStatus',
    ]);

    await subscription.cancel();
  });

  test(
    'maps history records and retains a replayable completed snapshot',
    () async {
      final events = <BridgeSdkEvent>[];
      final subscription = adapter.events.listen(events.add);
      await _connectRing(sdk, adapter);

      await adapter.syncHistory('ring-1');
      expect(adapter.activeOperation, 'syncHistory');
      expect(sdk.historyDeviceId, 'ring-1');

      sdk.history.add(const HistoryTypeStarted(type: 'measurement', total: 1));
      sdk.history.add(
        const HistoryRecordReceived(
          type: 'measurement',
          record: MeasurementRecord(
            unixSec: 100,
            hr: 61,
            hrv: 32,
            spo2: 98,
            respRate: 14,
            hrSuccess: true,
            spo2Success: true,
          ),
          index: 0,
          total: 1,
        ),
      );
      sdk.history.add(
        const HistoryRecordReceived(
          type: 'sport',
          record: SportRecord(
            unixSec: 200,
            hr: 90,
            steps: 1200,
            activityCount: 4,
          ),
          index: 0,
          total: 1,
        ),
      );
      sdk.history.add(
        const HistoryRecordReceived(
          type: 'activity',
          record: ActivityRecord(
            unixSec: 300,
            batteryPercent: 75,
            steps: 4000,
            activeSeconds: 1800,
            temperaturesC: [36.2, 36.4],
          ),
          index: 0,
          total: 1,
        ),
      );
      sdk.history.add(
        const HistoryTypeCompleted(type: 'measurement', count: 1),
      );
      sdk.history.add(
        const HistoryAllCompleted(
          counts: {'measurement': 1, 'sport': 1, 'activity': 1},
        ),
      );
      await pumpEventQueue();

      final historyEvents = events
          .where((event) => event.event.startsWith('history'))
          .toList();
      final syncId = historyEvents.first.data['syncId'];
      expect(syncId, isA<String>());
      expect(historyEvents[0].toJson(), {
        'event': 'historyProgress',
        'data': {
          'deviceId': 'ring-1',
          'syncId': syncId,
          'phase': 'typeStarted',
          'type': 'measurement',
          'total': 1,
        },
      });
      expect(historyEvents[1].data['record'], {
        'unixSec': 100,
        'hr': 61,
        'hrv': 32,
        'spo2': 98,
        'respRate': 14,
        'hrSuccess': true,
        'spo2Success': true,
      });
      expect(historyEvents[2].data['record'], {
        'unixSec': 200,
        'hr': 90,
        'steps': 1200,
        'activityCount': 4,
      });
      expect(historyEvents[3].data['record'], {
        'unixSec': 300,
        'batteryPercent': 75,
        'steps': 4000,
        'activeSeconds': 1800,
        'temperaturesC': [36.2, 36.4],
      });
      expect(historyEvents.last.data['phase'], 'allCompleted');
      expect(adapter.activeOperation, isNull);
      expect(
        adapter.snapshotEvents
            .where((event) => event.event.startsWith('history'))
            .map((event) => event.toJson()),
        historyEvents.map((event) => event.toJson()),
      );

      await subscription.cancel();
    },
  );

  test(
    'forwards SpO2 and packet-batched PPG and ACC measurement data',
    () async {
      final events = <BridgeSdkEvent>[];
      final subscription = adapter.events.listen(events.add);
      await _connectRing(sdk, adapter);

      await adapter.startSpo2Verification('ring-1');
      expect(adapter.activeOperation, 'spo2Measurement');
      expect(sdk.measurementStartDeviceId, 'ring-1');
      expect(sdk.spo2.hasListener, isTrue);
      expect(sdk.ppg.hasListener, isTrue);
      expect(sdk.acc.hasListener, isTrue);

      sdk.spo2.add(
        Spo2Result(
          spo2: 98,
          success: true,
          measuredAt: DateTime.utc(2026, 8, 4, 10, 30),
          isVerified: true,
        ),
      );
      sdk.ppg.add(
        const PpgWave(
          packCount: 7,
          captureTime: 1234,
          samples: [
            PpgSample(ledG: 1, ledGAmb: 2, ledRedAmb: 3, ledIr: 4),
            PpgSample(ledG: 5, ledGAmb: 6, ledRedAmb: 7, ledIr: 8),
          ],
        ),
      );
      sdk.acc.add(
        const AccWave(
          packCount: 8,
          captureTime: 1235,
          samples: [AccSample3(x: -1, y: 2, z: 3)],
        ),
      );
      await pumpEventQueue();

      expect(
        events.where((event) => event.event == 'spo2Result').single.toJson(),
        {
          'event': 'spo2Result',
          'data': {
            'deviceId': 'ring-1',
            'spo2': 98,
            'hr': null,
            'success': true,
            'isVerified': true,
            'measuredAt': '2026-08-04T10:30:00.000Z',
          },
        },
      );
      expect(events.where((event) => event.event == 'ppgWave').single.data, {
        'deviceId': 'ring-1',
        'packCount': 7,
        'captureTime': 1234,
        'samples': [
          {'ledG': 1, 'ledGAmb': 2, 'ledRedAmb': 3, 'ledIr': 4},
          {'ledG': 5, 'ledGAmb': 6, 'ledRedAmb': 7, 'ledIr': 8},
        ],
      });
      expect(events.where((event) => event.event == 'accWave').single.data, {
        'deviceId': 'ring-1',
        'packCount': 8,
        'captureTime': 1235,
        'samples': [
          {'x': -1, 'y': 2, 'z': 3},
        ],
      });

      await adapter.stopMeasurement('ring-1');
      expect(sdk.measurementStopDeviceId, 'ring-1');
      expect(adapter.activeOperation, isNull);
      expect(sdk.spo2.hasListener, isFalse);
      expect(sdk.ppg.hasListener, isFalse);
      expect(sdk.acc.hasListener, isFalse);
      await subscription.cancel();
    },
  );

  test(
    'keeps sync active across callers and preserves official errors',
    () async {
      final events = <BridgeSdkEvent>[];
      final subscription = adapter.events.listen(events.add);
      await _connectRing(sdk, adapter);

      await adapter.syncHistory('ring-1');
      await expectLater(
        adapter.disconnect('ring-1'),
        throwsA(
          isA<AlloopBlueLiteException>().having(
            (error) => error.code,
            'code',
            'BRIDGE_BUSY',
          ),
        ),
      );
      sdk.history.addError(
        const AlloopBlueLiteException('HISTORY_TIMEOUT', 'History timed out'),
      );
      await pumpEventQueue();

      final error = events.last;
      expect(error.event, 'bridgeError');
      expect(error.data['operation'], 'syncHistory');
      expect(error.data['code'], 'HISTORY_TIMEOUT');
      expect(adapter.activeOperation, isNull);
      expect(adapter.snapshotEvents.last.toJson(), error.toJson());

      await subscription.cancel();
    },
  );

  test('deduplicates history indexes before replay and completion', () async {
    final events = <BridgeSdkEvent>[];
    final subscription = adapter.events.listen(events.add);
    await _connectRing(sdk, adapter);
    await adapter.syncHistory('ring-1');

    const record = HistoryRecordReceived(
      type: 'measurement',
      record: MeasurementRecord(
        unixSec: 100,
        hr: 61,
        hrv: 32,
        spo2: 98,
        respRate: 14,
        hrSuccess: true,
        spo2Success: true,
      ),
      index: 0,
      total: 1,
    );
    sdk.history.add(record);
    sdk.history.add(record);
    sdk.history.add(
      const HistoryAllCompleted(
        counts: {'measurement': 1, 'sport': 0, 'activity': 0},
      ),
    );
    await pumpEventQueue();

    expect(
      events.where((event) => event.event == 'historyRecord'),
      hasLength(1),
    );
    expect(events.last.data['phase'], 'allCompleted');
    expect(adapter.activeOperation, isNull);
    await subscription.cancel();
  });

  test(
    'reports incomplete history instead of accepting an index gap',
    () async {
      final events = <BridgeSdkEvent>[];
      final subscription = adapter.events.listen(events.add);
      await _connectRing(sdk, adapter);
      await adapter.syncHistory('ring-1');

      sdk.history.add(
        const HistoryRecordReceived(
          type: 'measurement',
          record: MeasurementRecord(
            unixSec: 100,
            hr: 61,
            hrv: 32,
            spo2: 98,
            respRate: 14,
            hrSuccess: true,
            spo2Success: true,
          ),
          index: 1,
          total: 2,
        ),
      );
      sdk.history.add(
        const HistoryAllCompleted(
          counts: {'measurement': 2, 'sport': 0, 'activity': 0},
        ),
      );
      await pumpEventQueue();

      expect(events.last.event, 'bridgeError');
      expect(events.last.data['code'], 'BRIDGE_HISTORY_INCOMPLETE');
      expect(adapter.activeOperation, isNull);
      await subscription.cancel();
    },
  );

  test(
    'finishes history with a replayable error when ring disconnects',
    () async {
      final events = <BridgeSdkEvent>[];
      final subscription = adapter.events.listen(events.add);
      await _connectRing(sdk, adapter);
      await adapter.syncHistory('ring-1');

      sdk.connections['ring-1']!.add(
        const LiteConnectionState(state: LiteConnectionStateValue.disconnected),
      );
      await pumpEventQueue();

      final error = events.firstWhere(
        (event) =>
            event.event == 'bridgeError' &&
            event.data['operation'] == 'syncHistory',
      );
      expect(error.data['code'], 'BRIDGE_RING_DISCONNECTED');
      expect(adapter.activeOperation, isNull);
      expect(adapter.snapshotEvents, contains(error));
      await subscription.cancel();
    },
  );

  test('stops the SDK measurement when a realtime stream fails', () async {
    final events = <BridgeSdkEvent>[];
    final subscription = adapter.events.listen(events.add);
    await _connectRing(sdk, adapter);
    await adapter.startSpo2Verification('ring-1');

    sdk.ppg.addError(
      const AlloopBlueLiteException('PPG_STREAM_FAILED', 'PPG failed'),
    );
    await pumpEventQueue();

    expect(sdk.measurementStopDeviceId, 'ring-1');
    expect(adapter.activeOperation, isNull);
    expect(events.last.event, 'bridgeError');
    expect(events.last.data, containsPair('operation', 'spo2Measurement'));
    expect(events.last.data, containsPair('stream', 'ppg'));
    expect(events.last.data, containsPair('code', 'PPG_STREAM_FAILED'));
    await subscription.cancel();
  });
}

Future<void> _connectRing(
  FakeAlloopSdk sdk,
  AlloopBridgeAdapter adapter,
) async {
  await adapter.startScan();
  sdk.devices.add(const LiteDevice(id: 'ring-1', name: 'Ring', rssi: -45));
  await pumpEventQueue();
  await adapter.connect('ring-1');
  sdk.connections['ring-1']!.add(
    const LiteConnectionState(state: LiteConnectionStateValue.connected),
  );
  await pumpEventQueue();
}

class FakeAlloopSdk implements AlloopSdkClient {
  final StreamController<LiteDevice> devices =
      StreamController<LiteDevice>.broadcast();
  final StreamController<bool> scanning = StreamController<bool>.broadcast();
  final Map<String, StreamController<LiteConnectionState>> connections = {};
  final Map<String, StreamController<LiteDeviceStatus>> statuses = {};
  final Map<String, LiteDeviceInfo> deviceInfos = {};
  final StreamController<HistorySyncEvent> history =
      StreamController<HistorySyncEvent>.broadcast();
  final StreamController<Spo2Result> spo2 =
      StreamController<Spo2Result>.broadcast();
  final StreamController<PpgWave> ppg = StreamController<PpgWave>.broadcast();
  final StreamController<AccWave> acc = StreamController<AccWave>.broadcast();

  int initializeCalls = 0;
  Duration? lastTimeout;
  String? lastNameFilter;
  bool hadConnectionListenerWhenConnectCalled = false;
  String? historyDeviceId;
  String? measurementStartDeviceId;
  String? measurementStopDeviceId;

  @override
  Stream<LiteDevice> get deviceDiscoveredStream => devices.stream;

  @override
  Stream<bool> get isScanningStream => scanning.stream;

  @override
  Future<void> initialize() async => initializeCalls++;

  @override
  Future<void> startScan({Duration? timeout, String? nameFilter}) async {
    lastTimeout = timeout;
    lastNameFilter = nameFilter;
  }

  @override
  Future<void> stopScan() async {}

  @override
  Stream<LiteConnectionState> connectionStateStream(String deviceId) =>
      connections
          .putIfAbsent(
            deviceId,
            () => StreamController<LiteConnectionState>.broadcast(),
          )
          .stream;

  @override
  Future<void> connect(String deviceId) async {
    hadConnectionListenerWhenConnectCalled =
        connections[deviceId]?.hasListener ?? false;
  }

  @override
  Future<void> disconnect(String deviceId) async {}

  @override
  Future<LiteDeviceInfo> getDeviceInfo(String deviceId) async =>
      deviceInfos[deviceId]!;

  @override
  Stream<LiteDeviceStatus> deviceStatusStream(String deviceId) => statuses
      .putIfAbsent(
        deviceId,
        () => StreamController<LiteDeviceStatus>.broadcast(),
      )
      .stream;

  @override
  Future<void> startSpo2Verification(String deviceId) async {
    measurementStartDeviceId = deviceId;
  }

  @override
  Future<void> stopMeasurement(String deviceId) async {
    measurementStopDeviceId = deviceId;
  }

  @override
  Stream<Spo2Result> spo2ResultStream(String deviceId) => spo2.stream;

  @override
  Stream<PpgWave> ppgWaveStream(String deviceId) => ppg.stream;

  @override
  Stream<AccWave> accStream(String deviceId) => acc.stream;

  @override
  Stream<HistorySyncEvent> syncHistory(String deviceId) {
    historyDeviceId = deviceId;
    return history.stream;
  }

  Future<void> dispose() async {
    await devices.close();
    await scanning.close();
    await history.close();
    await spo2.close();
    await ppg.close();
    await acc.close();
    for (final controller in connections.values) {
      await controller.close();
    }
    for (final controller in statuses.values) {
      await controller.close();
    }
  }
}
