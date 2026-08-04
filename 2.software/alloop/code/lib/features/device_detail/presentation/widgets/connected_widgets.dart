import 'package:alloop_blue_lite/alloop_blue_lite.dart';
import 'package:flutter/material.dart';
import 'package:flutter_screenutil/flutter_screenutil.dart';

import '../../../../core/utils/converters/state_converter.dart';

/// Connected view showing the device overview and action entries.
class ConnectedOverviewCard extends StatelessWidget {
  final String deviceId;
  final LiteDeviceStatus? status;
  final LiteDeviceInfo? deviceInfo;

  const ConnectedOverviewCard({
    super.key,
    required this.deviceId,
    required this.status,
    required this.deviceInfo,
  });

  @override
  Widget build(BuildContext context) {
    final firmware = deviceInfo?.firmwareVersion ?? '';

    return Card(
      elevation: 2,
      child: Padding(
        padding: EdgeInsets.all(12.w),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Title and status badge
            Row(
              children: [
                Icon(
                  Icons.dashboard_customize,
                  color: Colors.blueGrey.shade600,
                ),
                SizedBox(width: 6.w),
                Text(
                  'Device Overview',
                  style: TextStyle(
                    fontSize: 16.sp,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                SizedBox(width: 8.w),
                Expanded(
                  child: Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    alignment: WrapAlignment.end,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      _buildStatusBadge(
                        icon: Icons.bluetooth_connected,
                        label: 'Connected',
                        color: Colors.green,
                      ),
                    ],
                  ),
                ),
              ],
            ),
            SizedBox(height: 10.h),

            // Device info section
            _buildInfoSection(
              children: [
                _buildInfoRow('Device ID', deviceId),
                _buildInfoRow('Firmware', firmware.isNotEmpty ? firmware : 'N/A'),
                _buildInfoRow(
                  'Device State',
                  status != null
                      ? StateConverter.deviceStateLabel(status!.deviceState)
                      : 'Unknown',
                ),
              ],
            ),
            SizedBox(height: 10.h),

            // Battery
            _buildBatteryRow(status),
          ],
        ),
      ),
    );
  }

  Widget _buildInfoSection({required List<Widget> children}) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.grey.shade50,
        borderRadius: BorderRadius.circular(8.r),
        border: Border.all(color: Colors.grey.shade200),
      ),
      child: Padding(
        padding: EdgeInsets.all(12.w),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: children,
        ),
      ),
    );
  }

  Widget _buildInfoRow(String label, String value) {
    return Padding(
      padding: EdgeInsets.symmetric(vertical: 2.h),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 80.w,
            child: Text(
              label,
              style: TextStyle(
                color: Colors.grey.shade600,
                fontSize: 12.sp,
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
          SizedBox(width: 12.w),
          Expanded(
            child: Text(
              value,
              style: TextStyle(
                fontSize: 12.sp,
                fontWeight: FontWeight.w600,
                color: Colors.black87,
              ),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }


  Widget _buildStatusBadge({
    required IconData icon,
    required String label,
    required Color color,
  }) {
    return Container(
      padding: EdgeInsets.symmetric(horizontal: 8.w, vertical: 4.h),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(12.r),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14.r, color: color),
          SizedBox(width: 4.w),
          Text(
            label,
            style: TextStyle(
              fontSize: 12.sp,
              fontWeight: FontWeight.w600,
              color: color,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildBatteryRow(LiteDeviceStatus? status) {
    final batteryValue = status != null ? '${status.batteryPercent}%' : '--';
    final batteryColor = status != null
        ? _batteryColor(status.batteryPercent)
        : Colors.grey;

    return Container(
      padding: EdgeInsets.symmetric(horizontal: 12.w, vertical: 10.h),
      decoration: BoxDecoration(
        color: batteryColor.withValues(alpha: 0.06),
        borderRadius: BorderRadius.circular(10.r),
        border: Border.all(color: batteryColor.withValues(alpha: 0.25)),
      ),
      child: Row(
        children: [
          Icon(Icons.battery_std, size: 15.r, color: batteryColor),
          SizedBox(width: 8.w),
          Text(
            'Battery',
            style: TextStyle(
              fontSize: 11.sp,
              color: batteryColor.withValues(alpha: 0.9),
            ),
          ),
          SizedBox(width: 8.w),
          Text(
            batteryValue,
            style: TextStyle(fontSize: 11.sp, fontWeight: FontWeight.w700),
          ),
        ],
      ),
    );
  }

  Color _batteryColor(int level) {
    if (level >= 50) return Colors.green;
    if (level >= 20) return Colors.orange;
    return Colors.red;
  }
}

/// Debug entries card
class DebugEntriesCard extends StatelessWidget {
  final VoidCallback onAlgorithmDebug;
  final VoidCallback onHistorySyncDebug;

  const DebugEntriesCard({
    super.key,
    required this.onAlgorithmDebug,
    required this.onHistorySyncDebug,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: EdgeInsets.all(16.w),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Features',
              style: TextStyle(fontSize: 16.sp, fontWeight: FontWeight.bold),
            ),
            SizedBox(height: 12.h),
            _DebugEntryTile(
              icon: Icons.analytics,
              title: 'SpO2 Verification',
              subtitle: 'SpO2 / PPG waveform',
              onTap: onAlgorithmDebug,
            ),
            SizedBox(height: 12.h),
            _DebugEntryTile(
              icon: Icons.history,
              title: 'History Data',
              subtitle: 'Measurement / Activity / Sport',
              onTap: onHistorySyncDebug,
            ),
          ],
        ),
      ),
    );
  }
}

class _DebugEntryTile extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  const _DebugEntryTile({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.blueGrey.shade50,
      borderRadius: BorderRadius.circular(12.r),
      child: InkWell(
        borderRadius: BorderRadius.circular(12.r),
        onTap: onTap,
        child: Padding(
          padding: EdgeInsets.all(14.w),
          child: Row(
            children: [
              Container(
                padding: EdgeInsets.all(6.w),
                decoration: BoxDecoration(
                  color: Colors.white,
                  shape: BoxShape.circle,
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withValues(alpha: 0.05),
                      blurRadius: 6,
                      offset: const Offset(0, 2),
                    ),
                  ],
                ),
                child: Icon(icon, color: Colors.blueGrey),
              ),
              SizedBox(width: 12.w),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      title,
                      style: TextStyle(
                        fontSize: 14.sp,
                        fontWeight: FontWeight.bold,
                      ),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    SizedBox(height: 4.h),
                    Text(
                      subtitle,
                      style: TextStyle(fontSize: 11.sp, color: Colors.grey[700]),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
              Icon(Icons.chevron_right, color: Colors.grey.shade400, size: 20.r),
            ],
          ),
        ),
      ),
    );
  }
}
