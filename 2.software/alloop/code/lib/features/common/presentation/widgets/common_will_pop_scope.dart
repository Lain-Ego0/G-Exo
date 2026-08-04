import 'package:flutter/material.dart';
import 'package:get/get.dart';

/// Back-navigation interceptor
class CommonWillPopScope extends StatelessWidget {
  /// Callback to check if measurement is running
  final bool Function() isMeasuring;

  /// Callback to stop the measurement
  final Future<void> Function()? onStopMeasurement;

  /// Child widget
  final Widget child;

  /// Confirmation dialog title (can be a callback for dynamic title)
  final String? confirmTitle;

  /// Confirmation dialog title callback (for dynamic title based on state)
  final String Function()? confirmTitleCallback;

  /// Confirmation dialog message (can be a callback for dynamic message)
  final String? confirmMessage;

  /// Confirmation dialog message callback (for dynamic message based on state)
  final String Function()? confirmMessageCallback;

  const CommonWillPopScope({
    super.key,
    required this.isMeasuring,
    required this.child,
    this.onStopMeasurement,
    this.confirmTitle,
    this.confirmTitleCallback,
    this.confirmMessage,
    this.confirmMessageCallback,
  });

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false, // Disable default back behavior
      onPopInvokedWithResult: (bool didPop, dynamic result) async {
        if (didPop) return;

        // If measurement is not running, allow direct back navigation
        if (!isMeasuring()) {
          Get.back();
          return;
        }

        // Measurement is running, show confirmation dialog
        final shouldExit = await _showExitConfirmationDialog(context);
        if (shouldExit == true && context.mounted) {
          // Stop the measurement
          await onStopMeasurement?.call();

          // Exit the page
          if (context.mounted) {
            Get.back();
          }
        }
      },
      child: child,
    );
  }

  /// Show exit confirmation dialog
  Future<bool?> _showExitConfirmationDialog(BuildContext context) async {
    // Get dynamic title and message
    final title = confirmTitleCallback?.call() ?? confirmTitle ?? 'Stop Measurement';
    final message =
        confirmMessageCallback?.call() ??
        confirmMessage ??
        'A measurement is in progress. Stop it and exit?';

    // Check if we should show only info dialog (no exit option)
    // This is determined by checking if onStopMeasurement will actually do anything
    // We can infer this by checking if the title suggests waiting
    final isWaitingDialog = title.contains('Please wait') || title.contains('Waiting');

    if (isWaitingDialog) {
      // Show info-only dialog with a single "OK" button
      return Get.dialog<bool?>(
        AlertDialog(
          title: Text(title),
          content: Text(message),
          actions: [
            TextButton(
              onPressed: () => Get.back(result: false),
              child: const Text('OK'),
            ),
          ],
        ),
        barrierDismissible: false,
      );
    }

    // Show normal confirmation dialog with cancel and exit options
    return Get.dialog<bool?>(
      AlertDialog(
        title: Text(title),
        content: Text(message),
        actions: [
          TextButton(
            onPressed: () => Get.back(result: false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Get.back(result: true),
            style: TextButton.styleFrom(
              foregroundColor: Get.theme.colorScheme.error,
            ),
            child: const Text('Stop & Exit'),
          ),
        ],
      ),
      barrierDismissible: false, // Don't close on barrier tap
    );
  }
}
