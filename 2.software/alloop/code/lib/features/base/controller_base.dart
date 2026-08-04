import 'package:get/get.dart';
import '../../../foundations/log/al_logger.dart';

/// Base controller
///
/// Provides common controller functionality and lifecycle management
abstract class BaseController extends GetxController {
  /// Controller tag, used for logging
  String get tag => runtimeType.toString();

  /// Whether the controller has been initialized
  final RxBool isInitialized = false.obs;

  /// Whether the controller is loading
  final RxBool isLoading = false.obs;

  /// Error message
  final RxnString errorMessage = RxnString();

  @override
  void onInit() {
    super.onInit();
    AlLogger.info('Controller initialized', tag: tag);
  }

  @override
  void onReady() {
    super.onReady();
    AlLogger.info('Controller ready', tag: tag);
  }

  @override
  void onClose() {
    AlLogger.info('Controller disposed', tag: tag);
    super.onClose();
  }

  /// Set the loading state
  void setLoading(bool loading) {
    isLoading.value = loading;
  }

  /// Set the error message
  void setError(String? error) {
    errorMessage.value = error;
  }

  /// Clear the error message
  void clearError() {
    errorMessage.value = null;
  }

  /// Safely execute an async operation
  ///
  /// Automatically handles the loading state and error capture
  Future<T?> safeExecute<T>(
    Future<T> Function() operation, {
    bool showLoading = true,
    String? errorPrefix,
  }) async {
    try {
      if (showLoading) setLoading(true);
      clearError();

      final result = await operation();
      return result;
    } catch (e) {
      final errorMsg = errorPrefix != null ? '$errorPrefix: $e' : e.toString();
      setError(errorMsg);
      AlLogger.error(errorMsg, tag: tag, error: e);
      return null;
    } finally {
      if (showLoading) setLoading(false);
    }
  }

  /// Log a debug message
  void logDebug(String message) {
    AlLogger.debug(message, tag: tag);
  }

  /// Log an info message
  void logInfo(String message) {
    AlLogger.info(message, tag: tag);
  }

  /// Log a warning
  void logWarning(String message) {
    AlLogger.warning(message, tag: tag);
  }

  /// Log an error
  void logError(String message, [Object? error]) {
    AlLogger.error(message, tag: tag, error: error);
  }
}
