import 'package:flutter/material.dart';
import 'package:flutter_screenutil/flutter_screenutil.dart';

import '../../../../core/utils/converters/state_converter.dart';

/// Common battery indicator
///
/// A reusable widget for displaying the device battery level.
/// Can be used standalone in an AppBar or integrated into other widgets.
///
/// Example:
/// ```dart
/// // Use in an AppBar
/// actions: [
///   Obx(() => CommonBatteryIndicator(
///     batteryLevel: controller.batteryLevel.value,
///   )),
/// ]
///
/// // Integrate into other widgets
/// CommonBatteryIndicator(
///   batteryLevel: deviceStatus?.batteryLevel,
///   iconSize: 16,
///   textSize: 12,
///   isCharging: deviceStatus?.isCharging ?? false,
/// )
/// ```
class CommonBatteryIndicator extends StatelessWidget {
  /// Battery level (0-100), or null if unavailable
  final int? batteryLevel;

  /// Battery icon size
  final double iconSize;

  /// Percentage text font size
  final double textSize;

  /// Percentage text font weight
  final FontWeight textWeight;

  /// Padding around the indicator
  final EdgeInsetsGeometry? padding;

  /// Whether the device is charging
  final bool isCharging;

  const CommonBatteryIndicator({
    super.key,
    required this.batteryLevel,
    this.iconSize = 18,
    this.textSize = 13,
    this.textWeight = FontWeight.w600,
    this.padding,
    this.isCharging = false,
  });

  @override
  Widget build(BuildContext context) {
    // Render nothing if the battery level is unavailable
    if (batteryLevel == null) {
      return const SizedBox.shrink();
    }

    final level = batteryLevel!;

    return Padding(
      padding: padding ?? EdgeInsets.zero,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            StateConverter.getBatteryIcon(level, isCharging: isCharging),
            size: iconSize.r,
            color: isCharging ? Colors.green : StateConverter.getBatteryColor(level),
          ),
          SizedBox(width: 4.w),
          Text(
            '$level%',
            style: TextStyle(
              fontSize: textSize.sp,
              fontWeight: textWeight,
              color: isCharging ? Colors.green : null,
            ),
          ),
        ],
      ),
    );
  }
}

/// Extension methods for battery icon and color
///
/// These methods can be used by other widgets that need a custom layout
extension CommonBatteryIndicatorExtension on int {
  /// Get the battery icon for this level
  IconData getBatteryIcon() => StateConverter.getBatteryIcon(this);

  /// Get the battery color for this level
  Color getBatteryColor() => StateConverter.getBatteryColor(this);
}
