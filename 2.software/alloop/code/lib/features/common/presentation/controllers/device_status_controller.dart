import 'dart:async';

import 'package:alloop_blue_lite/alloop_blue_lite.dart';
import 'package:get/get.dart';

import '../../../base/controller_base.dart';
import '../../data/repositories/common_repository.dart';

/// Global device status controller
///
/// Centrally manages device status and connection state, providing a single
/// source of truth for device status across all pages in the app. Avoids
/// redundant subscriptions to the device status stream from multiple pages,
/// reducing resource usage and ensuring data consistency.
///
/// Usage:
/// ```dart
/// // 1. Initialize after the device connects successfully
/// final controller = Get.find<DeviceStatusController>();
/// await controller.switchToDevice(deviceId);
///
/// // 2. Use device status on any page
/// Obx(() => Text('Battery: ${controller.currentStatus.value?.batteryPercent}%'))
///
/// // 3. Listen for status changes
/// ever(controller.currentStatus, (status) {
///   // Handle status changes
/// });
/// ```
class DeviceStatusController extends BaseController {
  final CommonRepository _repository;

  /// The ID of the device currently being monitored
  String? get currentDeviceId => _currentDeviceId;

  /// Whether device status is currently being monitored
  final RxBool isMonitoring = false.obs;

  /// Current device connection state
  final RxBool isConnected = false.obs;

  /// Current device status (battery, state code)
  final Rx<LiteDeviceStatus?> currentStatus = Rx<LiteDeviceStatus?>(null);

  String? _currentDeviceId;
  StreamSubscription<LiteDeviceStatus>? _statusSubscription;
  StreamSubscription<LiteConnectionState>? _connectionSubscription;

  DeviceStatusController({required CommonRepository repository})
    : _repository = repository;

  @override
  void onClose() {
    stopMonitoring();
    super.onClose();
  }

  /// Switch to the given device and start monitoring its status.
  ///
  /// If already monitoring this device, re-subscribe to ensure the stream
  /// state is correct. If monitoring another device, stop monitoring first,
  /// then switch to the new device.
  Future<void> switchToDevice(String deviceId) async {
    // Re-entering a page for the device we already monitor must not clear
    // the cached status: device status pushes can be minutes apart, so a
    // stop/re-subscribe cycle would blank the battery/state UI until the
    // next push arrives.
    if (_currentDeviceId == deviceId && isMonitoring.value) {
      logInfo('Already monitoring device $deviceId, keeping current status');
      return;
    }

    logInfo('Switching to device $deviceId (force re-subscribe)');

    await stopMonitoring();
    _currentDeviceId = deviceId;
    await _startMonitoring();
  }

  /// Stop monitoring the current device status.
  ///
  /// Cleans up all subscriptions and state. Even if [_startMonitoring] fails
  /// midway and leaves [isMonitoring] false, any subscriptions already created
  /// are still cancelled correctly to avoid leaks.
  Future<void> stopMonitoring() async {
    // Cancel subscriptions unconditionally first to avoid leaks when
    // _startMonitoring throws
    await _statusSubscription?.cancel();
    await _connectionSubscription?.cancel();
    _statusSubscription = null;
    _connectionSubscription = null;

    if (!isMonitoring.value) {
      return;
    }

    logInfo('Stopping device status monitoring for device $_currentDeviceId');
    isMonitoring.value = false;

    currentStatus.value = null;
    isConnected.value = false;
    _currentDeviceId = null;
  }

  /// Get the device connection state stream.
  ///
  /// Other controllers can listen to this stream to react to connection state
  /// changes. For example, AlgorithmVerifyController can listen to it and stop
  /// measurement when the device disconnects.
  Stream<LiteConnectionState> get connectionStateStream {
    if (_currentDeviceId == null) {
      return const Stream.empty();
    }
    return _repository.getConnectionStateStream(_currentDeviceId!);
  }

  /// Start monitoring device status
  Future<void> _startMonitoring() async {
    if (_currentDeviceId == null) {
      logWarning('Cannot start monitoring: device ID is null');
      return;
    }

    logInfo('Starting device status monitoring for device $_currentDeviceId');
    isMonitoring.value = true;

    // Note: assumes the device is already connected (confirmed by the caller),
    // so initialize to true. The actual connection state is updated
    // asynchronously via the stream.
    isConnected.value = true;

    // Subscribe to the connection state stream
    _connectionSubscription = _repository
        .getConnectionStateStream(_currentDeviceId!)
        .listen(
          (state) {
            final connected = state.state == LiteConnectionStateValue.connected;
            isConnected.value = connected;
            logInfo('Connection state changed: ${state.state}');
          },
          onError: (error) {
            logError('Connection state stream error', error);
            isConnected.value = false;
          },
        );

    // Subscribe to the device status stream
    _statusSubscription = _repository
        .getDeviceStatusStream(_currentDeviceId!)
        .listen(
          (status) {
            currentStatus.value = status;
            logDebug(
              'Device status updated: battery=${status.batteryPercent}%, '
              'state=${status.deviceState}, history[m/a/s]='
              '${status.hasMeasurementHistory}/${status.hasActivityHistory}/'
              '${status.hasSportHistory}',
            );
          },
          onError: (error) {
            logError('Device status stream error', error);
          },
        );
  }

  /// Locally clear history-availability flags after a successful sync.
  ///
  /// This updates the UI status chips immediately instead of waiting for a
  /// firmware status push. The device's own status push remains authoritative
  /// and will overwrite this local value if/when it arrives via the status
  /// stream — see [_startMonitoring].
  ///
  /// Only the flags explicitly requested to be cleared (`true`) are changed;
  /// omitted/`false` params leave the corresponding flag untouched.
  void clearHistoryFlags({
    bool measurement = false,
    bool activity = false,
    bool sport = false,
  }) {
    final current = currentStatus.value;
    if (current == null) return;
    if (!measurement && !activity && !sport) return;

    final updated = LiteDeviceStatus(
      batteryPercent: current.batteryPercent,
      deviceState: current.deviceState,
      hasMeasurementHistory:
          measurement ? false : current.hasMeasurementHistory,
      hasActivityHistory: activity ? false : current.hasActivityHistory,
      hasSportHistory: sport ? false : current.hasSportHistory,
    );
    currentStatus.value = updated;
    logInfo(
      'Cleared local history flags (measurement=$measurement, '
      'activity=$activity, sport=$sport)',
    );
  }
}
