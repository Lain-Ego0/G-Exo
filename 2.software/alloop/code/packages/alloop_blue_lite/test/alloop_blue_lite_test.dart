import 'package:alloop_blue_lite/alloop_blue_lite.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const methodChannel = MethodChannel('alloop_blue_lite/methods');
  const scanChannel = EventChannel('alloop_blue_lite/events/scan');
  const connectionChannel = EventChannel('alloop_blue_lite/events/connection');
  const deviceStatusChannel = EventChannel('alloop_blue_lite/events/device_status');
  const spo2Channel = EventChannel('alloop_blue_lite/events/spo2');
  const ppgChannel = EventChannel('alloop_blue_lite/events/ppg');
  const historyChannel = EventChannel('alloop_blue_lite/events/history');

  final lite = AlloopBlueLite.instance;

  setUp(() {
    lite.resetForTest();
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(methodChannel, null);
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(scanChannel, null);
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(connectionChannel, null);
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(deviceStatusChannel, null);
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(spo2Channel, null);
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(ppgChannel, null);
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(historyChannel, null);
  });

  group('startScan', () {
    test('invokes startScan with nameFilter and timeoutMs', () async {
      MethodCall? capturedCall;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(methodChannel, (call) async {
        capturedCall = call;
        return null;
      });
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(
        scanChannel,
        MockStreamHandler.inline(onListen: (arguments, events) {}),
      );

      await lite.startScan(nameFilter: 'Alloop', timeout: const Duration(seconds: 5));

      expect(capturedCall!.method, 'startScan');
      expect(capturedCall!.arguments, {'nameFilter': 'Alloop', 'timeoutMs': 5000});
    });

    test('isScanning toggles true/false on startScan/stopScan', () async {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(methodChannel, (call) async => null);
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(
        scanChannel,
        MockStreamHandler.inline(onListen: (arguments, events) {}),
      );

      final states = <bool>[];
      final sub = lite.isScanningStream.listen(states.add);

      await lite.startScan();
      expect(lite.isScanning, isTrue);

      await lite.stopScan();
      expect(lite.isScanning, isFalse);

      await Future<void>.delayed(Duration.zero);
      expect(states, [true, false]);
      await sub.cancel();
    });

    test('isScanning flips to false locally after the scan timeout elapses', () async {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(methodChannel, (call) async => null);
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(
        scanChannel,
        MockStreamHandler.inline(onListen: (arguments, events) {}),
      );

      final states = <bool>[];
      final sub = lite.isScanningStream.listen(states.add);

      await lite.startScan(timeout: const Duration(milliseconds: 10));
      expect(lite.isScanning, isTrue);

      await Future<void>.delayed(const Duration(milliseconds: 20));

      expect(lite.isScanning, isFalse);
      expect(states, [true, false]);
      await sub.cancel();
    });

    test('a subsequent stopScan after the timeout mirror already fired is a no-op on state', () async {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(methodChannel, (call) async => null);
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(
        scanChannel,
        MockStreamHandler.inline(onListen: (arguments, events) {}),
      );

      final states = <bool>[];
      final sub = lite.isScanningStream.listen(states.add);

      await lite.startScan(timeout: const Duration(milliseconds: 10));
      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(lite.isScanning, isFalse);

      await lite.stopScan();
      expect(lite.isScanning, isFalse);

      await Future<void>.delayed(Duration.zero);
      expect(states, [true, false, false]);
      await sub.cancel();
    });
  });

  test('scan event map is converted to LiteDevice', () async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(methodChannel, (call) async => null);

    late MockStreamHandlerEventSink sink;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(
      scanChannel,
      MockStreamHandler.inline(onListen: (arguments, events) => sink = events),
    );

    final future = lite.deviceDiscoveredStream.first;
    await lite.startScan();

    sink.success({'id': 'AA:BB:CC', 'name': 'Alloop Kit', 'rssi': -42});

    final device = await future;
    expect(device.id, 'AA:BB:CC');
    expect(device.name, 'Alloop Kit');
    expect(device.rssi, -42);
  });

  test(
    'a scan event emitted immediately on listen (i.e. right after the native '
    'startScan call) is not lost even when the app only subscribes to '
    'deviceDiscoveredStream after startScan() returns '
    '(regression: scan pipeline must attach before the native invocation)',
    () async {
      late MockStreamHandlerEventSink sink;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(
        scanChannel,
        MockStreamHandler.inline(
          onListen: (arguments, events) {
            sink = events;
            // Simulate the native side emitting a discovery result the
            // instant the scan channel is listened to — i.e. before the
            // startScan method call has even returned.
            sink.success({'id': 'AA:BB:CC', 'name': 'Alloop Kit', 'rssi': -42});
          },
        ),
      );
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(
        methodChannel,
        (call) async => null,
      );

      await lite.startScan();

      // Only now does the app start listening to deviceDiscoveredStream.
      final devices = <LiteDevice>[];
      final sub = lite.deviceDiscoveredStream.listen(devices.add);
      await Future<void>.delayed(Duration.zero);

      expect(devices, hasLength(1));
      expect(devices.single.id, 'AA:BB:CC');

      await sub.cancel();
    },
  );

  group('connection events', () {
    test('connectionStateStream emits states filtered by deviceId', () async {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(methodChannel, (call) async => null);

      late MockStreamHandlerEventSink sink;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(
        connectionChannel,
        MockStreamHandler.inline(onListen: (arguments, events) => sink = events),
      );

      final states = <LiteConnectionState>[];
      final sub = lite.connectionStateStream('dev-1').listen(states.add);
      await Future<void>.delayed(Duration.zero);

      sink.success({'deviceId': 'dev-2', 'state': 'connecting'}); // filtered out
      sink.success({'deviceId': 'dev-1', 'state': 'connecting'});
      sink.success({'deviceId': 'dev-1', 'state': 'connected'});
      sink.success({'deviceId': 'dev-1', 'state': 'disconnected', 'errorCode': 'TIMEOUT'});

      await Future<void>.delayed(Duration.zero);

      expect(states, hasLength(3));
      expect(states[0].state, LiteConnectionStateValue.connecting);
      expect(states[1].state, LiteConnectionStateValue.connected);
      expect(states[2].state, LiteConnectionStateValue.disconnected);
      expect(states[2].errorCode, 'TIMEOUT');

      await sub.cancel();
    });

    test('connectedDevicesStream derives [] / [device] from connection events', () async {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(methodChannel, (call) async => null);

      late MockStreamHandlerEventSink sink;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(
        connectionChannel,
        MockStreamHandler.inline(onListen: (arguments, events) => sink = events),
      );

      final snapshots = <List<LiteDevice>>[];
      final sub = lite.connectedDevicesStream.listen(snapshots.add);
      // Ensure the underlying connection listener is attached.
      final stateSub = lite.connectionStateStream('dev-1').listen((_) {});
      await Future<void>.delayed(Duration.zero);

      sink.success({'deviceId': 'dev-1', 'state': 'connected'});
      sink.success({'deviceId': 'dev-1', 'state': 'disconnected'});

      await Future<void>.delayed(Duration.zero);

      // snapshots[0] is the replayed "currently connected" snapshot delivered
      // synchronously on listen (empty, since nothing was connected yet).
      expect(snapshots, hasLength(3));
      expect(snapshots[0], isEmpty);
      expect(snapshots[1], hasLength(1));
      expect(snapshots[1].first.id, 'dev-1');
      expect(snapshots[2], isEmpty);

      await sub.cancel();
      await stateSub.cancel();
    });

    test('connectedDevicesStream replays the current connected list to a late subscriber', () async {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(methodChannel, (call) async => null);

      late MockStreamHandlerEventSink sink;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(
        connectionChannel,
        MockStreamHandler.inline(onListen: (arguments, events) => sink = events),
      );

      // Establish the connection listener and connect a device before anyone
      // subscribes to connectedDevicesStream (simulates the scan page having
      // been popped and later re-entered).
      final stateSub = lite.connectionStateStream('dev-1').listen((_) {});
      await Future<void>.delayed(Duration.zero);

      sink.success({'deviceId': 'dev-1', 'state': 'connected'});
      await Future<void>.delayed(Duration.zero);

      final snapshots = <List<LiteDevice>>[];
      final lateSub = lite.connectedDevicesStream.listen(snapshots.add);
      await Future<void>.delayed(Duration.zero);

      expect(snapshots, hasLength(1));
      expect(snapshots.single, hasLength(1));
      expect(snapshots.single.first.id, 'dev-1');

      await stateSub.cancel();
      await lateSub.cancel();
    });

    test('connectionStateStream replays the last known state to a late subscriber', () async {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(methodChannel, (call) async => null);

      late MockStreamHandlerEventSink sink;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(
        connectionChannel,
        MockStreamHandler.inline(onListen: (arguments, events) => sink = events),
      );

      final firstSub = lite.connectionStateStream('dev-1').listen((_) {});
      await Future<void>.delayed(Duration.zero);

      sink.success({'deviceId': 'dev-1', 'state': 'connected'});
      await Future<void>.delayed(Duration.zero);

      // Simulate a page (e.g. device_detail) leaving and re-entering: it
      // cancels its old subscription and creates a fresh one later.
      await firstSub.cancel();

      final replayed = <LiteConnectionState>[];
      final lateSub = lite.connectionStateStream('dev-1').listen(replayed.add);
      await Future<void>.delayed(Duration.zero);

      expect(replayed, hasLength(1));
      expect(replayed.single.state, LiteConnectionStateValue.connected);

      await lateSub.cancel();
    });
  });

  group('spo2 channel', () {
    test('kind=result maps to Spo2Result with isVerified=false', () async {
      late MockStreamHandlerEventSink sink;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(
        spo2Channel,
        MockStreamHandler.inline(onListen: (arguments, events) => sink = events),
      );

      final future = lite.spo2ResultStream('dev-1').first;
      await Future<void>.delayed(Duration.zero);

      sink.success({'kind': 'result', 'spo2': 97, 'spo2Success': true, 'hr': 72, 'hrSuccess': true});

      final result = await future;
      expect(result.isVerified, isFalse);
      expect(result.spo2, 97);
      expect(result.hr, 72);
      expect(result.success, isTrue);
      expect(result.measuredAt, isNull);
    });

    test('kind=verify maps to Spo2Result with measuredAt and isVerified=true', () async {
      late MockStreamHandlerEventSink sink;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(
        spo2Channel,
        MockStreamHandler.inline(onListen: (arguments, events) => sink = events),
      );

      final future = lite.spo2ResultStream('dev-1').first;
      await Future<void>.delayed(Duration.zero);

      const unixSec = 1700000000;
      sink.success({'kind': 'verify', 'unixSec': unixSec, 'spo2': 95, 'success': true, 'timeSynced': true});

      final result = await future;
      expect(result.isVerified, isTrue);
      expect(result.spo2, 95);
      expect(result.success, isTrue);
      expect(result.measuredAt, DateTime.fromMillisecondsSinceEpoch(unixSec * 1000, isUtc: true));
    });
  });

  group('ppg channel', () {
    test('kind=ppg maps to PpgWave with sample fields', () async {
      late MockStreamHandlerEventSink sink;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(
        ppgChannel,
        MockStreamHandler.inline(onListen: (arguments, events) => sink = events),
      );

      final future = lite.ppgWaveStream('dev-1').first;
      await Future<void>.delayed(Duration.zero);

      sink.success({
        'kind': 'ppg',
        'packCount': 10,
        'captureTime': 123456,
        'samples': [
          {'ledG': 1, 'ledGAmb': 2, 'ledRedAmb': 3, 'ledIr': 4},
        ],
      });

      final wave = await future;
      expect(wave.packCount, 10);
      expect(wave.captureTime, 123456);
      expect(wave.samples, hasLength(1));
      expect(wave.samples.first.ledG, 1);
      expect(wave.samples.first.ledGAmb, 2);
      expect(wave.samples.first.ledRedAmb, 3);
      expect(wave.samples.first.ledIr, 4);
    });

    test('kind=acc is routed to accStream and not to ppgWaveStream', () async {
      late MockStreamHandlerEventSink sink;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(
        ppgChannel,
        MockStreamHandler.inline(onListen: (arguments, events) => sink = events),
      );

      final waves = <PpgWave>[];
      final accWaves = <AccWave>[];
      final ppgSub = lite.ppgWaveStream('dev-1').listen(waves.add);
      final accSub = lite.accStream('dev-1').listen(accWaves.add);
      await Future<void>.delayed(Duration.zero);

      sink.success({
        'kind': 'acc',
        'packCount': 5,
        'captureTime': 111,
        'samples': [
          {'x': 10, 'y': -10, 'z': 0},
        ],
      });
      sink.success({
        'kind': 'ppg',
        'packCount': 6,
        'captureTime': 222,
        'samples': <Map<String, dynamic>>[],
      });

      await Future<void>.delayed(Duration.zero);

      expect(waves, hasLength(1));
      expect(waves.single.packCount, 6);

      expect(accWaves, hasLength(1));
      expect(accWaves.single.packCount, 5);
      expect(accWaves.single.captureTime, 111);
      expect(accWaves.single.samples, hasLength(1));
      expect(accWaves.single.samples.first.x, 10);
      expect(accWaves.single.samples.first.y, -10);
      expect(accWaves.single.samples.first.z, 0);

      await ppgSub.cancel();
      await accSub.cancel();
    });
  });

  group('history sync', () {
    test('full sequence yields typed events and closes after allCompleted', () async {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(methodChannel, (call) async => null);

      late MockStreamHandlerEventSink sink;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(
        historyChannel,
        MockStreamHandler.inline(onListen: (arguments, events) => sink = events),
      );

      final events = <HistorySyncEvent>[];
      var done = false;
      final sub = lite.syncHistory('dev-1').listen(
        events.add,
        onDone: () => done = true,
      );

      await Future<void>.delayed(Duration.zero);

      sink.success({'event': 'typeStarted', 'type': 'measurement', 'total': 1});
      sink.success({
        'event': 'record',
        'type': 'measurement',
        'index': 0,
        'total': 1,
        'record': {
          'unixSec': 1700000000,
          'hr': 70,
          'hrv': 40,
          'spo2': 98,
          'respRate': 16,
          'hrSuccess': true,
          'spo2Success': true,
        },
      });
      sink.success({'event': 'typeCompleted', 'type': 'measurement', 'count': 1});
      sink.success({
        'event': 'allCompleted',
        'counts': {'measurement': 1},
      });

      await Future<void>.delayed(Duration.zero);

      expect(events, hasLength(4));
      expect(events[0], isA<HistoryTypeStarted>());
      expect((events[0] as HistoryTypeStarted).type, 'measurement');
      expect(events[1], isA<HistoryRecordReceived>());
      final record = (events[1] as HistoryRecordReceived).record as MeasurementRecord;
      expect(record.hr, 70);
      expect(events[2], isA<HistoryTypeCompleted>());
      expect(events[3], isA<HistoryAllCompleted>());
      expect((events[3] as HistoryAllCompleted).counts['measurement'], 1);
      expect(done, isTrue);

      await sub.cancel();
    });

    test(
      'two sequential syncHistory runs both receive their full event sequence '
      '(regression: overlapping receiveBroadcastStream calls must not steal '
      'the native handler registration)',
      () async {
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(
          methodChannel,
          (call) async => null,
        );

        late MockStreamHandlerEventSink sink;
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(
          historyChannel,
          MockStreamHandler.inline(onListen: (arguments, events) => sink = events),
        );

        // First run: full sequence to allCompleted.
        final firstEvents = <HistorySyncEvent>[];
        var firstDone = false;
        final firstSub = lite.syncHistory('dev-1').listen(
          firstEvents.add,
          onDone: () => firstDone = true,
        );

        await Future<void>.delayed(Duration.zero);

        sink.success({'event': 'typeStarted', 'type': 'measurement', 'total': 1});
        sink.success({
          'event': 'record',
          'type': 'measurement',
          'index': 0,
          'total': 1,
          'record': {
            'unixSec': 1700000000,
            'hr': 70,
            'hrv': 40,
            'spo2': 98,
            'respRate': 16,
            'hrSuccess': true,
            'spo2Success': true,
          },
        });
        sink.success({'event': 'typeCompleted', 'type': 'measurement', 'count': 1});
        sink.success({
          'event': 'allCompleted',
          'counts': {'measurement': 1},
        });

        await Future<void>.delayed(Duration.zero);

        expect(firstEvents, hasLength(4));
        expect(firstEvents[0], isA<HistoryTypeStarted>());
        expect(firstEvents[3], isA<HistoryAllCompleted>());
        expect(firstDone, isTrue);

        await firstSub.cancel();

        // Second run: same channel/sink, full sequence again. If the second
        // syncHistory() re-registered a fresh receiveBroadcastStream listener
        // (the pre-fix footgun), the native handler registration would be
        // silently stolen and this second run's events would go nowhere.
        final secondEvents = <HistorySyncEvent>[];
        var secondDone = false;
        final secondSub = lite.syncHistory('dev-1').listen(
          secondEvents.add,
          onDone: () => secondDone = true,
        );

        await Future<void>.delayed(Duration.zero);

        sink.success({'event': 'typeStarted', 'type': 'measurement', 'total': 1});
        sink.success({
          'event': 'record',
          'type': 'measurement',
          'index': 0,
          'total': 1,
          'record': {
            'unixSec': 1700000100,
            'hr': 75,
            'hrv': 45,
            'spo2': 97,
            'respRate': 15,
            'hrSuccess': true,
            'spo2Success': true,
          },
        });
        sink.success({'event': 'typeCompleted', 'type': 'measurement', 'count': 1});
        sink.success({
          'event': 'allCompleted',
          'counts': {'measurement': 1},
        });

        await Future<void>.delayed(Duration.zero);

        expect(secondEvents, hasLength(4));
        expect(secondEvents[0], isA<HistoryTypeStarted>());
        final secondRecord = (secondEvents[1] as HistoryRecordReceived).record as MeasurementRecord;
        expect(secondRecord.hr, 75);
        expect(secondEvents[3], isA<HistoryAllCompleted>());
        expect(secondDone, isTrue);

        await secondSub.cancel();
      },
    );

    test('error event yields HistorySyncError then closes', () async {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(methodChannel, (call) async => null);

      late MockStreamHandlerEventSink sink;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(
        historyChannel,
        MockStreamHandler.inline(onListen: (arguments, events) => sink = events),
      );

      final events = <HistorySyncEvent>[];
      var done = false;
      final sub = lite.syncHistory('dev-1').listen(
        events.add,
        onDone: () => done = true,
      );

      await Future<void>.delayed(Duration.zero);

      sink.success({'event': 'error', 'code': 'SYNC_FAILED', 'message': 'boom'});

      await Future<void>.delayed(Duration.zero);

      expect(events, hasLength(1));
      expect(events.single, isA<HistorySyncError>());
      expect((events.single as HistorySyncError).code, 'SYNC_FAILED');
      expect(done, isTrue);

      await sub.cancel();
    });

    test('typeStarted without total (null) and record with null total do not crash', () async {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(methodChannel, (call) async => null);

      late MockStreamHandlerEventSink sink;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockStreamHandler(
        historyChannel,
        MockStreamHandler.inline(onListen: (arguments, events) => sink = events),
      );

      final events = <HistorySyncEvent>[];
      var done = false;
      final sub = lite.syncHistory('dev-1').listen(
        events.add,
        onDone: () => done = true,
      );

      await Future<void>.delayed(Duration.zero);

      // Send typeStarted WITHOUT total key (null in native contract for normal-mode sync)
      sink.success({'event': 'typeStarted', 'type': 'measurement'});
      sink.success({
        'event': 'record',
        'type': 'measurement',
        'index': 0,
        'total': null,
        'record': {
          'unixSec': 1700000000,
          'hr': 70,
          'hrv': 40,
          'spo2': 98,
          'respRate': 16,
          'hrSuccess': true,
          'spo2Success': true,
        },
      });
      sink.success({'event': 'typeCompleted', 'type': 'measurement', 'count': 1});
      sink.success({
        'event': 'allCompleted',
        'counts': {'measurement': 1},
      });

      await Future<void>.delayed(Duration.zero);

      expect(events, hasLength(4));
      expect(events[0], isA<HistoryTypeStarted>());
      expect((events[0] as HistoryTypeStarted).total, isNull);
      expect(events[1], isA<HistoryRecordReceived>());
      expect((events[1] as HistoryRecordReceived).total, isNull);
      expect(done, isTrue);

      await sub.cancel();
    });
  });

  group('errors', () {
    test('PlatformException(code: BUSY) is wrapped in AlloopBlueLiteException', () async {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(methodChannel, (call) async {
        throw PlatformException(code: 'BUSY', message: 'device busy');
      });

      await expectLater(
        lite.connect('dev-1'),
        throwsA(isA<AlloopBlueLiteException>().having((e) => e.code, 'code', 'BUSY')),
      );
    });
  });

  group('device info & status', () {
    test('getDeviceInfo maps result to LiteDeviceInfo', () async {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(methodChannel, (call) async {
        expect(call.method, 'getDeviceInfo');
        expect(call.arguments, {'deviceId': 'dev-1'});
        return {
          'firmwareVersion': '1.2.3',
          'batteryPercent': 80,
          'deviceState': 1,
          'hasMeasurementHistory': true,
          'hasActivityHistory': false,
          'hasSportHistory': true,
        };
      });

      final info = await lite.getDeviceInfo('dev-1');
      expect(info.firmwareVersion, '1.2.3');
      expect(info.batteryPercent, 80);
      expect(info.deviceState, 1);
      expect(info.hasMeasurementHistory, true);
      expect(info.hasActivityHistory, false);
      expect(info.hasSportHistory, true);
    });

    test('getDeviceInfo tolerates missing history flags', () async {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(methodChannel, (call) async {
        return {'firmwareVersion': '1.2.3', 'batteryPercent': 80, 'deviceState': 1};
      });

      final info = await lite.getDeviceInfo('dev-1');
      expect(info.hasMeasurementHistory, false);
      expect(info.hasActivityHistory, false);
      expect(info.hasSportHistory, false);
    });

    test('queryDeviceStatus maps result to LiteDeviceStatus', () async {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(methodChannel, (call) async {
        expect(call.method, 'queryDeviceStatus');
        expect(call.arguments, {'deviceId': 'dev-1'});
        return {
          'batteryPercent': 55,
          'deviceState': 2,
          'hasMeasurementHistory': false,
          'hasActivityHistory': true,
          'hasSportHistory': false,
        };
      });

      final status = await lite.queryDeviceStatus('dev-1');
      expect(status.batteryPercent, 55);
      expect(status.deviceState, 2);
      expect(status.hasMeasurementHistory, false);
      expect(status.hasActivityHistory, true);
      expect(status.hasSportHistory, false);
    });

    test('queryDeviceStatus tolerates missing history flags', () async {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(methodChannel, (call) async {
        return {'batteryPercent': 55, 'deviceState': 2};
      });

      final status = await lite.queryDeviceStatus('dev-1');
      expect(status.hasMeasurementHistory, false);
      expect(status.hasActivityHistory, false);
      expect(status.hasSportHistory, false);
    });
  });
}
