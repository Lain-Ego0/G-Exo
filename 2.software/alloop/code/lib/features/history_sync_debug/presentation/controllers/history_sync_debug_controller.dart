import 'dart:async';
import 'dart:io';

import 'package:alloop/core/utils/al_file_utils.dart';
import 'package:alloop/core/utils/csv_file_writer.dart';
import 'package:alloop/features/common/presentation/controllers/device_status_controller.dart';
import 'package:alloop/features/history_sync_debug/domain/models/history_sync_state.dart';
import 'package:alloop/foundations/log/al_logger.dart';
import 'package:alloop/foundations/ui/al_toast.dart';
import 'package:alloop_blue_lite/alloop_blue_lite.dart';
import 'package:get/get.dart';
import 'package:intl/intl.dart';
import 'package:path/path.dart' as p;
import 'package:share_plus/share_plus.dart';

/// Sync status for each history data type.
class TypeSyncStatus {
  int receivedCount = 0;
  int? total;
  bool isCompleted = false;

  final String type;

  TypeSyncStatus(this.type);

  String get displayName {
    switch (type) {
      case 'measurement':
        return 'Measurement History';
      case 'sport':
        return 'Sport History';
      case 'activity':
        return 'Activity History';
      default:
        return type;
    }
  }
}

/// History data sync debug controller.
///
/// Manages the entire history data sync flow:
/// 1. Display device status (from [DeviceStatusController]'s pushed status; does
///    not query proactively)
/// 2. Sync history data (measurement/activity/sport)
/// 3. Display sync progress and results
/// 4. After sync completes (or partially completes), write the received records
///    to CSV, refresh the local syncable-type flags, and provide an entry point
///    to share the exported files
class HistorySyncDebugController extends GetxController {
  final String deviceId;

  final AlloopBlueLite _blue = AlloopBlueLite.instance;

  static const String _logTag = 'history_sync';

  DeviceStatusController get _deviceStatusController =>
      Get.find<DeviceStatusController>();

  HistorySyncDebugController({required this.deviceId});

  // ==================== State management ====================

  /// Whether loading is in progress.
  final isLoading = false.obs;

  /// Device status (from DeviceStatusController's pushed status, updated by the device's own reports; not queried proactively).
  Rx<LiteDeviceStatus?> get deviceStatus =>
      _deviceStatusController.currentStatus;

  /// Whether each history data type has syncable content (based on the device status flags); returns an empty list when the status is unknown.
  List<String> get availableTypes {
    final status = deviceStatus.value;
    if (status == null) return const [];
    return [
      if (status.hasMeasurementHistory) 'measurement',
      if (status.hasActivityHistory) 'activity',
      if (status.hasSportHistory) 'sport',
    ];
  }

  /// Whether the device status is known (at least one status push has been received).
  bool get isStatusKnown => deviceStatus.value != null;

  /// Whether no history data type has syncable content (only meaningful when the status is known).
  bool get hasNoSyncableHistory =>
      isStatusKnown && availableTypes.isEmpty;

  /// Sync state.
  final syncState = Rx<HistorySyncState>(HistorySyncState.idle);

  /// Error message.
  final errorMessage = ''.obs;

  // ==================== Sync data ====================

  /// Sync status per type (measurement/sport/activity).
  final typeSyncStatuses = <String, TypeSyncStatus>{}.obs;

  /// Records received per type (type -> record list).
  ///
  /// Records accumulate as-is during syncing (MeasurementRecord/SportRecord/
  /// ActivityRecord), and are written out to CSV files once the sync ends
  /// (whether completed or errored).
  final recordsByType = <String, List<Object>>{}.obs;

  // ==================== Export results ====================

  /// List of CSV file paths written out by this sync.
  final exportedFiles = <String>[].obs;

  /// Whether file export/sharing is in progress.
  final isExporting = false.obs;

  // ==================== Sync progress ====================

  /// Total number of records received.
  final receivedRecords = 0.obs;

  /// The data type currently being synced.
  final currentSyncType = ''.obs;

  // ==================== Stream subscriptions ====================

  StreamSubscription<HistorySyncEvent>? _syncSubscription;

  // ==================== Lifecycle ====================

  @override
  void onClose() {
    _syncSubscription?.cancel();
    super.onClose();
  }

  // ==================== Sync operations ====================

  /// Syncs all history data.
  Future<void> syncAllHistoryData() async {
    if (syncState.value.isSyncing) {
      AlToast.showInfo('Sync already in progress');
      return;
    }

    // Reset state: clear the old data first (clearAllData resets syncState to
    // idle), then set syncState to syncing so it isn't overwritten by
    // clearAllData.
    clearAllData();
    syncState.value = HistorySyncState.syncing;
    errorMessage.value = '';
    receivedRecords.value = 0;
    currentSyncType.value = '';

    try {
      await _syncSubscription?.cancel();

      _syncSubscription = _blue.syncHistory(deviceId).listen(
        _handleSyncEvent,
        onError: (Object error) async {
          syncState.value = HistorySyncState.error;
          errorMessage.value = 'Sync failed: ${_describeError(error)}';
          AlToast.showError('Sync failed: ${_describeError(error)}');
          // On error, still perform one write-to-disk + local flag refresh with
          // the data received so far, to preserve partially-synced data
          // (best-effort strategy).
          await _finalizeSync();
        },
        onDone: () async {
          if (syncState.value != HistorySyncState.error) {
            syncState.value = HistorySyncState.completed;
          }
          currentSyncType.value = '';
          await _finalizeSync();
        },
      );
    } catch (e) {
      syncState.value = HistorySyncState.error;
      errorMessage.value = 'Sync failed: $e';
      AlToast.showError('Sync failed: $e');
      await _finalizeSync();
    }
  }

  /// Handles a sync event.
  void _handleSyncEvent(HistorySyncEvent event) {
    switch (event) {
      case HistoryTypeStarted():
        final status = typeSyncStatuses.putIfAbsent(
          event.type,
          () => TypeSyncStatus(event.type),
        );
        status.total = event.total;
        currentSyncType.value = status.displayName;
        typeSyncStatuses.refresh();

        if (event.total != null) {
          AlToast.showInfo('Started syncing ${status.displayName}, ${event.total} records');
        } else {
          AlToast.showInfo('Started syncing ${status.displayName}');
        }

      case HistoryRecordReceived():
        final status = typeSyncStatuses.putIfAbsent(
          event.type,
          () => TypeSyncStatus(event.type),
        );
        status.receivedCount++;
        receivedRecords.value++;

        final records = recordsByType.putIfAbsent(event.type, () => []);
        records.add(event.record);
        recordsByType.refresh();
        typeSyncStatuses.refresh();

      case HistoryTypeCompleted():
        final status = typeSyncStatuses.putIfAbsent(
          event.type,
          () => TypeSyncStatus(event.type),
        );
        status.isCompleted = true;
        typeSyncStatuses.refresh();

        AlToast.showSuccess('${status.displayName} sync complete, ${event.count} records');

      case HistoryAllCompleted():
        syncState.value = HistorySyncState.completed;
        currentSyncType.value = '';
        final summary = event.counts.entries
            .map((e) => '${e.key}: ${e.value} records')
            .join(', ');
        AlToast.showSuccess('Sync complete! $summary');

      case HistorySyncError():
        syncState.value = HistorySyncState.error;
        errorMessage.value = '${event.code}: ${event.message ?? ""}';
        AlToast.showError('Sync failed: ${event.code} ${event.message ?? ""}');
    }
  }

  // ==================== Sync finalization: CSV write + local flag refresh ====================

  /// Finalization after the sync stream ends (whether success or mid-way error):
  /// 1. Write the received records to CSV per type (only for types with at least
  ///    1 record);
  /// 2. For types written successfully, locally clear the corresponding
  ///    syncable flag in DeviceStatusController so the status card badges
  ///    refresh immediately;
  /// 3. Record the written file paths for sharing.
  ///
  /// Idempotent: if there are no records this round, no files are written and no
  /// flags are changed.
  Future<void> _finalizeSync() async {
    if (recordsByType.values.every((records) => records.isEmpty)) {
      return;
    }

    final written = await _writeCsvFiles();
    if (written.isEmpty) return;

    exportedFiles.assignAll(written.map((f) => f.path));

    _deviceStatusController.clearHistoryFlags(
      measurement: (recordsByType['measurement']?.isNotEmpty ?? false),
      activity: (recordsByType['activity']?.isNotEmpty ?? false),
      sport: (recordsByType['sport']?.isNotEmpty ?? false),
    );
  }

  /// Writes the records accumulated in [recordsByType] out to CSV files.
  ///
  /// Path convention: `<user-accessible directory>/history_sync/history_<yyyy-MM-dd_HH-mm-ss>_<Type>.csv`
  /// (consistent with the CsvFileWriter usage in the algorithm_verify module).
  /// Only writes files for types with at least 1 record.
  Future<List<File>> _writeCsvFiles() async {
    final baseDir = await AlFileUtils.getUserAccessibleDirectory();
    if (baseDir == null) {
      AlLogger.error('Failed to get export directory', tag: _logTag);
      AlToast.showError('Failed to get file path; history data not exported');
      return const [];
    }

    final exportDir = p.join(baseDir.path, 'history_sync');
    final timeStamp = DateFormat('yyyy-MM-dd_HH-mm-ss').format(DateTime.now());

    final files = <File>[];

    final measurements = recordsByType['measurement'];
    if (measurements != null && measurements.isNotEmpty) {
      final file = await _writeMeasurementCsv(
        exportDir: exportDir,
        timeStamp: timeStamp,
        records: measurements.cast<MeasurementRecord>(),
      );
      if (file != null) files.add(file);
    }

    final sports = recordsByType['sport'];
    if (sports != null && sports.isNotEmpty) {
      final file = await _writeSportCsv(
        exportDir: exportDir,
        timeStamp: timeStamp,
        records: sports.cast<SportRecord>(),
      );
      if (file != null) files.add(file);
    }

    final activities = recordsByType['activity'];
    if (activities != null && activities.isNotEmpty) {
      final file = await _writeActivityCsv(
        exportDir: exportDir,
        timeStamp: timeStamp,
        records: activities.cast<ActivityRecord>(),
      );
      if (file != null) files.add(file);
    }

    AlLogger.info(
      'History sync CSV export done: ${files.length} file(s) in $exportDir',
      tag: _logTag,
    );
    return files;
  }

  Future<File?> _writeMeasurementCsv({
    required String exportDir,
    required String timeStamp,
    required List<MeasurementRecord> records,
  }) async {
    final filePath = p.join(
      exportDir,
      'history_${timeStamp}_Measurement.csv',
    );
    try {
      final writer = CsvFileWriter(
        filePath: filePath,
        headers: ['time', 'hr', 'hrv', 'spo2', 'respRate', 'hrSuccess', 'spo2Success'],
      );
      await writer.initialize();
      for (final r in records) {
        writer.writeRow([
          _isoFromUnixSec(r.unixSec),
          r.hr,
          r.hrv,
          r.spo2,
          r.respRate,
          r.hrSuccess,
          r.spo2Success,
        ]);
      }
      await writer.close();
      return File(filePath);
    } catch (e) {
      AlLogger.error('Failed to write measurement CSV', tag: _logTag, error: e);
      return null;
    }
  }

  Future<File?> _writeSportCsv({
    required String exportDir,
    required String timeStamp,
    required List<SportRecord> records,
  }) async {
    final filePath = p.join(exportDir, 'history_${timeStamp}_Sport.csv');
    try {
      final writer = CsvFileWriter(
        filePath: filePath,
        headers: ['time', 'hr', 'steps', 'activityCount'],
      );
      await writer.initialize();
      for (final r in records) {
        writer.writeRow([
          _isoFromUnixSec(r.unixSec),
          r.hr,
          r.steps,
          r.activityCount,
        ]);
      }
      await writer.close();
      return File(filePath);
    } catch (e) {
      AlLogger.error('Failed to write sport CSV', tag: _logTag, error: e);
      return null;
    }
  }

  Future<File?> _writeActivityCsv({
    required String exportDir,
    required String timeStamp,
    required List<ActivityRecord> records,
  }) async {
    final filePath = p.join(exportDir, 'history_${timeStamp}_Activity.csv');
    try {
      final writer = CsvFileWriter(
        filePath: filePath,
        headers: ['time', 'batteryPercent', 'steps', 'activeSeconds', 'temperaturesC'],
      );
      await writer.initialize();
      for (final r in records) {
        writer.writeRow([
          _isoFromUnixSec(r.unixSec),
          r.batteryPercent,
          r.steps,
          r.activeSeconds,
          r.temperaturesC.join(';'),
        ]);
      }
      await writer.close();
      return File(filePath);
    } catch (e) {
      AlLogger.error('Failed to write activity CSV', tag: _logTag, error: e);
      return null;
    }
  }

  /// Converts unixSec (Unix seconds, UTC) to an ISO8601 string.
  String _isoFromUnixSec(int unixSec) =>
      DateTime.fromMillisecondsSinceEpoch(unixSec * 1000, isUtc: true)
          .toIso8601String();

  // ==================== Sharing ====================

  /// Shares the CSV files exported by this sync.
  Future<void> shareExportedFiles() async {
    if (exportedFiles.isEmpty) {
      AlToast.showError('No files to share');
      return;
    }

    isExporting.value = true;
    try {
      final xFiles = exportedFiles.map((path) => XFile(path)).toList();
      await SharePlus.instance.share(
        ShareParams(
          files: xFiles,
          subject: 'History Sync Export - $deviceId',
        ),
      );
      AlLogger.info('Shared ${xFiles.length} history sync file(s)', tag: _logTag);
    } catch (e) {
      AlLogger.error('Share failed', tag: _logTag, error: e);
      AlToast.showError('Share failed: $e');
    } finally {
      isExporting.value = false;
    }
  }

  // ==================== Helper methods ====================

  /// Clears all data.
  void clearAllData() {
    typeSyncStatuses.clear();
    recordsByType.clear();
    exportedFiles.clear();
    receivedRecords.value = 0;
    syncState.value = HistorySyncState.idle;
    errorMessage.value = '';
    currentSyncType.value = '';
  }

  String _describeError(Object error) {
    if (error is AlloopBlueLiteException) {
      return '${error.code}: ${error.message ?? ""}';
    }
    return error.toString();
  }
}
