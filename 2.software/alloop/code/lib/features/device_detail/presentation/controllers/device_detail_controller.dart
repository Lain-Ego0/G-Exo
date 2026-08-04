import 'dart:async';

import 'package:alloop/features/common/presentation/controllers/device_status_controller.dart';
import 'package:alloop_blue_lite/alloop_blue_lite.dart';
import 'package:get/get.dart';

import '../../../../foundations/navigation/al_routes.dart';
import '../../../../foundations/ui/al_toast.dart';
import '../../../base/controller_base.dart';
import '../../data/device_detail_repository.dart';

/// Device detail controller: manages connection state, status stream
/// subscriptions, and navigation to the debug entries.
///
/// Connection readiness has a single criterion: [connectionStateStream]
/// reports connected. There is no separate setup step.
class DeviceDetailController extends BaseController {
  final DeviceDetailRepository _repository;

  final RxBool isConnecting = false.obs;

  // isConnected reflects the real connection state from DeviceStatusController
  RxBool get isConnected => _deviceStatusController.isConnected;

  final Rxn<LiteDeviceInfo> deviceInfo = Rxn<LiteDeviceInfo>();

  // Device name (reactive)
  final RxString deviceName = ''.obs;

  DeviceStatusController get _deviceStatusController =>
      Get.find<DeviceStatusController>();

  StreamSubscription<LiteConnectionState>? _connectionSub;

  /// Connection timeout fallback: the wait window between [connect] being
  /// initiated and the first subsequent connection event being received.
  static const Duration _connectTimeout = Duration(seconds: 25);
  Timer? _connectTimeoutTimer;
  bool _awaitingConnectResult = false;

  /// Display name from the scan result that opened this page; connection
  /// events only carry the device id, so the name must be threaded through.
  final String initialName;

  DeviceDetailController({
    required DeviceDetailRepository repository,
    this.initialName = '',
  }) : _repository = repository;

  String get deviceId => _repository.deviceId;

  @override
  void onInit() {
    super.onInit();
    if (initialName.isNotEmpty) {
      deviceName.value = initialName;
    }
    _bindConnectionState();
  }

  @override
  void onClose() {
    _cancelConnectTimeoutTimer();
    _connectionSub?.cancel();
    super.onClose();
  }

  /// Connect to the device, guarding against repeated taps.
  ///
  /// Enters the "connecting" phase: [isConnecting] is set to true and a 25s
  /// fallback timeout is started. The phase ends when the first subsequent
  /// connection event (connected or disconnected) arrives; see
  /// [_bindConnectionState]. If the timeout fires before any event, it is
  /// treated as a connection timeout.
  Future<void> connect() async {
    if (isConnecting.value) return;
    isConnecting.value = true;
    _awaitingConnectResult = true;
    _startConnectTimeoutTimer();
    try {
      await _repository.connect();
      // The actual connection result arrives asynchronously via
      // connectionStateStream; this only initiates the connection.
      AlToast.showInfo('Connecting to device...');
    } catch (e) {
      _awaitingConnectResult = false;
      _cancelConnectTimeoutTimer();
      isConnecting.value = false;
      AlToast.showError('Connection failed: ${_describeError(e)}');
      logError('Failed to connect', e);
    }
  }

  void _startConnectTimeoutTimer() {
    _cancelConnectTimeoutTimer();
    _connectTimeoutTimer = Timer(_connectTimeout, () {
      _connectTimeoutTimer = null;
      if (!_awaitingConnectResult) return;
      _awaitingConnectResult = false;
      isConnecting.value = false;
      AlToast.showError('Connection timed out, please try again');
      logWarning('Connect timed out waiting for a connection event: $deviceId');
    });
  }

  void _cancelConnectTimeoutTimer() {
    _connectTimeoutTimer?.cancel();
    _connectTimeoutTimer = null;
  }

  /// Actively disconnect from the device and clean up state.
  Future<void> disconnect() async {
    try {
      await _repository.disconnect();
    } catch (e) {
      AlToast.showError('Failed to disconnect: ${_describeError(e)}');
      logError('Failed to disconnect', e);
    } finally {
      await _deviceStatusController.stopMonitoring();
      _handleDisconnected();
    }
  }

  /// Navigate to the SpO2 verification entry.
  void goToAlgorithmDebug() {
    if (!_ensureConnected()) return;
    logInfo('Navigating to Algorithm Verify page for device: $deviceId');
    Get.toNamed(AlRoutes.algorithmVerify, arguments: {'deviceId': deviceId});
  }

  /// Navigate to the history data sync debug entry.
  void goToHistorySyncDebug() {
    if (!_ensureConnected()) return;
    logInfo('Navigating to History Sync Debug page for device: $deviceId');
    Get.toNamed(AlRoutes.historySyncDebug, arguments: {'deviceId': deviceId});
  }

  void _bindConnectionState() {
    _connectionSub?.cancel();
    _connectionSub = _repository.connectionStateStream.listen((state) {
      // The first connection event received while awaiting a connect()
      // result resolves the "connecting" phase (cancels the fallback timer).
      // This applies whether the event is 'connected' or 'disconnected';
      // 'connecting' itself does not resolve the phase.
      final wasAwaitingConnect = _awaitingConnectResult;
      if (wasAwaitingConnect && state.state != LiteConnectionStateValue.connecting) {
        _awaitingConnectResult = false;
        _cancelConnectTimeoutTimer();
      }

      switch (state.state) {
        case LiteConnectionStateValue.connected:
          _handleConnected();
        case LiteConnectionStateValue.connecting:
          break;
        case LiteConnectionStateValue.disconnected:
          if (wasAwaitingConnect) {
            // Connect attempt failed before ever reaching 'connected':
            // surface a distinct "connect failed" toast (with errorCode when
            // available) instead of the generic "device disconnected" toast.
            isConnecting.value = false;
            deviceInfo.value = null;
            final suffix = state.errorCode != null ? ': ${state.errorCode}' : '';
            AlToast.showError('Connection failed$suffix');
            logError('Connect failed while connecting: $deviceId, errorCode=${state.errorCode}');
          } else {
            _handleDisconnected(showToast: true, errorCode: state.errorCode);
          }
      }
    });
  }

  Future<void> _handleConnected() async {
    logInfo('Device connected: $deviceId');
    isConnecting.value = false;
    await _deviceStatusController.switchToDevice(deviceId);
    await _fetchDeviceInfo(silent: true);
    deviceName.value = deviceName.value.isEmpty ? deviceId : deviceName.value;
  }

  void _handleDisconnected({bool showToast = false, String? errorCode}) {
    logInfo('Device disconnected: $deviceId, errorCode=$errorCode');
    isConnecting.value = false;
    _awaitingConnectResult = false;
    _cancelConnectTimeoutTimer();
    deviceInfo.value = null;
    if (showToast) {
      final suffix = errorCode != null ? ': $errorCode' : '';
      AlToast.showInfo('Device disconnected$suffix');
    }
  }

  bool _ensureConnected() {
    if (!isConnected.value) {
      AlToast.showError('Please connect a device first');
      return false;
    }
    return true;
  }

  Future<void> _fetchDeviceInfo({bool silent = false}) async {
    if (!isConnected.value) {
      return;
    }
    try {
      final info = await _repository.getDeviceInfo();
      deviceInfo.value = info;
    } catch (e) {
      if (!silent) {
        AlToast.showError('Failed to fetch device info: ${_describeError(e)}');
      }
      logError('Failed to fetch device info', e);
    }
  }

  String _describeError(Object error) {
    if (error is AlloopBlueLiteException) {
      return '${error.code}: ${error.message ?? ""}';
    }
    return error.toString();
  }
}
