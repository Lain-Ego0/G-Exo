/// A single measurement history record (heart rate / HRV / SpO2 / resp rate).
class MeasurementRecord {
  const MeasurementRecord({
    required this.unixSec,
    required this.hr,
    required this.hrv,
    required this.spo2,
    required this.respRate,
    required this.hrSuccess,
    required this.spo2Success,
  });

  final int unixSec;
  final int hr;
  final int hrv;
  final int spo2;
  final int respRate;
  final bool hrSuccess;
  final bool spo2Success;

  factory MeasurementRecord.fromMap(Map<dynamic, dynamic> map) {
    return MeasurementRecord(
      unixSec: map['unixSec'] as int,
      hr: map['hr'] as int,
      hrv: map['hrv'] as int,
      spo2: map['spo2'] as int,
      respRate: map['respRate'] as int,
      hrSuccess: map['hrSuccess'] as bool,
      spo2Success: map['spo2Success'] as bool,
    );
  }
}

/// A single sport (activity tracking) history record.
class SportRecord {
  const SportRecord({
    required this.unixSec,
    required this.hr,
    required this.steps,
    required this.activityCount,
  });

  final int unixSec;
  final int hr;
  final int steps;
  final int activityCount;

  factory SportRecord.fromMap(Map<dynamic, dynamic> map) {
    return SportRecord(
      unixSec: map['unixSec'] as int,
      hr: map['hr'] as int,
      steps: map['steps'] as int,
      activityCount: map['activityCount'] as int,
    );
  }
}

/// A single daily-activity history record.
class ActivityRecord {
  const ActivityRecord({
    required this.unixSec,
    required this.batteryPercent,
    required this.steps,
    required this.activeSeconds,
    required this.temperaturesC,
  });

  final int unixSec;
  final int batteryPercent;
  final int steps;
  final int activeSeconds;
  final List<double> temperaturesC;

  factory ActivityRecord.fromMap(Map<dynamic, dynamic> map) {
    return ActivityRecord(
      unixSec: map['unixSec'] as int,
      batteryPercent: map['batteryPercent'] as int,
      steps: map['steps'] as int,
      activeSeconds: map['activeSeconds'] as int,
      temperaturesC: (map['temperaturesC'] as List<dynamic>).map((e) => (e as num).toDouble()).toList(),
    );
  }
}

/// Base type for events emitted while syncing history from a device.
sealed class HistorySyncEvent {
  const HistorySyncEvent();

  /// Parses one native history event map into its typed counterpart.
  factory HistorySyncEvent.fromMap(Map<dynamic, dynamic> map) {
    final event = map['event'] as String;
    switch (event) {
      case 'typeStarted':
        return HistoryTypeStarted(type: map['type'] as String, total: map['total'] as int?);
      case 'record':
        return HistoryRecordReceived(
          type: map['type'] as String,
          record: _parseRecord(map['type'] as String, map['record'] as Map<dynamic, dynamic>),
          index: map['index'] as int,
          total: map['total'] as int?,
        );
      case 'typeCompleted':
        return HistoryTypeCompleted(type: map['type'] as String, count: map['count'] as int);
      case 'allCompleted':
        return HistoryAllCompleted(
          counts: (map['counts'] as Map<dynamic, dynamic>).map((k, v) => MapEntry(k as String, v as int)),
        );
      case 'error':
        return HistorySyncError(code: map['code'] as String, message: map['message'] as String?);
      default:
        throw ArgumentError.value(event, 'event', 'Unknown history event');
    }
  }

  static Object _parseRecord(String type, Map<dynamic, dynamic> record) {
    switch (type) {
      case 'measurement':
        return MeasurementRecord.fromMap(record);
      case 'sport':
        return SportRecord.fromMap(record);
      case 'activity':
        return ActivityRecord.fromMap(record);
      default:
        throw ArgumentError.value(type, 'type', 'Unknown history record type');
    }
  }
}

/// Emitted when the device starts sending records of [type].
class HistoryTypeStarted extends HistorySyncEvent {
  const HistoryTypeStarted({required this.type, required this.total});

  final String type;
  final int? total;
}

/// Emitted for each individual history record received.
///
/// [record] is one of [MeasurementRecord], [SportRecord] or [ActivityRecord]
/// depending on [type].
class HistoryRecordReceived extends HistorySyncEvent {
  const HistoryRecordReceived({
    required this.type,
    required this.record,
    required this.index,
    required this.total,
  });

  final String type;
  final Object record;
  final int index;
  final int? total;
}

/// Emitted when all records of [type] have been received.
class HistoryTypeCompleted extends HistorySyncEvent {
  const HistoryTypeCompleted({required this.type, required this.count});

  final String type;
  final int count;
}

/// Emitted once, after every history type has finished syncing.
class HistoryAllCompleted extends HistorySyncEvent {
  const HistoryAllCompleted({required this.counts});

  /// Total record count per history type.
  final Map<String, int> counts;
}

/// Emitted when history sync fails.
class HistorySyncError extends HistorySyncEvent {
  const HistorySyncError({required this.code, required this.message});

  final String code;
  final String? message;
}
