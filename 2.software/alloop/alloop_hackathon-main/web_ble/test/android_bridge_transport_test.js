const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

class FakeWebSocket {
  static OPEN = 1;
  static CLOSING = 2;

  constructor() {
    this.readyState = FakeWebSocket.OPEN;
    this.sent = [];
  }

  send(value) {
    this.sent.push(JSON.parse(value));
  }

  close() {
    this.readyState = FakeWebSocket.CLOSING;
  }
}

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const start = html.indexOf('class RingTransport');
const end = html.indexOf('let bridgeTransport', start);
assert.notEqual(start, -1, 'RingTransport source is present');
assert.notEqual(end, -1, 'AndroidBridgeTransport source is present');

const context = vm.createContext({
  clearTimeout,
  console,
  Date,
  Error,
  JSON,
  Map,
  Promise,
  Set,
  setTimeout,
  WebSocket: FakeWebSocket,
});
vm.runInContext(
  `${html.slice(start, end)}\n` +
  'globalThis.AndroidBridgeTransportForTest = AndroidBridgeTransport;\n' +
  'globalThis.BridgeHistoryStoreForTest = BridgeHistoryStore;\n' +
  'globalThis.historyRowsForCsvForTest = historyRowsForCsv;',
  context,
);
const AndroidBridgeTransport = context.AndroidBridgeTransportForTest;
const BridgeHistoryStore = context.BridgeHistoryStoreForTest;
const historyRowsForCsv = context.historyRowsForCsvForTest;

function createTransport(timeoutMs = 100) {
  const transport = new AndroidBridgeTransport('ws://127.0.0.1:8766/ws', 'token', timeoutMs);
  transport.socket = new FakeWebSocket();
  return transport;
}

test('correlates a response with its pending request', async () => {
  const transport = createTransport();
  const pending = transport.request('ping');
  const [{ id }] = transport.socket.sent;

  transport._handleMessage(JSON.stringify({ id, ok: true, result: { bridgeVersion: '1.0.0' } }));

  assert.deepEqual(await pending, { bridgeVersion: '1.0.0' });
  assert.equal(transport.pending.size, 0);
});

test('rejects a request after its timeout', async () => {
  const transport = createTransport(10);

  await assert.rejects(transport.request('ping'), /timed out after 10ms/);
  assert.equal(transport.pending.size, 0);
});

test('rejects every pending request when the socket closes', async () => {
  const transport = createTransport();
  const first = transport.request('ping');
  const second = transport.request('getBridgeState');

  transport._handleClose({ code: 1006, reason: '' });

  await assert.rejects(first, /Bridge closed/);
  await assert.rejects(second, /Bridge closed/);
  assert.equal(transport.pending.size, 0);
});

test('dispatches server events to registered handlers', () => {
  const transport = createTransport();
  const received = [];
  const unsubscribe = transport.onEvent(message => received.push(message));

  transport._handleMessage(JSON.stringify({ event: 'bridgeError', data: { code: 'BUSY' } }));
  unsubscribe();
  transport._handleMessage(JSON.stringify({ event: 'bridgeError', data: { code: 'IGNORED' } }));

  assert.equal(received.length, 1);
  assert.equal(received[0].event, 'bridgeError');
  assert.equal(received[0].data.code, 'BUSY');
});

test('maps Stage 2 through Stage 5 RPC calls', async () => {
  const transport = createTransport();

  const pending = [
    transport.scan({ timeoutMs: 15000, nameFilter: 'AlloopRing' }),
    transport.stopScan(),
    transport.connect('android-sdk-id'),
    transport.disconnect('android-sdk-id'),
    transport.getDeviceInfo('android-sdk-id'),
    transport.startSpo2Verification('android-sdk-id'),
    transport.stopMeasurement('android-sdk-id'),
    transport.syncHistory('android-sdk-id'),
  ];

  assert.deepEqual(
    transport.socket.sent.map(({ method, params }) => ({ method, params })),
    [
      { method: 'startScan', params: { timeoutMs: 15000, nameFilter: 'AlloopRing' } },
      { method: 'stopScan', params: {} },
      { method: 'connect', params: { deviceId: 'android-sdk-id' } },
      { method: 'disconnect', params: { deviceId: 'android-sdk-id' } },
      { method: 'getDeviceInfo', params: { deviceId: 'android-sdk-id' } },
      { method: 'startSpo2Verification', params: { deviceId: 'android-sdk-id' } },
      { method: 'stopMeasurement', params: { deviceId: 'android-sdk-id' } },
      { method: 'syncHistory', params: { deviceId: 'android-sdk-id' } },
    ],
  );
  transport.close();
  await Promise.allSettled(pending);
});

test('bridge UI consumes Android scan and connection events', () => {
  assert.match(html, /bridgeTransport\.scan\(\{ timeoutMs: 15000 \}\)/);
  assert.doesNotMatch(html, /startAndroidScan[\s\S]*?nameFilter: 'AlloopRing'[\s\S]*?\n\}/);
  assert.match(html, /bridgeDevices\.set\(data\.deviceId, data\)/);
  assert.match(html, /handleBridgeConnectionState\(data\)/);
  assert.match(html, /bridgeTransport\.connect\(deviceId\)/);
  assert.match(html, /if \(!state\.ringConnected\) \{\s*await startAndroidScan\(\)/);
});

test('bridge UI loads device info and consumes status events', () => {
  assert.match(html, /loadAndroidDeviceInfo\(data\.deviceId\)/);
  assert.match(html, /event === 'deviceStatus'/);
  assert.match(html, /handleBridgeDeviceStatus\(data\)/);
  assert.match(html, /info\.firmwareVersion/);
  assert.match(html, /Android SDK 未提供/);
});

test('shared history contract fixture is consumable by the web store', () => {
  const fixture = JSON.parse(fs.readFileSync(
    path.join(__dirname, '..', '..', '..', 'contracts', 'history_sync_v1.json'),
    'utf8',
  ));
  const store = new BridgeHistoryStore();

  for (const message of fixture.events) {
    if (message.event === 'historyProgress') store.applyProgress(message.data);
    if (message.event === 'historyRecord') store.applyRecord(message.data);
  }

  assert.equal(store.syncId, 'history-example-1');
  assert.equal(store.records.measurement.length, 1);
  assert.equal(store.records.measurement[0].spo2, 98);
  assert.equal(store.completed, true);
});

test('history store deduplicates replayed records and resets for a new sync', () => {
  const store = new BridgeHistoryStore();
  const first = {
    deviceId: 'ring-1', syncId: 'sync-1', type: 'sport', index: 0, total: 1,
    record: { unixSec: 100, hr: 80, steps: 200, activityCount: 3 },
  };

  assert.equal(store.applyRecord(first).added, true);
  assert.equal(store.applyRecord(first).added, false);
  store.applyProgress({
    deviceId: 'ring-1', syncId: 'sync-1', phase: 'allCompleted',
    counts: { measurement: 0, sport: 1, activity: 0 },
  });
  assert.equal(store.records.sport.length, 1);
  assert.equal(store.active, false);

  const next = store.applyRecord({ ...first, syncId: 'sync-2', index: 0 });
  assert.equal(next.newSync, true);
  assert.equal(store.syncId, 'sync-2');
  assert.equal(store.records.sport.length, 1);
  assert.equal(store.completed, false);
});

test('history store sorts records by index and rejects completion gaps', () => {
  const store = new BridgeHistoryStore();
  const record = index => ({
    deviceId: 'ring-1', syncId: 'sync-1', type: 'sport', index, total: 3,
    record: { unixSec: 100 + index, hr: 80, steps: index, activityCount: 3 },
  });

  store.applyRecord(record(2));
  store.applyRecord(record(0));
  const result = store.applyProgress({
    deviceId: 'ring-1', syncId: 'sync-1', phase: 'allCompleted',
    counts: { measurement: 0, sport: 3, activity: 0 },
  });

  assert.deepEqual(Array.from(store.records.sport.map(item => item.unixSec)), [100, 102]);
  assert.equal(result.completed, false);
  assert.equal(store.completed, false);
  assert.equal(store.error.code, 'BRIDGE_HISTORY_INCOMPLETE');
});

test('history store rejects conflicting content for a replayed index', () => {
  const store = new BridgeHistoryStore();
  const first = {
    deviceId: 'ring-1', syncId: 'sync-1', type: 'measurement', index: 0, total: 1,
    record: { unixSec: 100, hr: 60 },
  };

  assert.equal(store.applyRecord(first).added, true);
  assert.equal(store.applyRecord({ ...first, record: { unixSec: 100, hr: 99 } }).added, false);
  assert.equal(store.error.code, 'BRIDGE_HISTORY_INCOMPLETE');
  assert.equal(store.records.measurement[0].hr, 60);
});

test('history errors retain partial records for export', () => {
  const store = new BridgeHistoryStore();
  store.applyRecord({
    deviceId: 'ring-1', syncId: 'sync-1', type: 'activity', index: 0, total: 2,
    record: { unixSec: 100, batteryPercent: 80, steps: 10, activeSeconds: 5, temperaturesC: [] },
  });
  store.applyError({
    deviceId: 'ring-1', syncId: 'sync-1', operation: 'syncHistory',
    code: 'HISTORY_TIMEOUT', message: 'History timed out',
  });

  assert.equal(store.active, false);
  assert.equal(store.error.code, 'HISTORY_TIMEOUT');
  assert.equal(store.records.activity.length, 1);
});

test('CSV conversion exports every retained record beyond the UI cap', () => {
  const records = Array.from({ length: 205 }, (_, index) => ({
    unixSec: index,
    hr: 60 + index,
    steps: index * 10,
    activityCount: index,
  }));
  const rows = historyRowsForCsv('sport', records, value => `time-${value}`);

  assert.equal(rows.length, 205);
  assert.deepEqual(Array.from(rows[204]), ['time-204', 264, 2040, 204]);
  assert.match(html, /const HISTORY_UI_CAP = 200/);
});

test('bridge UI handles history replay and keeps SDK cancellation disabled', () => {
  assert.match(html, /event === 'historyProgress'/);
  assert.match(html, /event === 'historyRecord'/);
  assert.match(html, /handleBridgeHistoryRecord\(data\)/);
  assert.match(html, /handleBridgeHistoryProgress\(data\)/);
  assert.match(html, /bridgeHistory\.beginRequest\(activeBridgeDeviceId\)/);
  assert.match(html, /SDK 不支持取消/);
});

test('shared realtime contract keeps PPG and ACC samples packet-batched', () => {
  const fixture = JSON.parse(fs.readFileSync(
    path.join(__dirname, '..', '..', '..', 'contracts', 'realtime_measurement_v1.json'),
    'utf8',
  ));

  assert.equal(fixture.events[1].event, 'ppgWave');
  assert.equal(fixture.events[1].data.samples.length, 2);
  assert.equal(fixture.events[2].event, 'accWave');
  assert.deepEqual(fixture.events[2].data.samples[0], { x: -1, y: 2, z: 3 });
});

test('bridge UI consumes realtime events with bounded waveform storage', () => {
  assert.match(html, /event === 'spo2Result'/);
  assert.match(html, /event === 'ppgWave'/);
  assert.match(html, /event === 'accWave'/);
  assert.match(html, /handleBridgeSpo2Result\(data\)/);
  assert.match(html, /handleBridgePpgWave\(data\)/);
  assert.match(html, /handleBridgeAccWave\(data\)/);
  assert.match(html, /const WAVE_WINDOW = 1500/);
  assert.match(html, /now - lastStreamStatsRender >= 250/);
  assert.doesNotMatch(html, /body\[data-mode=bridge\] #sec-spo2/);
});
