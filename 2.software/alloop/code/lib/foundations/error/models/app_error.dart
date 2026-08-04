import 'error_severity.dart';
import 'error_category.dart';

/// Base error class for application-wide error handling
///
/// Provides structured error information with severity, category, and context
class AppError {
  /// Human-readable error message
  final String message;

  /// Error severity level
  final ErrorSeverity severity;

  /// Error category/type
  final ErrorCategory category;

  /// Original error object (if any)
  final dynamic originalError;

  /// Stack trace (if available)
  final StackTrace? stackTrace;

  /// Timestamp when error occurred
  final DateTime timestamp;

  /// Additional context information (optional)
  final Map<String, dynamic>? context;

  /// User-facing message (optional, for production)
  final String? userMessage;

  AppError({
    required this.message,
    required this.severity,
    required this.category,
    this.originalError,
    this.stackTrace,
    DateTime? timestamp,
    this.context,
    this.userMessage,
  }) : timestamp = timestamp ?? DateTime.now();

  /// Create a network error
  factory AppError.network({
    required String message,
    ErrorSeverity severity = ErrorSeverity.medium,
    dynamic originalError,
    StackTrace? stackTrace,
    Map<String, dynamic>? context,
    String? userMessage,
  }) {
    return AppError(
      message: message,
      severity: severity,
      category: ErrorCategory.network,
      originalError: originalError,
      stackTrace: stackTrace,
      context: context,
      userMessage: userMessage ?? 'Network connection error, please try again',
    );
  }

  /// Create a business logic error
  factory AppError.business({
    required String message,
    ErrorSeverity severity = ErrorSeverity.medium,
    dynamic originalError,
    StackTrace? stackTrace,
    Map<String, dynamic>? context,
    String? userMessage,
  }) {
    return AppError(
      message: message,
      severity: severity,
      category: ErrorCategory.business,
      originalError: originalError,
      stackTrace: stackTrace,
      context: context,
      userMessage: userMessage ?? 'Operation failed, please try again',
    );
  }

  /// Create a UI error
  factory AppError.ui({
    required String message,
    ErrorSeverity severity = ErrorSeverity.low,
    dynamic originalError,
    StackTrace? stackTrace,
    Map<String, dynamic>? context,
    String? userMessage,
  }) {
    return AppError(
      message: message,
      severity: severity,
      category: ErrorCategory.ui,
      originalError: originalError,
      stackTrace: stackTrace,
      context: context,
      userMessage: userMessage ?? 'Display error occurred',
    );
  }

  /// Create a system error
  factory AppError.system({
    required String message,
    ErrorSeverity severity = ErrorSeverity.high,
    dynamic originalError,
    StackTrace? stackTrace,
    Map<String, dynamic>? context,
    String? userMessage,
  }) {
    return AppError(
      message: message,
      severity: severity,
      category: ErrorCategory.system,
      originalError: originalError,
      stackTrace: stackTrace,
      context: context,
      userMessage: userMessage ?? 'System error occurred',
    );
  }

  /// Create an authentication error
  factory AppError.auth({
    required String message,
    ErrorSeverity severity = ErrorSeverity.high,
    dynamic originalError,
    StackTrace? stackTrace,
    Map<String, dynamic>? context,
    String? userMessage,
  }) {
    return AppError(
      message: message,
      severity: severity,
      category: ErrorCategory.auth,
      originalError: originalError,
      stackTrace: stackTrace,
      context: context,
      userMessage: userMessage ?? 'Authentication failed, please login again',
    );
  }

  /// Create a health data error
  factory AppError.health({
    required String message,
    ErrorSeverity severity = ErrorSeverity.medium,
    dynamic originalError,
    StackTrace? stackTrace,
    Map<String, dynamic>? context,
    String? userMessage,
  }) {
    return AppError(
      message: message,
      severity: severity,
      category: ErrorCategory.health,
      originalError: originalError,
      stackTrace: stackTrace,
      context: context,
      userMessage:
          userMessage ?? 'Health data error, please check permissions',
    );
  }

  /// Create an unknown error
  factory AppError.unknown({
    required String message,
    ErrorSeverity severity = ErrorSeverity.medium,
    dynamic originalError,
    StackTrace? stackTrace,
    Map<String, dynamic>? context,
    String? userMessage,
  }) {
    return AppError(
      message: message,
      severity: severity,
      category: ErrorCategory.unknown,
      originalError: originalError,
      stackTrace: stackTrace,
      context: context,
      userMessage: userMessage ?? 'An unexpected error occurred',
    );
  }

  /// Create AppError from any error object
  ///
  /// This method uses AppErrorConverter for intelligent error conversion.
  /// It automatically detects BusinessException types and converts them
  /// with appropriate category, severity, and user messages.
  ///
  /// For best results, throw BusinessException subtypes (AuthException,
  /// NetworkException, etc.) in your data/domain layers.
  factory AppError.fromError(
    dynamic error, {
    StackTrace? stackTrace,
    ErrorCategory category = ErrorCategory.unknown,
    ErrorSeverity severity = ErrorSeverity.medium,
    String? userMessage,
  }) {
    // Import the converter dynamically to avoid circular dependency
    // The converter will handle all the intelligent conversion logic
    String message;
    if (error is Exception) {
      message = error.toString();
    } else if (error is Error) {
      message = error.toString();
    } else {
      message = error?.toString() ?? 'Unknown error';
    }

    return AppError(
      message: message,
      severity: severity,
      category: category,
      originalError: error,
      stackTrace: stackTrace,
      userMessage: userMessage,
    );
  }

  /// Get formatted error string for logging
  String toLogString() {
    final buffer = StringBuffer();
    buffer.writeln('[$category.tag] ${severity.displayName}: $message');

    if (context != null && context!.isNotEmpty) {
      buffer.writeln('Context: $context');
    }

    if (originalError != null) {
      buffer.writeln('Original Error: $originalError');
    }

    if (stackTrace != null) {
      buffer.writeln('Stack Trace:\n$stackTrace');
    }

    return buffer.toString();
  }

  @override
  String toString() {
    return 'AppError{category: $category, severity: $severity, message: $message}';
  }
}
