import 'package:flutter/material.dart';
import 'package:flutter_screenutil/flutter_screenutil.dart';

/// Sync operation card.
///
/// Triggers a one-time sync of all history data types (measurement/sport/activity).
class SyncOperationCard extends StatelessWidget {
  /// Whether syncing is in progress.
  final bool isSyncing;

  /// Whether syncing can be initiated (true when the device status is known and at least one history type is syncable).
  final bool canSync;

  /// Hint text shown when the device currently has no syncable history.
  final String? disabledHint;

  /// Callback to sync all history data.
  final VoidCallback onSyncAll;

  const SyncOperationCard({
    super.key,
    required this.isSyncing,
    required this.onSyncAll,
    this.canSync = true,
    this.disabledHint,
  });

  @override
  Widget build(BuildContext context) {
    final active = canSync && !isSyncing;

    return Card(
      child: Padding(
        padding: EdgeInsets.all(16.w),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Title bar
            Row(
              children: [
                Icon(Icons.sync, size: 20.sp),
                SizedBox(width: 8.w),
                Text(
                  'Sync Data',
                  style: TextStyle(
                    fontSize: 16.sp,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
            SizedBox(height: 12.h),

            Container(
              padding: EdgeInsets.all(12.w),
              decoration: BoxDecoration(
                color: active
                    ? Colors.green.withValues(alpha: 0.05)
                    : Colors.grey.withValues(alpha: 0.05),
                borderRadius: BorderRadius.circular(8.r),
                border: Border.all(
                  color: active
                      ? Colors.green.withValues(alpha: 0.3)
                      : Colors.grey.withValues(alpha: 0.3),
                ),
              ),
              child: Column(
                children: [
                  Row(
                    children: [
                      Icon(
                        Icons.auto_awesome,
                        color: active ? Colors.green : Colors.grey,
                        size: 20.sp,
                      ),
                      SizedBox(width: 8.w),
                      Text(
                        'Sync All History Data',
                        style: TextStyle(
                          fontSize: 14.sp,
                          fontWeight: FontWeight.bold,
                          color: active ? Colors.green : Colors.grey,
                        ),
                      ),
                    ],
                  ),
                  SizedBox(height: 8.h),
                  Text(
                    'Automatically syncs all history data types: measurement, sport, and activity',
                    style: TextStyle(fontSize: 12.sp, color: Colors.grey[600]),
                  ),
                  if (!canSync && !isSyncing && disabledHint != null) ...[
                    SizedBox(height: 8.h),
                    Text(
                      disabledHint!,
                      style: TextStyle(fontSize: 12.sp, color: Colors.orange[800]),
                    ),
                  ],
                  SizedBox(height: 12.h),
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton.icon(
                      onPressed: active ? onSyncAll : null,
                      icon: const Icon(Icons.sync),
                      label: Text(isSyncing ? 'Syncing...' : 'Start Sync'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: active ? Colors.green : Colors.grey,
                        foregroundColor: Colors.white,
                        padding: EdgeInsets.symmetric(vertical: 12.h),
                      ),
                    ),
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
