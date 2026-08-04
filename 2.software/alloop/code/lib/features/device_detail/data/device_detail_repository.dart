import 'package:alloop_blue_lite/alloop_blue_lite.dart';

/// Device detail data repository: wraps device connection and status queries.
class DeviceDetailRepository {
  final String deviceId;

  final AlloopBlueLite _blue = AlloopBlueLite.instance;

  DeviceDetailRepository({required this.deviceId});

  /// Connect to the device (progress/result via [connectionStateStream])
  Future<void> connect() => _blue.connect(deviceId);

  /// Disconnect
  Future<void> disconnect() => _blue.disconnect(deviceId);

  /// Device connection state stream
  Stream<LiteConnectionState> get connectionStateStream =>
      _blue.connectionStateStream(deviceId);

  /// Get device info (firmware version, battery, device state)
  Future<LiteDeviceInfo> getDeviceInfo() => _blue.getDeviceInfo(deviceId);
}
