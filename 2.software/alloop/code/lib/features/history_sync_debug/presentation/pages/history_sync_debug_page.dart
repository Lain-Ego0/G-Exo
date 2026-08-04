import 'package:alloop/features/history_sync_debug/domain/models/history_sync_state.dart';
import 'package:alloop/features/history_sync_debug/presentation/controllers/history_sync_debug_controller.dart';
import 'package:alloop/features/history_sync_debug/presentation/widgets/device_status_card.dart';
import 'package:alloop/features/history_sync_debug/presentation/widgets/sync_operation_card.dart';
import 'package:alloop/features/history_sync_debug/presentation/widgets/sync_progress_card.dart';
import 'package:alloop_blue_lite/alloop_blue_lite.dart';
import 'package:flutter/material.dart';
import 'package:flutter_screenutil/flutter_screenutil.dart';
import 'package:get/get.dart';

/// History data sync debug page.
///
/// Used to test and debug the history data sync feature:
/// 1. Display device status
/// 2. Sync history data (measurement/activity/sport)
/// 3. Display sync progress and results
class HistorySyncDebugPage extends StatelessWidget {
  final String deviceId;

  const HistorySyncDebugPage({
    super.key,
    required this.deviceId,
  });

  @override
  Widget build(BuildContext context) {
    // Create the controller
    final controller = Get.put(
      HistorySyncDebugController(deviceId: deviceId),
      tag: deviceId,
    );

    return Scaffold(
      appBar: AppBar(
        title: const Text('History Data'),
      ),
      body: Obx(() {
        final isLoading = controller.isLoading.value;

        return Stack(
          children: [
            // Main content
            SingleChildScrollView(
              padding: EdgeInsets.all(16.w),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  // Device status card
                  DeviceStatusCard(
                    deviceStatus: controller.deviceStatus.value,
                  ),
                  SizedBox(height: 16.h),

                  // Sync operation card
                  SyncOperationCard(
                    isSyncing: controller.syncState.value.isSyncing,
                    canSync: !controller.hasNoSyncableHistory,
                    disabledHint: controller.hasNoSyncableHistory
                        ? 'This device has no history data to sync'
                        : null,
                    onSyncAll: controller.syncAllHistoryData,
                  ),
                  SizedBox(height: 16.h),

                  // Sync progress card
                  SyncProgressCard(
                    syncState: controller.syncState.value,
                    currentSyncType: controller.currentSyncType.value,
                    receivedRecords: controller.receivedRecords.value,
                    errorMessage: controller.errorMessage.value,
                    exportedFiles: controller.exportedFiles,
                    isExporting: controller.isExporting.value,
                    onClearData: controller.clearAllData,
                    onShare: controller.shareExportedFiles,
                  ),
                  SizedBox(height: 16.h),

                  // Data list card
                  _buildDataListCard(controller),
                ],
              ),
            ),

            // Loading indicator
            if (isLoading)
              Container(
                color: Colors.black.withValues(alpha: 0.3),
                child: const Center(
                  child: CircularProgressIndicator(),
                ),
              ),
          ],
        );
      }),
    );
  }

  /// Builds the data list card.
  Widget _buildDataListCard(HistorySyncDebugController controller) {
    final recordsByType = controller.recordsByType;

    if (recordsByType.isEmpty) {
      return const SizedBox.shrink();
    }

    return Card(
      child: Padding(
        padding: EdgeInsets.all(16.w),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Title bar
            Row(
              children: [
                Icon(Icons.list, size: 20.sp),
                SizedBox(width: 8.w),
                Text(
                  'Synced Data',
                  style: TextStyle(
                    fontSize: 16.sp,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
            SizedBox(height: 12.h),

            ...recordsByType.entries.map((entry) {
              final status = controller.typeSyncStatuses[entry.key];
              return Padding(
                padding: EdgeInsets.only(bottom: 8.h),
                child: _buildDataSection(
                  title: status?.displayName ?? entry.key,
                  count: entry.value.length,
                  icon: _iconForType(entry.key),
                  color: _colorForType(entry.key),
                  onTap: () => _showRecordsDialog(
                    title: status?.displayName ?? entry.key,
                    records: entry.value,
                  ),
                ),
              );
            }),
          ],
        ),
      ),
    );
  }

  IconData _iconForType(String type) {
    switch (type) {
      case 'measurement':
        return Icons.favorite;
      case 'sport':
        return Icons.directions_run;
      case 'activity':
        return Icons.directions_walk;
      default:
        return Icons.data_object;
    }
  }

  Color _colorForType(String type) {
    switch (type) {
      case 'measurement':
        return Colors.red;
      case 'sport':
        return Colors.blue;
      case 'activity':
        return Colors.green;
      default:
        return Colors.grey;
    }
  }

  /// Builds a data section.
  Widget _buildDataSection({
    required String title,
    required int count,
    required IconData icon,
    required Color color,
    required VoidCallback onTap,
  }) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8.r),
      child: Container(
        padding: EdgeInsets.all(12.w),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.05),
          borderRadius: BorderRadius.circular(8.r),
          border: Border.all(color: color.withValues(alpha: 0.3)),
        ),
        child: Row(
          children: [
            Icon(icon, size: 20.sp, color: color),
            SizedBox(width: 12.w),
            Expanded(
              child: Text(
                title,
                style: TextStyle(
                  fontSize: 14.sp,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ),
            Text(
              '$count records',
              style: TextStyle(
                fontSize: 14.sp,
                fontWeight: FontWeight.bold,
                color: color,
              ),
            ),
            SizedBox(width: 8.w),
            Icon(Icons.arrow_forward_ios, size: 16.sp, color: color),
          ],
        ),
      ),
    );
  }

  /// Shows the record detail dialog (generic, works for MeasurementRecord/SportRecord/ActivityRecord).
  void _showRecordsDialog({
    required String title,
    required List<Object> records,
  }) {
    Get.dialog(
      Dialog(
        child: Container(
          constraints: BoxConstraints(maxHeight: 600.h),
          child: Column(
            children: [
              Container(
                padding: EdgeInsets.all(16.w),
                decoration: BoxDecoration(
                  color: Colors.blue.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.only(
                    topLeft: Radius.circular(8.r),
                    topRight: Radius.circular(8.r),
                  ),
                ),
                child: Row(
                  children: [
                    Text(
                      '$title (${records.length} records)',
                      style: TextStyle(
                        fontSize: 16.sp,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const Spacer(),
                    IconButton(
                      icon: const Icon(Icons.close),
                      onPressed: () => Get.back(),
                    ),
                  ],
                ),
              ),
              Expanded(
                child: ListView.separated(
                  padding: EdgeInsets.all(16.w),
                  itemCount: records.length,
                  separatorBuilder: (context, index) => Divider(height: 16.h),
                  itemBuilder: (context, index) {
                    return Text(
                      '#${index + 1}  ${_describeRecord(records[index])}',
                      style: TextStyle(fontSize: 12.sp),
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _describeRecord(Object record) {
    if (record is MeasurementRecord) {
      return 'hr=${record.hr}, spo2=${record.spo2}, hrv=${record.hrv}, '
          'respRate=${record.respRate}, hrSuccess=${record.hrSuccess}, '
          'spo2Success=${record.spo2Success}, unixSec=${record.unixSec}';
    }
    if (record is SportRecord) {
      return 'hr=${record.hr}, steps=${record.steps}, '
          'activityCount=${record.activityCount}, unixSec=${record.unixSec}';
    }
    if (record is ActivityRecord) {
      return 'battery=${record.batteryPercent}%, steps=${record.steps}, '
          'activeSeconds=${record.activeSeconds}, unixSec=${record.unixSec}';
    }
    return record.toString();
  }
}
