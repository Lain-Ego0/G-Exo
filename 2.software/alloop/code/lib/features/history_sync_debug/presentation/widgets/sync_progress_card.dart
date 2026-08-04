import 'package:alloop/features/history_sync_debug/domain/models/history_sync_state.dart';
import 'package:flutter/material.dart';
import 'package:flutter_screenutil/flutter_screenutil.dart';
import 'package:path/path.dart' as p;

/// Sync progress card.
///
/// Displays the sync progress, state, received record count, the list of
/// exported CSV files, and the share entry point.
class SyncProgressCard extends StatelessWidget {
  /// Sync state.
  final HistorySyncState syncState;

  /// The data type currently being synced.
  final String currentSyncType;

  /// Number of records received.
  final int receivedRecords;

  /// Error message.
  final String errorMessage;

  /// CSV file paths exported by this sync.
  final List<String> exportedFiles;

  /// Whether exporting/sharing is in progress.
  final bool isExporting;

  /// Callback to clear the data.
  final VoidCallback onClearData;

  /// Callback to share the exported files.
  final VoidCallback? onShare;

  const SyncProgressCard({
    super.key,
    required this.syncState,
    required this.currentSyncType,
    required this.receivedRecords,
    required this.errorMessage,
    required this.onClearData,
    this.exportedFiles = const [],
    this.isExporting = false,
    this.onShare,
  });

  @override
  Widget build(BuildContext context) {
    // Hide the card when idle and there is no data
    if (syncState.isIdle && receivedRecords == 0) {
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
                Icon(Icons.analytics_outlined, size: 20.sp),
                SizedBox(width: 8.w),
                Text(
                  'Sync Progress',
                  style: TextStyle(
                    fontSize: 16.sp,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const Spacer(),
                // Clear button
                if (!syncState.isSyncing)
                  TextButton.icon(
                    onPressed: onClearData,
                    icon: Icon(Icons.clear_all, size: 16.sp),
                    label: const Text('Clear'),
                    style: TextButton.styleFrom(
                      foregroundColor: Colors.grey[600],
                    ),
                  ),
              ],
            ),
            SizedBox(height: 12.h),

            // Sync state
            _buildStatusRow(
              icon: _getStatusIcon(),
              label: 'Status',
              value: syncState.description,
              valueColor: _getStatusColor(),
            ),

            // If syncing, show the current sync type
            if (syncState.isSyncing && currentSyncType.isNotEmpty) ...[
              SizedBox(height: 8.h),
              _buildStatusRow(
                icon: Icons.sync,
                label: 'Syncing',
                value: currentSyncType,
                valueColor: Colors.blue,
              ),
            ],

            SizedBox(height: 8.h),

            // Number of records received
            _buildStatusRow(
              icon: Icons.list_alt,
              label: 'Received',
              value: '$receivedRecords records',
              valueColor: Colors.black87,
            ),

            // If there is an error message, show the error
            if (syncState.isError && errorMessage.isNotEmpty) ...[
              SizedBox(height: 12.h),
              Container(
                padding: EdgeInsets.all(12.w),
                decoration: BoxDecoration(
                  color: Colors.red.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(8.r),
                  border: Border.all(color: Colors.red.withValues(alpha: 0.3)),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(
                      Icons.error_outline,
                      color: Colors.red,
                      size: 16.sp,
                    ),
                    SizedBox(width: 8.w),
                    Expanded(
                      child: Text(
                        errorMessage,
                        style: TextStyle(
                          fontSize: 12.sp,
                          color: Colors.red[800],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],

            // If syncing, show the progress indicator
            if (syncState.isSyncing) ...[
              SizedBox(height: 12.h),
              LinearProgressIndicator(
                backgroundColor: Colors.grey[200],
                valueColor: const AlwaysStoppedAnimation<Color>(Colors.blue),
              ),
            ],

            // Exported files list + share button
            if (!syncState.isSyncing && exportedFiles.isNotEmpty) ...[
              SizedBox(height: 12.h),
              _buildExportedFilesSection(),
            ],
          ],
        ),
      ),
    );
  }

  /// Builds the exported files list + share button.
  Widget _buildExportedFilesSection() {
    return Container(
      padding: EdgeInsets.all(12.w),
      decoration: BoxDecoration(
        color: Colors.blue.withValues(alpha: 0.05),
        borderRadius: BorderRadius.circular(8.r),
        border: Border.all(color: Colors.blue.withValues(alpha: 0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.description_outlined, size: 16.sp, color: Colors.blue),
              SizedBox(width: 8.w),
              Text(
                'Exported ${exportedFiles.length} CSV file(s)',
                style: TextStyle(
                  fontSize: 13.sp,
                  fontWeight: FontWeight.w500,
                  color: Colors.blue[800],
                ),
              ),
            ],
          ),
          SizedBox(height: 8.h),
          ...exportedFiles.map(
            (path) => Padding(
              padding: EdgeInsets.only(bottom: 4.h),
              child: Text(
                p.basename(path),
                style: TextStyle(fontSize: 12.sp, color: Colors.grey[700]),
              ),
            ),
          ),
          SizedBox(height: 8.h),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: isExporting ? null : onShare,
              icon: isExporting
                  ? SizedBox(
                      width: 16.w,
                      height: 16.w,
                      child: const CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.share),
              label: Text(isExporting ? 'Sharing...' : 'Share'),
            ),
          ),
        ],
      ),
    );
  }

  /// Builds a status row.
  Widget _buildStatusRow({
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
          style: TextStyle(
            fontSize: 14.sp,
            color: Colors.grey[600],
          ),
        ),
        SizedBox(width: 8.w),
        Expanded(
          child: Text(
            value,
            style: TextStyle(
              fontSize: 14.sp,
              fontWeight: FontWeight.w500,
              color: valueColor ?? Colors.black87,
            ),
            textAlign: TextAlign.right,
          ),
        ),
      ],
    );
  }

  /// Returns the status icon.
  IconData _getStatusIcon() {
    switch (syncState) {
      case HistorySyncState.idle:
        return Icons.pause_circle_outline;
      case HistorySyncState.syncing:
        return Icons.sync;
      case HistorySyncState.completed:
        return Icons.check_circle;
      case HistorySyncState.error:
        return Icons.error;
    }
  }

  /// Returns the status color.
  Color _getStatusColor() {
    switch (syncState) {
      case HistorySyncState.idle:
        return Colors.grey;
      case HistorySyncState.syncing:
        return Colors.blue;
      case HistorySyncState.completed:
        return Colors.green;
      case HistorySyncState.error:
        return Colors.red;
    }
  }
}
