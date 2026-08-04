import 'package:alloop_blue_lite/alloop_blue_lite.dart';
import 'package:flutter/material.dart';
import 'package:flutter_screenutil/flutter_screenutil.dart';

import '../../../../core/utils/converters/state_converter.dart';

/// Device status card.
///
/// Displays the device's battery, status, and related information.
class DeviceStatusCard extends StatelessWidget {
  /// Device status.
  final LiteDeviceStatus? deviceStatus;

  const DeviceStatusCard({
    super.key,
    required this.deviceStatus,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: EdgeInsets.all(16.w),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Title bar
            Row(
              children: [
                Icon(Icons.info_outline, size: 20.sp),
                SizedBox(width: 8.w),
                Text(
                  'Device Status',
                  style: TextStyle(
                    fontSize: 16.sp,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
            SizedBox(height: 12.h),

            // Device status info
            if (deviceStatus != null) ...[
              // Battery
              _buildInfoRow(
                icon: Icons.battery_std,
                label: 'Battery',
                value: '${deviceStatus!.batteryPercent}%',
                valueColor: _getBatteryColor(deviceStatus!.batteryPercent),
              ),
              SizedBox(height: 8.h),
              // Device state code
              _buildInfoRow(
                icon: Icons.settings,
                label: 'Device State',
                value: StateConverter.deviceStateLabel(
                  deviceStatus!.deviceState,
                ),
              ),
              SizedBox(height: 12.h),
              // Syncable history data types
              Text(
                'Available History Data',
                style: TextStyle(
                  fontSize: 12.sp,
                  fontWeight: FontWeight.w500,
                  color: Colors.grey[700],
                ),
              ),
              SizedBox(height: 8.h),
              Wrap(
                spacing: 8.w,
                runSpacing: 8.h,
                children: [
                  _buildAvailabilityChip('Measurement', deviceStatus!.hasMeasurementHistory),
                  _buildAvailabilityChip('Activity', deviceStatus!.hasActivityHistory),
                  _buildAvailabilityChip('Sport', deviceStatus!.hasSportHistory),
                ],
              ),
            ] else
              Text(
                'No device status data',
                style: TextStyle(fontSize: 12.sp, color: Colors.grey[600]),
              ),
          ],
        ),
      ),
    );
  }

  /// Builds a history-data availability chip.
  Widget _buildAvailabilityChip(String label, bool hasData) {
    final color = hasData ? Colors.green : Colors.grey;
    return Container(
      padding: EdgeInsets.symmetric(horizontal: 10.w, vertical: 6.h),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(16.r),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            hasData ? Icons.check_circle : Icons.remove_circle_outline,
            size: 14.sp,
            color: color,
          ),
          SizedBox(width: 4.w),
          Text(
            '$label: ${hasData ? "Available" : "None"}',
            style: TextStyle(
              fontSize: 11.sp,
              fontWeight: FontWeight.w500,
              color: color,
            ),
          ),
        ],
      ),
    );
  }

  /// Builds an info row.
  Widget _buildInfoRow({
    required IconData icon,
    required String label,
    required String value,
    Color? valueColor,
  }) {
    return Row(
      children: [
        Icon(icon, size: 16.sp, color: Colors.grey[600]),
        SizedBox(width: 8.w),
        Text(
          label,
          style: TextStyle(fontSize: 14.sp, color: Colors.grey[600]),
        ),
        SizedBox(width: 8.w),
        Expanded(
          child: Text(
            value,
            style: TextStyle(
              fontSize: 14.sp,
              fontWeight: FontWeight.w500,
              color: valueColor,
            ),
            textAlign: TextAlign.right,
          ),
        ),
      ],
    );
  }

  /// Returns the battery color.
  Color _getBatteryColor(int batteryLevel) {
    if (batteryLevel > 50) {
      return Colors.green;
    } else if (batteryLevel > 20) {
      return Colors.orange;
    } else {
      return Colors.red;
    }
  }
}
