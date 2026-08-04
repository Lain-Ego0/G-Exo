/// Error severity levels for categorizing the impact of errors
///
/// Used to determine logging verbosity, user notifications, and error reporting priority
enum ErrorSeverity {
  /// Low severity - minor issues that don't affect functionality
  /// Examples: UI glitches, non-critical warnings
  low,

  /// Medium severity - issues that affect some functionality but have workarounds
  /// Examples: Feature degradation, retry-able network errors
  medium,

  /// High severity - significant issues affecting core functionality
  /// Examples: Authentication failures, data sync errors
  high,

  /// Critical severity - severe issues requiring immediate attention
  /// Examples: App crashes, data loss, security vulnerabilities
  critical,
}

extension ErrorSeverityExtension on ErrorSeverity {
  /// Get human-readable name
  String get displayName {
    switch (this) {
      case ErrorSeverity.low:
        return 'Low';
      case ErrorSeverity.medium:
        return 'Medium';
      case ErrorSeverity.high:
        return 'High';
      case ErrorSeverity.critical:
        return 'Critical';
    }
  }

  /// Get severity level for numerical comparison
  int get level {
    switch (this) {
      case ErrorSeverity.low:
        return 1;
      case ErrorSeverity.medium:
        return 2;
      case ErrorSeverity.high:
        return 3;
      case ErrorSeverity.critical:
        return 4;
    }
  }

  /// Check if this severity is higher or equal to another
  bool isAtLeast(ErrorSeverity other) {
    return level >= other.level;
  }
}
