import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:alloop/features/web_bridge/data/bridge_server.dart';
import 'package:alloop/features/web_bridge/data/alloop_bridge_adapter.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late BridgeServer server;
  late FakeRingOperations ringOperations;

  setUp(() async {
    ringOperations = FakeRingOperations();
    server = BridgeServer(
      requestedPort: 0,
      bindAddress: InternetAddress.loopbackIPv4,
      tokenGenerator: () => 'test-token',
      ringOperations: ringOperations,
    );
    await server.start();
  });

  tearDown(() => server.dispose());

  test('generates a four-digit temporary token by default', () async {
    final generatedTokenServer = BridgeServer(
      requestedPort: 0,
      bindAddress: InternetAddress.loopbackIPv4,
    );

    try {
      await generatedTokenServer.start();
      expect(generatedTokenServer.token, matches(RegExp(r'^\d{4}$')));
    } finally {
      await generatedTokenServer.dispose();
    }
  });

  test('requires token authentication before RPC requests', () async {
    final socket = await _connect(server.port);
    socket.add(jsonEncode({'id': '1', 'method': 'ping', 'params': {}}));

    final response = jsonDecode(await socket.first as String);

    expect(response['ok'], isFalse);
    expect(response['error']['code'], 'BRIDGE_AUTH_REQUIRED');
  });

  test('authenticates and serves ping and bridge state', () async {
    final socket = await _connect(server.port);
    final messages = StreamIterator<Object?>(socket);

    socket.add(
      jsonEncode({
        'id': 'auth-1',
        'method': 'authenticate',
        'params': {'token': 'test-token'},
      }),
    );
    expect(await messages.moveNext(), isTrue);
    expect(jsonDecode(messages.current as String)['ok'], isTrue);

    socket.add(
      jsonEncode({'id': 'state-1', 'method': 'getBridgeState', 'params': {}}),
    );
    expect(await messages.moveNext(), isTrue);
    final stateResponse = jsonDecode(messages.current as String);
    expect(stateResponse['result']['webClientConnected'], isTrue);

    socket.add(jsonEncode({'id': 'ping-1', 'method': 'ping', 'params': {}}));
    expect(await messages.moveNext(), isTrue);
    final pingResponse = jsonDecode(messages.current as String);
    expect(pingResponse['result']['bridgeVersion'], '1.0.0');

    await messages.cancel();
    await socket.close();
  });

  test('rejects a second web client', () async {
    final first = await _connect(server.port);

    await expectLater(
      _connect(server.port),
      throwsA(isA<WebSocketException>()),
    );

    await first.close();
  });

  test('serves 100 authenticated ping requests on one connection', () async {
    final socket = await _connect(server.port);
    final messages = StreamIterator<Object?>(socket);
    socket.add(
      jsonEncode({
        'id': 'auth-stress',
        'method': 'authenticate',
        'params': {'token': 'test-token'},
      }),
    );
    expect(await messages.moveNext(), isTrue);

    for (var index = 0; index < 100; index++) {
      socket.add(
        jsonEncode({'id': 'ping-$index', 'method': 'ping', 'params': {}}),
      );
      expect(await messages.moveNext(), isTrue);
      final response = jsonDecode(messages.current as String);
      expect(response['id'], 'ping-$index');
      expect(response['ok'], isTrue);
    }

    await messages.cancel();
    await socket.close();
  });

  test('forwards SDK events and exposes real ring state', () async {
    final socket = await _connect(server.port);
    final messages = StreamIterator<Object?>(socket);
    socket.add(
      jsonEncode({
        'id': 'auth-events',
        'method': 'authenticate',
        'params': {'token': 'test-token'},
      }),
    );
    expect(await messages.moveNext(), isTrue);

    ringOperations.emitConnected('ring-1');
    expect(await messages.moveNext(), isTrue);
    final event = jsonDecode(messages.current as String);
    expect(event, {
      'event': 'connectionState',
      'data': {'deviceId': 'ring-1', 'state': 'connected'},
    });

    socket.add(
      jsonEncode({
        'id': 'state-ring',
        'method': 'getBridgeState',
        'params': {},
      }),
    );
    expect(await messages.moveNext(), isTrue);
    final stateResponse = jsonDecode(messages.current as String);
    expect(stateResponse['result']['ringConnected'], isTrue);

    await messages.cancel();
    await socket.close();
  });

  test(
    'replays discovered device and connection after authentication',
    () async {
      ringOperations
        ..connected = true
        ..snapshot = const [
          BridgeSdkEvent('deviceDiscovered', {
            'deviceId': 'ring-replay',
            'name': 'AlloopRing-4555',
            'rssi': -70,
          }),
          BridgeSdkEvent('connectionState', {
            'deviceId': 'ring-replay',
            'state': 'connected',
          }),
          BridgeSdkEvent('deviceStatus', {
            'deviceId': 'ring-replay',
            'battery': 82,
            'state': 1,
            'hasMeasurement': true,
            'hasActivity': false,
            'hasSport': true,
          }),
        ];
      final socket = await _connect(server.port);
      final messages = StreamIterator<Object?>(socket);
      socket.add(
        jsonEncode({
          'id': 'auth-replay',
          'method': 'authenticate',
          'params': {'token': 'test-token'},
        }),
      );

      expect(await messages.moveNext(), isTrue);
      expect(jsonDecode(messages.current as String)['id'], 'auth-replay');
      expect(await messages.moveNext(), isTrue);
      expect(
        jsonDecode(messages.current as String)['event'],
        'deviceDiscovered',
      );
      expect(await messages.moveNext(), isTrue);
      final connection = jsonDecode(messages.current as String);
      expect(connection['event'], 'connectionState');
      expect(connection['data']['state'], 'connected');
      expect(await messages.moveNext(), isTrue);
      final status = jsonDecode(messages.current as String);
      expect(status['event'], 'deviceStatus');
      expect(status['data']['battery'], 82);

      await messages.cancel();
      await socket.close();
    },
  );
}

Future<WebSocket> _connect(int port) {
  return WebSocket.connect('ws://127.0.0.1:$port/ws');
}

class FakeRingOperations implements BridgeRingOperations {
  final StreamController<BridgeSdkEvent> controller =
      StreamController<BridgeSdkEvent>.broadcast();
  bool connected = false;
  Iterable<BridgeSdkEvent> snapshot = const [];

  @override
  Stream<BridgeSdkEvent> get events => controller.stream;

  @override
  bool get ringConnected => connected;

  @override
  String? get activeOperation => null;

  @override
  Iterable<BridgeSdkEvent> get snapshotEvents => snapshot;

  void emitConnected(String deviceId) {
    connected = true;
    controller.add(
      BridgeSdkEvent('connectionState', {
        'deviceId': deviceId,
        'state': 'connected',
      }),
    );
  }

  @override
  Future<void> initialize() async {}

  @override
  Future<void> startScan({Duration? timeout, String? nameFilter}) async {}

  @override
  Future<void> stopScan() async {}

  @override
  Future<void> connect(String deviceId) async {}

  @override
  Future<void> disconnect(String deviceId) async {}

  @override
  Future<Map<String, dynamic>> getDeviceInfo(String deviceId) async => {};

  @override
  Future<void> startSpo2Verification(String deviceId) async {}

  @override
  Future<void> stopMeasurement(String deviceId) async {}

  @override
  Future<void> syncHistory(String deviceId) async {}

  @override
  Future<void> dispose() => controller.close();
}
