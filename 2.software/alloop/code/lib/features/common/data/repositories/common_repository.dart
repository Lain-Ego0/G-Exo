import 'package:alloop_blue_lite/alloop_blue_lite.dart';

/// Common data repository
///
/// A unified SDK wrapper for accessing device status and connection streams.
/// Provides a consistent interface for the device detail, algorithm verify,
/// and history sync modules.
class CommonRepository {
  final AlloopBlueLite _blue = AlloopBlueLite.instance;

  /// Device status stream
  Stream<LiteDeviceStatus> getDeviceStatusStream(String deviceId) {
    return _blue.deviceStatusStream(deviceId);
  }

  /// Get the connection state stream for the current device
  Stream<LiteConnectionState> getConnectionStateStream(String deviceId) {
    return _blue.connectionStateStream(deviceId);
  }
}
