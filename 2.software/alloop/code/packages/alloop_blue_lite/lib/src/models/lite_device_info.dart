/// Static/slow-changing information about a connected device.
class LiteDeviceInfo {
  const LiteDeviceInfo({
    required this.firmwareVersion,
    required this.batteryPercent,
    required this.deviceState,
    this.hasMeasurementHistory = false,
    this.hasActivityHistory = false,
    this.hasSportHistory = false,
  });

  final String firmwareVersion;
  final int batteryPercent;
  final int deviceState;

  /// Whether the device currently has measurement (HR/SpO2) history pending sync.
  final bool hasMeasurementHistory;

  /// Whether the device currently has activity history pending sync.
  final bool hasActivityHistory;

  /// Whether the device currently has sport-mode history pending sync.
  final bool hasSportHistory;

  factory LiteDeviceInfo.fromMap(Map<dynamic, dynamic> map) {
    return LiteDeviceInfo(
      firmwareVersion: map['firmwareVersion'] as String,
      batteryPercent: map['batteryPercent'] as int,
      deviceState: map['deviceState'] as int,
      hasMeasurementHistory: map['hasMeasurementHistory'] as bool? ?? false,
      hasActivityHistory: map['hasActivityHistory'] as bool? ?? false,
      hasSportHistory: map['hasSportHistory'] as bool? ?? false,
    );
  }

  @override
  String toString() =>
      'LiteDeviceInfo(firmwareVersion: $firmwareVersion, batteryPercent: $batteryPercent, '
      'deviceState: $deviceState, hasMeasurementHistory: $hasMeasurementHistory, '
      'hasActivityHistory: $hasActivityHistory, hasSportHistory: $hasSportHistory)';
}
