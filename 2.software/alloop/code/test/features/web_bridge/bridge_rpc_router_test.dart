import 'package:alloop/features/web_bridge/data/bridge_rpc_router.dart';
import 'dart:async';

import 'package:alloop/features/web_bridge/data/alloop_bridge_adapter.dart';
import 'package:alloop/features/web_bridge/domain/bridge_message.dart';
import 'package:alloop/features/web_bridge/domain/bridge_state.dart';
import 'package:alloop_blue_lite/alloop_blue_lite.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('BridgeRequest validates the request envelope', () {
    final request = BridgeRequest.fromJson({
      'id': 'req-1',
      'method': 'ping',
      'params': <String, dynamic>{},
    });

    expect(request.id, 'req-1');
    expect(request.method, 'ping');
    expect(request.params, isEmpty);
  });

  test('ping returns server time and bridge version', () async {
    final router = BridgeRpcRouter(
      stateProvider: BridgeState.stopped,
      clock: () => DateTime.utc(2026, 8, 3, 12, 30),
    );

    final response = await router.route(
      const BridgeRequest(id: 'req-2', method: 'ping', params: {}),
    );

    expect(response.toJson(), {
      'id': 'req-2',
      'ok': true,
      'result': {
        'serverTime': '2026-08-03T12:30:00.000Z',
        'bridgeVersion': '1.0.0',
      },
    });
  });

  test('getBridgeState returns independent bridge state fields', () async {
    final router = BridgeRpcRouter(
      stateProvider: () => const BridgeState(
        serviceRunning: true,
        webClientConnected: true,
        ringConnected: false,
        port: 8766,
      ),
    );

    final response = await router.route(
      const BridgeRequest(id: 'req-3', method: 'getBridgeState', params: {}),
    );

    expect(response.toJson()['result'], containsPair('ringConnected', false));
    expect(
      response.toJson()['result'],
      containsPair('webClientConnected', true),
    );
  });

  test('routes scan and connect through ring operations', () async {
    final operations = FakeRingOperations();
    final router = BridgeRpcRouter(
      stateProvider: BridgeState.stopped,
      ringOperations: operations,
    );

    final scanResponse = await router.route(
      const BridgeRequest(
        id: 'scan-1',
        method: 'startScan',
        params: {'timeoutMs': 5000, 'nameFilter': 'Alloop'},
      ),
    );
    final connectResponse = await router.route(
      const BridgeRequest(
        id: 'connect-1',
        method: 'connect',
        params: {'deviceId': 'sdk-id'},
      ),
    );

    expect(scanResponse.toJson(), {'id': 'scan-1', 'ok': true, 'result': null});
    expect(operations.timeout, const Duration(seconds: 5));
    expect(operations.nameFilter, 'Alloop');
    expect(connectResponse.ok, isTrue);
    expect(operations.connectedDeviceId, 'sdk-id');
  });

  test('preserves official SDK errors', () async {
    final operations = FakeRingOperations(
      connectError: const AlloopBlueLiteException(
        'AUTH_FAILED',
        'Authentication failed',
      ),
    );
    final router = BridgeRpcRouter(
      stateProvider: BridgeState.stopped,
      ringOperations: operations,
    );

    final response = await router.route(
      const BridgeRequest(
        id: 'connect-2',
        method: 'connect',
        params: {'deviceId': 'sdk-id'},
      ),
    );

    expect(response.toJson()['error'], {
      'code': 'AUTH_FAILED',
      'message': 'Authentication failed',
    });
  });

  test('returns official device info fields', () async {
    final operations = FakeRingOperations();
    final router = BridgeRpcRouter(
      stateProvider: BridgeState.stopped,
      ringOperations: operations,
    );

    final response = await router.route(
      const BridgeRequest(
        id: 'info-1',
        method: 'getDeviceInfo',
        params: {'deviceId': 'sdk-id'},
      ),
    );

    expect(operations.infoDeviceId, 'sdk-id');
    expect(response.toJson(), {
      'id': 'info-1',
      'ok': true,
      'result': {
        'firmwareVersion': '1.2.3',
        'batteryPercent': 82,
        'deviceState': 1,
        'hasMeasurementHistory': true,
        'hasActivityHistory': false,
        'hasSportHistory': true,
      },
    });
  });

  test('routes history sync and preserves busy errors', () async {
    final operations = FakeRingOperations();
    final router = BridgeRpcRouter(
      stateProvider: BridgeState.stopped,
      ringOperations: operations,
    );

    final response = await router.route(
      const BridgeRequest(
        id: 'history-1',
        method: 'syncHistory',
        params: {'deviceId': 'sdk-id'},
      ),
    );
    expect(response.toJson(), {'id': 'history-1', 'ok': true, 'result': null});
    expect(operations.historyDeviceId, 'sdk-id');

    operations.historyError = const AlloopBlueLiteException(
      'BRIDGE_BUSY',
      'Bridge is busy with syncHistory',
    );
    final busy = await router.route(
      const BridgeRequest(
        id: 'history-2',
        method: 'syncHistory',
        params: {'deviceId': 'sdk-id'},
      ),
    );
    expect(busy.error?.code, 'BRIDGE_BUSY');
  });

  test('routes measurement start and stop', () async {
    final operations = FakeRingOperations();
    final router = BridgeRpcRouter(
      stateProvider: BridgeState.stopped,
      ringOperations: operations,
    );

    final started = await router.route(
      const BridgeRequest(
        id: 'measure-1',
        method: 'startSpo2Verification',
        params: {'deviceId': 'sdk-id'},
      ),
    );
    final stopped = await router.route(
      const BridgeRequest(
        id: 'measure-2',
        method: 'stopMeasurement',
        params: {'deviceId': 'sdk-id'},
      ),
    );

    expect(started.ok, isTrue);
    expect(stopped.ok, isTrue);
    expect(operations.measurementStartDeviceId, 'sdk-id');
    expect(operations.measurementStopDeviceId, 'sdk-id');
  });

  test('rejects malformed scan and device parameters', () async {
    final router = BridgeRpcRouter(
      stateProvider: BridgeState.stopped,
      ringOperations: FakeRingOperations(),
    );

    final badTimeout = await router.route(
      const BridgeRequest(
        id: 'scan-2',
        method: 'startScan',
        params: {'timeoutMs': 0},
      ),
    );
    final missingDevice = await router.route(
      const BridgeRequest(id: 'connect-3', method: 'connect', params: {}),
    );

    expect(badTimeout.error?.code, 'BRIDGE_INVALID_PARAMS');
    expect(missingDevice.error?.code, 'BRIDGE_INVALID_PARAMS');
  });
}

class FakeRingOperations implements BridgeRingOperations {
  FakeRingOperations({this.connectError});

  final Object? connectError;
  final StreamController<BridgeSdkEvent> controller =
      StreamController<BridgeSdkEvent>.broadcast();
  Duration? timeout;
  String? nameFilter;
  String? connectedDeviceId;
  String? infoDeviceId;
  String? historyDeviceId;
  String? measurementStartDeviceId;
  String? measurementStopDeviceId;
  Object? historyError;

  @override
  Stream<BridgeSdkEvent> get events => controller.stream;

  @override
  bool get ringConnected => false;

  @override
  String? get activeOperation => null;

  @override
  Iterable<BridgeSdkEvent> get snapshotEvents => const [];

  @override
  Future<void> initialize() async {}

  @override
  Future<void> startScan({Duration? timeout, String? nameFilter}) async {
    this.timeout = timeout;
    this.nameFilter = nameFilter;
  }

  @override
  Future<void> stopScan() async {}

  @override
  Future<void> connect(String deviceId) async {
    if (connectError != null) throw connectError!;
    connectedDeviceId = deviceId;
  }

  @override
  Future<void> disconnect(String deviceId) async {}

  @override
  Future<Map<String, dynamic>> getDeviceInfo(String deviceId) async {
    infoDeviceId = deviceId;
    return {
      'firmwareVersion': '1.2.3',
      'batteryPercent': 82,
      'deviceState': 1,
      'hasMeasurementHistory': true,
      'hasActivityHistory': false,
      'hasSportHistory': true,
    };
  }

  @override
  Future<void> startSpo2Verification(String deviceId) async {
    measurementStartDeviceId = deviceId;
  }

  @override
  Future<void> stopMeasurement(String deviceId) async {
    measurementStopDeviceId = deviceId;
  }

  @override
  Future<void> syncHistory(String deviceId) async {
    if (historyError != null) throw historyError!;
    historyDeviceId = deviceId;
  }

  @override
  Future<void> dispose() => controller.close();
}
