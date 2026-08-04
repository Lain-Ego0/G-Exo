import 'package:flutter/material.dart';
import 'package:fluttertoast/fluttertoast.dart';

/// AlLoop Toast wrapper.
///
/// Wraps the fluttertoast implementation to provide a unified toast API.
/// Follows the naming convention of the project's Al-series infrastructure
/// components.
///
/// Duration notes:
/// - Default [Toast.LENGTH_SHORT]: Android ≈ 2s, iOS ≈ 1s
/// - When [longDuration] is true, [Toast.LENGTH_LONG]: Android ≈ 3.5s, iOS ≈ 2s
class AlToast {
  static Toast _toastLength(bool longDuration) =>
      longDuration ? Toast.LENGTH_LONG : Toast.LENGTH_SHORT;

  /// Shows a success toast.
  static void showSuccess(String message, {bool longDuration = false}) {
    Fluttertoast.showToast(
      msg: message,
      toastLength: _toastLength(longDuration),
      gravity: ToastGravity.TOP,
      backgroundColor: Colors.green,
      textColor: Colors.white,
      fontSize: 16.0,
    );
  }

  /// Shows an error toast.
  static void showError(String message, {bool longDuration = false}) {
    Fluttertoast.showToast(
      msg: message,
      toastLength: _toastLength(longDuration),
      gravity: ToastGravity.TOP,
      backgroundColor: Colors.red,
      textColor: Colors.white,
      fontSize: 16.0,
    );
  }

  /// Shows an info toast.
  static void showInfo(String message, {bool longDuration = false}) {
    Fluttertoast.showToast(
      msg: message,
      toastLength: _toastLength(longDuration),
      gravity: ToastGravity.TOP,
      backgroundColor: Colors.blue,
      textColor: Colors.white,
      fontSize: 16.0,
    );
  }

  /// Shows a warning toast.
  static void showWarning(String message, {bool longDuration = false}) {
    Fluttertoast.showToast(
      msg: message,
      toastLength: _toastLength(longDuration),
      gravity: ToastGravity.TOP,
      backgroundColor: Colors.orange,
      textColor: Colors.white,
      fontSize: 16.0,
    );
  }
}
