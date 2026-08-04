/// Frequently-changing status of a connected device.
class LiteDeviceStatus {
  const LiteDeviceStatus({
    required this.batteryPercent,
    required this.deviceState,
    this.hasMeasurementHistory = false,
    this.hasActivityHistory = false,
    this.hasSportHistory = false,
  });

  final int batteryPercent;
  final int deviceState;

  /// Whether the device currently has measurement (HR/SpO2) history pending sync.
  final bool hasMeasurementHistory;

  /// Whether the device currently has activity history pending sync.
  final bool hasActivityHistory;

  /// Whether the device currently has sport-mode history pending sync.
  final bool hasSportHistory;

  factory LiteDeviceStatus.fromMap(Map<dynamic, dynamic> map) {
    return LiteDeviceStatus(
      batteryPercent: map['batteryPercent'] as int,
      deviceState: map['deviceState'] as int,
      hasMeasurementHistory: map['hasMeasurementHistory'] as bool? ?? false,
      hasActivityHistory: map['hasActivityHistory'] as bool? ?? false,
      hasSportHistory: map['hasSportHistory'] as bool? ?? false,
    );
  }

  @override
  String toString() =>
      'LiteDeviceStatus(batteryPercent: $batteryPercent, deviceState: $deviceState, '
      'hasMeasurementHistory: $hasMeasurementHistory, hasActivityHistory: $hasActivityHistory, '
      'hasSportHistory: $hasSportHistory)';
}
