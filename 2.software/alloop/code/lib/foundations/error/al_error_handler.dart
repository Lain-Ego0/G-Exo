import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:alloop/foundations/log/al_logger.dart';
import 'models/app_error.dart';
import 'models/error_severity.dart';
import 'models/error_category.dart';

/// Global error handler for the application
///
/// Captures and handles:
/// - Flutter framework errors (FlutterError.onError)
/// - Dart uncaught errors (PlatformDispatcher.onError)
/// - Zone errors (runZonedGuarded)
///
/// Features:
/// - Integrates with AlLogger for comprehensive error logging
/// - Error frequency tracking to prevent log spam
/// - Automatic error categorization and severity assessment
/// - User-friendly error messages in production
/// - Optional error reporting to external services
class AlErrorHandler {
  static bool _isInitialized = false;
  static FlutterExceptionHandler? _originalOnError;
  static bool Function(Object, StackTrace)? _originalPlatformError;

  /// Error frequency tracking to prevent log spam
  static final Map<String, _ErrorFrequency> _errorFrequencies = {};
  static const int _maxErrorsPerMinute = 10;
  static const Duration _frequencyWindow = Duration(minutes: 1);

  /// Private constructor
  AlErrorHandler._();

  /// Initialize global error handling
  ///
  /// Should be called early in main() before runApp()
  static void initialize({
    bool handleFlutterErrors = true,
    bool handlePlatformErrors = true,
    bool showErrorDetails = kDebugMode,
  }) {
    if (_isInitialized) {
      AlLogger.warning(
        'AlErrorHandler already initialized',
        tag: 'ErrorHandler',
      );
      return;
    }

    try {
      // Handle Flutter framework errors
      if (handleFlutterErrors) {
        _originalOnError = FlutterError.onError;
        FlutterError.onError = _handleFlutterError;
        AlLogger.info('Flutter error handler initialized', tag: 'ErrorHandler');
      }

      // Handle platform/Dart uncaught errors
      if (handlePlatformErrors) {
        _originalPlatformError = PlatformDispatcher.instance.onError;
        PlatformDispatcher.instance.onError = _handlePlatformError;
        AlLogger.info(
          'Platform error handler initialized',
          tag: 'ErrorHandler',
        );
      }

      // Configure error presentation
      if (!showErrorDetails) {
        // In production, show a simple error screen instead of red screen
        ErrorWidget.builder = _buildErrorWidget;
      }

      _isInitialized = true;
      AlLogger.info(
        'AlErrorHandler initialized successfully',
        tag: 'ErrorHandler',
      );
    } catch (e, stackTrace) {
      AlLogger.error(
        'Failed to initialize AlErrorHandler',
        tag: 'ErrorHandler',
        error: e,
        stackTrace: stackTrace,
      );
    }
  }

  /// Handle Flutter framework errors
  static void _handleFlutterError(FlutterErrorDetails details) {
    // Create structured error
    final appError = AppError.ui(
      message: details.exceptionAsString(),
      severity: _determineSeverity(details),
      originalError: details.exception,
      stackTrace: details.stack,
      context: {
        'library': details.library ?? 'unknown',
        'context': details.context?.toString() ?? 'none',
      },
    );

    // Log the error
    _logError(appError);

    // Call original handler if exists (for development tools)
    if (_originalOnError != null) {
      _originalOnError!(details);
    }
  }

  /// Handle platform/Dart uncaught errors
  static bool _handlePlatformError(Object error, StackTrace stackTrace) {
    // Create structured error
    final appError = AppError.fromError(
      error,
      stackTrace: stackTrace,
      category: _categorizeError(error),
      severity: ErrorSeverity.high,
    );

    // Log the error
    _logError(appError);

    // Call original handler if exists
    if (_originalPlatformError != null) {
      return _originalPlatformError!(error, stackTrace);
    }

    // Return true to indicate error was handled
    return true;
  }

  /// Handle zone errors (for runZonedGuarded)
  static void onZoneError(Object error, StackTrace stackTrace) {
    final appError = AppError.fromError(
      error,
      stackTrace: stackTrace,
      category: _categorizeError(error),
      severity: ErrorSeverity.high,
    );

    _logError(appError);
  }

  /// Log error with frequency control
  static void _logError(AppError error) {
    // Check error frequency to prevent spam
    if (!_shouldLogError(error)) {
      return;
    }

    // Log based on severity
    switch (error.severity) {
      case ErrorSeverity.low:
        AlLogger.info(
          error.message,
          tag: error.category.tag,
          error: error.originalError,
          stackTrace: error.stackTrace,
        );
        break;
      case ErrorSeverity.medium:
        AlLogger.warning(
          error.message,
          tag: error.category.tag,
          error: error.originalError,
          stackTrace: error.stackTrace,
        );
        break;
      case ErrorSeverity.high:
      case ErrorSeverity.critical:
        AlLogger.error(
          error.message,
          tag: error.category.tag,
          error: error.originalError,
          stackTrace: error.stackTrace,
        );
        break;
    }

    // TODO: Optional error reporting to external service (Sentry, Firebase, etc.)
    // _reportToExternalService(error);
  }

  /// Check if error should be logged (frequency control)
  static bool _shouldLogError(AppError error) {
    final key = '${error.category}_${error.message}';
    final now = DateTime.now();

    // Get or create frequency tracker
    final frequency = _errorFrequencies.putIfAbsent(
      key,
      () => _ErrorFrequency(firstOccurrence: now),
    );

    // Reset if outside frequency window
    if (now.difference(frequency.firstOccurrence) > _frequencyWindow) {
      frequency.count = 0;
      frequency.firstOccurrence = now;
    }

    // Increment count
    frequency.count++;
    frequency.lastOccurrence = now;

    // Check if within limits
    if (frequency.count > _maxErrorsPerMinute) {
      // Log suppression message once
      if (frequency.count == _maxErrorsPerMinute + 1) {
        AlLogger.warning(
          'Error frequency limit reached for: ${error.category.displayName} - ${error.message.substring(0, 50)}...',
          tag: 'ErrorHandler',
        );
      }
      return false;
    }

    return true;
  }

  /// Determine error severity from FlutterErrorDetails
  static ErrorSeverity _determineSeverity(FlutterErrorDetails details) {
    final exception = details.exception;

    // Critical errors
    if (exception is AssertionError || exception is StateError) {
      return ErrorSeverity.critical;
    }

    // High severity errors
    if (exception is FormatException || exception is TypeError) {
      return ErrorSeverity.high;
    }

    // Layout/rendering errors are usually medium
    if (details.library == 'rendering library' ||
        details.library == 'widgets library') {
      return ErrorSeverity.medium;
    }

    // Default to medium
    return ErrorSeverity.medium;
  }

  /// Categorize error based on type
  static ErrorCategory _categorizeError(Object error) {
    final errorString = error.toString().toLowerCase();

    // Network errors
    if (errorString.contains('socket') ||
        errorString.contains('network') ||
        errorString.contains('http') ||
        errorString.contains('connection')) {
      return ErrorCategory.network;
    }

    // Auth errors
    if (errorString.contains('auth') ||
        errorString.contains('token') ||
        errorString.contains('permission')) {
      return ErrorCategory.auth;
    }

    // Health errors
    if (errorString.contains('health') || errorString.contains('permission')) {
      return ErrorCategory.health;
    }

    // System errors
    if (errorString.contains('platform') ||
        errorString.contains('file') ||
        errorString.contains('storage')) {
      return ErrorCategory.system;
    }

    return ErrorCategory.unknown;
  }

  /// Build custom error widget for production
  static Widget _buildErrorWidget(FlutterErrorDetails details) {
    return MaterialApp(
      home: Scaffold(
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24.0),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.error_outline, color: Colors.red[300], size: 80),
                const SizedBox(height: 24),
                const Text(
                  'Something went wrong',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 16),
                Text(
                  kDebugMode
                      ? details.exceptionAsString()
                      : 'We apologize for the inconvenience. Please restart the app.',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 14, color: Colors.grey[600]),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  /// Manually report an error
  static void reportError(AppError error, {bool includeStackTrace = true}) {
    _logError(error);
  }

  /// Manually report a simple error
  static void reportSimpleError(
    String message, {
    ErrorCategory category = ErrorCategory.unknown,
    ErrorSeverity severity = ErrorSeverity.medium,
    dynamic error,
    StackTrace? stackTrace,
  }) {
    final appError = AppError(
      message: message,
      severity: severity,
      category: category,
      originalError: error,
      stackTrace: stackTrace,
    );
    _logError(appError);
  }

  /// Clear error frequency tracking (for testing)
  @visibleForTesting
  static void clearFrequencyTracking() {
    _errorFrequencies.clear();
  }

  /// Reset error handler (for testing)
  @visibleForTesting
  static void reset() {
    if (_originalOnError != null) {
      FlutterError.onError = _originalOnError;
    }
    if (_originalPlatformError != null) {
      PlatformDispatcher.instance.onError = _originalPlatformError;
    }
    _isInitialized = false;
    _errorFrequencies.clear();
  }
}

/// Internal class for tracking error frequency
class _ErrorFrequency {
  int count = 0;
  DateTime firstOccurrence;
  DateTime lastOccurrence;

  _ErrorFrequency({required this.firstOccurrence})
    : lastOccurrence = firstOccurrence;
}
