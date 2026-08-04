/// Error categories for classifying the source and type of errors
///
/// Used for routing errors to appropriate handlers and generating targeted error messages
enum ErrorCategory {
  /// Network-related errors
  /// Examples: Connection timeout, HTTP errors, API failures
  network,

  /// Business logic errors
  /// Examples: Validation failures, business rule violations
  business,

  /// UI/rendering errors
  /// Examples: Widget build errors, layout overflow
  ui,

  /// System-level errors
  /// Examples: Platform errors, permission issues, storage failures
  system,

  /// Authentication/authorization errors
  /// Examples: Login failures, token expiration, permission denied
  auth,

  /// Health data related errors
  /// Examples: Health permission denied, sync failures
  health,

  /// Unknown or uncategorized errors
  unknown,
}

extension ErrorCategoryExtension on ErrorCategory {
  /// Get human-readable name
  String get displayName {
    switch (this) {
      case ErrorCategory.network:
        return 'Network';
      case ErrorCategory.business:
        return 'Business';
      case ErrorCategory.ui:
        return 'UI';
      case ErrorCategory.system:
        return 'System';
      case ErrorCategory.auth:
        return 'Authentication';
      case ErrorCategory.health:
        return 'Health';
      case ErrorCategory.unknown:
        return 'Unknown';
    }
  }

  /// Get tag for logging
  String get tag {
    switch (this) {
      case ErrorCategory.network:
        return 'NETWORK_ERROR';
      case ErrorCategory.business:
        return 'BUSINESS_ERROR';
      case ErrorCategory.ui:
        return 'UI_ERROR';
      case ErrorCategory.system:
        return 'SYSTEM_ERROR';
      case ErrorCategory.auth:
        return 'AUTH_ERROR';
      case ErrorCategory.health:
        return 'HEALTH_ERROR';
      case ErrorCategory.unknown:
        return 'UNKNOWN_ERROR';
    }
  }
}
