import 'package:flutter/material.dart';
import 'package:get/get.dart';
import '../log/al_logger.dart';

/// Route navigation service.
/// Wraps GetX routing functionality to provide a unified navigation API.
class AlRouter {
  static final AlRouter _instance = AlRouter._internal();
  factory AlRouter() => _instance;
  AlRouter._internal() {
    AlLogger.info('AlRouter initialized', tag: 'AlRouter');
  }

  // ==================== Basic navigation methods ====================

  /// Navigates to the specified page.
  /// [page] the target page widget
  /// [binding] dependency injection bound to the page
  /// [transition] page transition animation
  /// [duration] animation duration
  /// [preventDuplicates] whether to prevent duplicate navigation
  Future<T?>? to<T>(
    Widget page, {
    Bindings? binding,
    Transition? transition,
    Duration? duration,
    bool preventDuplicates = true,
  }) {
    try {
      AlLogger.info('Navigating to: ${page.runtimeType}', tag: 'AlRouter');
      return Get.to<T>(
        () => page,
        binding: binding,
        transition: transition,
        duration: duration,
        preventDuplicates: preventDuplicates,
      );
    } catch (e) {
      AlLogger.error(
        'Failed to navigate to ${page.runtimeType}: $e',
        tag: 'AlRouter',
      );
      rethrow;
    }
  }

  /// Navigates using a named route.
  /// [routeName] the route name
  /// [arguments] the arguments to pass
  /// [parameters] URL parameters
  /// [preventDuplicates] whether to prevent duplicate navigation
  Future<T?>? toNamed<T>(
    String routeName, {
    dynamic arguments,
    Map<String, String>? parameters,
    bool preventDuplicates = true,
  }) {
    try {
      AlLogger.info('Navigating to named route: $routeName', tag: 'AlRouter');
      return Get.toNamed<T>(
        routeName,
        arguments: arguments,
        parameters: parameters,
        preventDuplicates: preventDuplicates,
      );
    } catch (e) {
      AlLogger.error('Failed to navigate to $routeName: $e', tag: 'AlRouter');
      rethrow;
    }
  }

  /// Replaces the current page.
  /// [page] the target page widget
  /// [binding] dependency injection bound to the page
  /// [transition] page transition animation
  /// [duration] animation duration
  Future<T?>? off<T>(
    Widget page, {
    Bindings? binding,
    Transition? transition,
    Duration? duration,
  }) {
    try {
      AlLogger.info(
        'Replacing current page with: ${page.runtimeType}',
        tag: 'AlRouter',
      );
      return Get.off<T>(
        () => page,
        binding: binding,
        transition: transition,
        duration: duration,
      );
    } catch (e) {
      AlLogger.error(
        'Failed to replace with ${page.runtimeType}: $e',
        tag: 'AlRouter',
      );
      rethrow;
    }
  }

  /// Replaces the current page using a named route.
  /// [routeName] the route name
  /// [arguments] the arguments to pass
  /// [parameters] URL parameters
  Future<T?>? offNamed<T>(
    String routeName, {
    dynamic arguments,
    Map<String, String>? parameters,
  }) {
    try {
      AlLogger.info(
        'Replacing current page with named route: $routeName',
        tag: 'AlRouter',
      );
      return Get.offNamed<T>(
        routeName,
        arguments: arguments,
        parameters: parameters,
      );
    } catch (e) {
      AlLogger.error('Failed to replace with $routeName: $e', tag: 'AlRouter');
      rethrow;
    }
  }

  /// Clears the entire route stack and navigates to the specified page.
  /// [page] the target page widget
  /// [binding] dependency injection bound to the page
  /// [transition] page transition animation
  /// [duration] animation duration
  Future<T?>? offAll<T>(
    Widget page, {
    Bindings? binding,
    Transition? transition,
    Duration? duration,
  }) {
    try {
      AlLogger.info(
        'Clearing all routes and navigating to: ${page.runtimeType}',
        tag: 'AlRouter',
      );
      return Get.offAll<T>(
        () => page,
        binding: binding,
        transition: transition,
        duration: duration,
      );
    } catch (e) {
      AlLogger.error(
        'Failed to clear all and navigate to ${page.runtimeType}: $e',
        tag: 'AlRouter',
      );
      rethrow;
    }
  }

  /// Clears the entire route stack and navigates using a named route.
  /// [routeName] the route name
  /// [arguments] the arguments to pass
  /// [parameters] URL parameters
  Future<T?>? offAllNamed<T>(
    String routeName, {
    dynamic arguments,
    Map<String, String>? parameters,
  }) {
    try {
      AlLogger.info(
        'Clearing all routes and navigating to named route: $routeName',
        tag: 'AlRouter',
      );
      return Get.offAllNamed<T>(
        routeName,
        arguments: arguments,
        parameters: parameters,
      );
    } catch (e) {
      AlLogger.error(
        'Failed to clear all and navigate to $routeName: $e',
        tag: 'AlRouter',
      );
      rethrow;
    }
  }

  /// Goes back to the previous page.
  /// [result] the result to return to the previous page
  /// [closeOverlays] whether to close overlays
  void back<T>({T? result, bool closeOverlays = false}) {
    try {
      AlLogger.info('Going back', tag: 'AlRouter');
      Get.back<T>(result: result, closeOverlays: closeOverlays);
    } catch (e) {
      AlLogger.error('Failed to go back: $e', tag: 'AlRouter');
    }
  }

  /// Goes back until the specified route.
  /// [routeName] the target route name
  void backUntil(String routeName) {
    try {
      AlLogger.info('Going back until: $routeName', tag: 'AlRouter');
      Get.until((route) => route.settings.name == routeName);
    } catch (e) {
      AlLogger.error('Failed to go back until $routeName: $e', tag: 'AlRouter');
    }
  }

  // ==================== Overlay-related methods ====================

  /// Shows a bottom sheet.
  /// [widget] the bottom sheet content
  /// [isScrollControlled] whether scrolling is controlled
  /// [backgroundColor] background color
  /// [elevation] shadow elevation
  /// [shape] shape
  Future<T?> showBottomSheet<T>(
    Widget widget, {
    bool isScrollControlled = false,
    Color? backgroundColor,
    double? elevation,
    ShapeBorder? shape,
  }) {
    try {
      AlLogger.info('Showing bottom sheet', tag: 'AlRouter');
      return Get.bottomSheet<T>(
        widget,
        isScrollControlled: isScrollControlled,
        backgroundColor: backgroundColor,
        elevation: elevation,
        shape: shape,
      );
    } catch (e) {
      AlLogger.error('Failed to show bottom sheet: $e', tag: 'AlRouter');
      rethrow;
    }
  }

  /// Shows a dialog.
  /// [widget] the dialog content
  /// [barrierDismissible] whether tapping the barrier dismisses it
  Future<T?> showDialog<T>(Widget widget, {bool barrierDismissible = true}) {
    try {
      AlLogger.info('Showing dialog', tag: 'AlRouter');
      return Get.dialog<T>(widget, barrierDismissible: barrierDismissible);
    } catch (e) {
      AlLogger.error('Failed to show dialog: $e', tag: 'AlRouter');
      rethrow;
    }
  }

  /// Shows a SnackBar.
  /// [title] the title
  /// [message] the message content
  /// [duration] the display duration
  /// [backgroundColor] background color
  /// [colorText] text color
  /// [snackPosition] display position
  void showSnackBar(
    String title,
    String message, {
    Duration duration = const Duration(seconds: 3),
    Color? backgroundColor,
    Color? colorText,
    SnackPosition snackPosition = SnackPosition.TOP,
  }) {
    try {
      AlLogger.info('Showing snackbar: $title - $message', tag: 'AlRouter');
      Get.snackbar(
        title,
        message,
        duration: duration,
        backgroundColor: backgroundColor,
        colorText: colorText,
        snackPosition: snackPosition,
      );
    } catch (e) {
      AlLogger.error('Failed to show snackbar: $e', tag: 'AlRouter');
    }
  }

  // ==================== Utility methods ====================

  /// Returns the current route name.
  String? get currentRoute {
    try {
      final route = Get.currentRoute;
      AlLogger.info('Current route: $route', tag: 'AlRouter');
      return route;
    } catch (e) {
      AlLogger.error('Failed to get current route: $e', tag: 'AlRouter');
      return null;
    }
  }

  /// Returns the route parameters.
  Map<String, String?> get parameters {
    try {
      final params = Get.parameters;
      AlLogger.info('Route parameters: $params', tag: 'AlRouter');
      return params;
    } catch (e) {
      AlLogger.error('Failed to get parameters: $e', tag: 'AlRouter');
      return {};
    }
  }

  /// Returns the passed arguments.
  dynamic get arguments {
    try {
      final args = Get.arguments;
      AlLogger.info('Route arguments: $args', tag: 'AlRouter');
      return args;
    } catch (e) {
      AlLogger.error('Failed to get arguments: $e', tag: 'AlRouter');
      return null;
    }
  }

  /// Checks whether it is possible to go back.
  bool get canPop {
    try {
      final canPop = Get.key.currentState?.canPop() ?? false;
      AlLogger.info('Can pop: $canPop', tag: 'AlRouter');
      return canPop;
    } catch (e) {
      AlLogger.error('Failed to check canPop: $e', tag: 'AlRouter');
      return false;
    }
  }

  /// Closes all overlays.
  void closeAllDialogs() {
    try {
      AlLogger.info('Closing all dialogs', tag: 'AlRouter');
      if (Get.isDialogOpen ?? false) {
        Get.back();
      }
      if (Get.isBottomSheetOpen ?? false) {
        Get.back();
      }
      if (Get.isSnackbarOpen) {
        Get.closeAllSnackbars();
      }
    } catch (e) {
      AlLogger.error('Failed to close all dialogs: $e', tag: 'AlRouter');
    }
  }

  // ==================== Business-specific methods ====================

  /// Navigates to the privacy policy page.
  Future<T?>? toPrivacyPolicy<T>({dynamic arguments}) {
    return toNamed<T>('/privacy-policy', arguments: arguments);
  }

  /// Navigates to the home page.
  Future<T?>? toHome<T>({dynamic arguments}) {
    return toNamed<T>('/home', arguments: arguments);
  }

  /// Clears all routes and navigates to the home page.
  Future<T?>? toHomeAndClearAll<T>({dynamic arguments}) {
    return offAllNamed<T>('/home', arguments: arguments);
  }

  /// Navigates to the splash page.
  Future<T?>? toSplash<T>({dynamic arguments}) {
    return toNamed<T>('/splash', arguments: arguments);
  }

  /// Navigates from the privacy policy page to the splash page (replacing the current page).
  Future<T?>? fromPrivacyToSplash<T>({dynamic arguments}) {
    return offNamed<T>('/splash', arguments: arguments);
  }
}
