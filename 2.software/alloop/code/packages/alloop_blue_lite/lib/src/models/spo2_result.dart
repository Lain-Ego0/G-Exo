/// A blood-oxygen (SpO2) reading.
///
/// Unifies two upstream shapes: a live measurement result and a verification
/// sample. Use [isVerified] to tell which one produced this instance.
class Spo2Result {
  const Spo2Result({
    this.spo2,
    this.hr,
    this.success,
    this.measuredAt,
    required bool isVerified,
  }) : _isVerified = isVerified;

  /// Blood oxygen saturation percentage, if available.
  final int? spo2;

  /// Heart rate in bpm, if available (only present for live results).
  final int? hr;

  /// Whether the reading was considered valid by the device.
  final bool? success;

  /// Wall-clock time of the reading. Only present for verification samples.
  final DateTime? measuredAt;

  final bool _isVerified;

  /// True when this reading came from the verification stream (has a
  /// timestamp), false when it came from a live measurement result.
  bool get isVerified => _isVerified;

  factory Spo2Result.fromMap(Map<dynamic, dynamic> map) {
    final kind = map['kind'] as String;
    switch (kind) {
      case 'result':
        return Spo2Result(
          spo2: map['spo2'] as int?,
          hr: map['hr'] as int?,
          success: (map['spo2Success'] as bool?) ?? (map['hrSuccess'] as bool?),
          isVerified: false,
        );
      case 'verify':
        return Spo2Result(
          spo2: map['spo2'] as int?,
          hr: null,
          success: map['success'] as bool?,
          measuredAt: DateTime.fromMillisecondsSinceEpoch((map['unixSec'] as int) * 1000, isUtc: true),
          isVerified: true,
        );
      default:
        throw ArgumentError.value(kind, 'kind', 'Unknown spo2 event kind');
    }
  }

  @override
  String toString() =>
      'Spo2Result(spo2: $spo2, hr: $hr, success: $success, measuredAt: $measuredAt, isVerified: $isVerified)';
}
