import 'package:alloop_blue_lite/alloop_blue_lite.dart';
import 'package:flutter/material.dart';
import 'package:flutter_screenutil/flutter_screenutil.dart';

/// Disconnected state -- device info card
///
/// Displays basic device info: name, ID, signal strength
class DisconnectDeviceInfoCard extends StatelessWidget {
  final LiteDevice device;

  const DisconnectDeviceInfoCard({super.key, required this.device});

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 2,
      child: Padding(
        padding: EdgeInsets.all(16.w),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  Icons.info_outline,
                  color: Colors.blueGrey,
                 size: 20.r,
                ),
                SizedBox(width: 8.w),
                Text(
                  'Device Info',
                  style: TextStyle(fontSize: 18.sp, fontWeight: FontWeight.bold),
                ),
                const Spacer(),
              ],
            ),
            SizedBox(height: 16.h),

            // Basic device info section
            _buildInfoSection(
              children: [
                _buildInfoRow(
                  'Device Name',
                  device.name.isEmpty ? 'Unnamed Device' : device.name,
                ),
                _buildInfoRow('Device ID', device.id),
                _buildInfoRow(
                  'Signal',
                  '${device.rssi} dBm',
                  Icons.signal_cellular_alt,
                  _getSignalStrengthColor(device.rssi),
                ),
              ],
            ),

            SizedBox(height: 16.h),
          ],
        ),
      ),
    );
  }

  /// Build the info section
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
          children: [...children],
        ),
      ),
    );
  }

  /// Build an info row
  Widget _buildInfoRow(
    String label,
    String value, [
    IconData? icon,
    Color? valueColor,
  ]) {
    return Padding(
      padding: EdgeInsets.symmetric(vertical: 2.h),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Label area
          SizedBox(
            width: 80.w,
            child: Text(
              label,
              style: TextStyle(
                color: Colors.grey.shade600,
                fontSize: 13.sp,
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
          SizedBox(width: 12.w),

          // Value area
          Expanded(
            child: Row(
              children: [
                if (icon != null) ...[
                  Icon(
                    icon,
                    size: 14.r,
                    color: valueColor ?? Colors.grey.shade700,
                  ),
                  SizedBox(width: 4.w),
                ],
                Expanded(
                  child: Text(
                    value,
                    style: TextStyle(
                      fontSize: 13.sp,
                      fontWeight: FontWeight.w600,
                      color: valueColor ?? Colors.black87,
                    ),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  /// Get color based on signal strength
  Color _getSignalStrengthColor(int rssi) {
    if (rssi >= -50) return Colors.green;
    if (rssi >= -70) return Colors.orange;
    return Colors.red;
  }
}

/// Connection status card
///
/// Displays the device connection status and provides the connect button
class ConnectionCard extends StatelessWidget {
  final bool isConnecting;
  final VoidCallback? onConnect;

  const ConnectionCard({super.key, required this.isConnecting, this.onConnect});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(12.r),
        child: Padding(
          padding: EdgeInsets.all(16.w),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Text(
                    'Connection Status',
                    style: TextStyle(fontSize: 18.sp, fontWeight: FontWeight.bold),
                  ),
                  const Spacer(),
                  Icon(Icons.bluetooth_disabled, color: Colors.grey),
                  SizedBox(width: 8.w),
                  Text(
                    'Disconnected',
                    style: TextStyle(
                      color: Colors.grey,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ],
              ),
              SizedBox(height: 16.h),

              // Disconnected state: show the connect button
              Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    'Tap the connect button to start the Bluetooth connection',
                    style: TextStyle(color: Colors.grey, fontSize: 13.sp),
                  ),
                  SizedBox(height: 12.h),
                  ElevatedButton.icon(
                    onPressed: isConnecting ? null : onConnect,
                    icon: isConnecting
                        ? SizedBox(
                            width: 16.w,
                            height: 16.h,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.flash_on),
                    label: Text(isConnecting ? 'Connecting...' : 'Connect'),
                    style: ElevatedButton.styleFrom(
                      padding: EdgeInsets.all(16.w),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Disconnected state -- hint card
class DisconnectHintCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;

  const DisconnectHintCard({
    super.key,
    required this.icon,
    required this.title,
    required this.subtitle,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: EdgeInsets.all(16.w),
        child: Row(
          children: [
            Icon(icon, color: Colors.blueGrey),
            SizedBox(width: 12.w),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: TextStyle(
                      fontSize: 14.sp,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  SizedBox(height: 4.h),
                  Text(
                    subtitle,
                    style: TextStyle(fontSize: 12.sp, color: Colors.grey[700]),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
