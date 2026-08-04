import 'package:flutter/material.dart';

/// Centralized state-to-UI converter
///
/// Provides static helpers to turn raw status values (battery level, device
/// state code) into user-facing UI elements (labels, icons, colors).
class StateConverter {
  StateConverter._();

  // ==================== Device State ====================

  /// Human-readable label for a device state code.
  ///
  /// Falls back to `State <code>` for any value not covered here.
  static String deviceStateLabel(int code) {
    switch (code) {
      case 0:
        return 'Unbound';
      case 1:
        return 'Idle';
      case 2:
        return 'Wearing';
      case 3:
        return 'Measuring';
      case 4:
        return 'In Charging Case';
      case 6:
        return 'Sports';
      case 7:
        return 'Sleep';
      default:
        return 'State $code';
    }
  }

  // ==================== Battery Converters ====================

  /// Battery level (%) at or above which the indicator shows green (healthy).
  static const int _batteryGreenThreshold = 50;

  /// Battery level (%) at or above which the indicator shows orange (low);
  /// below this is red (critical).
  static const int _batteryOrangeThreshold = 20;

  /// Convert battery level to color
  ///
  /// Rules:
  /// - >= 50%: Green (healthy)
  /// - >= 20%: Orange (low)
  /// - < 20%: Red (critical)
  static Color getBatteryColor(int level) {
    if (level >= _batteryGreenThreshold) {
      return Colors.green;
    }
    if (level >= _batteryOrangeThreshold) {
      return Colors.orange;
    }
    return Colors.red;
  }

  /// Convert battery level to icon
  ///
  /// Returns appropriate battery icon based on level and charging state.
  /// When charging, returns battery_charging_full regardless of level
  /// (Flutter Icons only has one charging variant with lightning bolt).
  static IconData getBatteryIcon(int level, {bool isCharging = false}) {
    if (isCharging) {
      return Icons.battery_charging_full;
    }
    if (level >= 90) return Icons.battery_full;
    if (level >= 70) return Icons.battery_6_bar;
    if (level >= 50) return Icons.battery_5_bar;
    if (level >= 30) return Icons.battery_3_bar;
    if (level >= 10) return Icons.battery_2_bar;
    return Icons.battery_1_bar;
  }
}
