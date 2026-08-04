import 'dart:io';
import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:alloop/foundations/log/al_logger.dart';
import 'package:get/get.dart';
import 'package:device_info_plus/device_info_plus.dart';

/// Bluetooth permission utility class
///
/// Encapsulates Bluetooth permission-related operations
class AlPermissionUtils {
  AlPermissionUtils._();

  /// Check if Bluetooth permissions are granted
  ///
  /// Returns true if all required permissions are granted
  static Future<bool> hasBluetoothPermissions() async {
    try {
      if (Platform.isAndroid) {
        // Android 12+ requires bluetoothScan and bluetoothConnect
        // Android 11- requires location permission
        final androidInfo = await _getAndroidVersion();
        if (androidInfo >= 31) {
          // Android 12+ (API 31+)
          final bluetoothScan = await Permission.bluetoothScan.status;
          final bluetoothConnect = await Permission.bluetoothConnect.status;
          final hasPermissions =
              bluetoothScan.isGranted && bluetoothConnect.isGranted;
          AlLogger.debug(
            'Android 12+ Bluetooth permissions check: bluetoothScan=${bluetoothScan.isGranted}, bluetoothConnect=${bluetoothConnect.isGranted}',
            tag: 'AlPermissionUtils',
          );
          return hasPermissions;
        } else {
          // Android 11- requires location permission for BLE scanning
          final location = await Permission.location.status;
          AlLogger.debug(
            'Android 11- Bluetooth permissions check: location=${location.isGranted}',
            tag: 'AlPermissionUtils',
          );
          return location.isGranted;
        }
      } else if (Platform.isIOS) {
        // iOS only requires bluetooth permission
        final bluetooth = await Permission.bluetooth.status;
        AlLogger.debug(
          'iOS Bluetooth permission check: ${bluetooth.isGranted}',
          tag: 'AlPermissionUtils',
        );
        return bluetooth.isGranted;
      }
      return false;
    } catch (e, stackTrace) {
      AlLogger.error(
        'Failed to check Bluetooth permissions: $e',
        tag: 'AlPermissionUtils',
        error: e,
        stackTrace: stackTrace,
      );
      return false;
    }
  }

  /// Request Bluetooth permissions
  ///
  /// Returns true if all required permissions are granted after request
  static Future<bool> requestBluetoothPermissions() async {
    try {
      if (Platform.isAndroid) {
        final androidInfo = await _getAndroidVersion();
        if (androidInfo >= 31) {
          // Android 12+ (API 31+)
          AlLogger.info(
            'Requesting Android 12+ Bluetooth permissions',
            tag: 'AlPermissionUtils',
          );
          final statuses = await [
            Permission.bluetoothScan,
            Permission.bluetoothConnect,
          ].request();

          final bluetoothScanGranted =
              statuses[Permission.bluetoothScan]?.isGranted ?? false;
          final bluetoothConnectGranted =
              statuses[Permission.bluetoothConnect]?.isGranted ?? false;

          AlLogger.info(
            'Android 12+ Bluetooth permission result: bluetoothScan=$bluetoothScanGranted, bluetoothConnect=$bluetoothConnectGranted',
            tag: 'AlPermissionUtils',
          );

          return bluetoothScanGranted && bluetoothConnectGranted;
        } else {
          // Android 11- requires location permission
          AlLogger.info(
            'Requesting Android 11- location permission for Bluetooth',
            tag: 'AlPermissionUtils',
          );
          final status = await Permission.location.request();
          AlLogger.info(
            'Android 11- location permission result: ${status.isGranted}',
            tag: 'AlPermissionUtils',
          );
          return status.isGranted;
        }
      } else if (Platform.isIOS) {
        // iOS only requires bluetooth permission
        AlLogger.info(
          'Requesting iOS Bluetooth permission',
          tag: 'AlPermissionUtils',
        );
        final status = await Permission.bluetooth.request();
        AlLogger.info(
          'iOS Bluetooth permission result: ${status.isGranted}',
          tag: 'AlPermissionUtils',
        );
        return status.isGranted;
      }
      return false;
    } catch (e, stackTrace) {
      AlLogger.error(
        'Failed to request Bluetooth permissions: $e',
        tag: 'AlPermissionUtils',
        error: e,
        stackTrace: stackTrace,
      );
      return false;
    }
  }

  /// Check and request Bluetooth permissions with user dialog
  ///
  /// Returns true if permissions are granted
  /// Shows dialog to guide user if permissions are denied
  static Future<bool> checkAndRequestBluetoothPermissions() async {
    // Check if already has permissions
    final hasPermissions = await hasBluetoothPermissions();
    if (hasPermissions) {
      AlLogger.debug(
        'Bluetooth permissions already granted',
        tag: 'AlPermissionUtils',
      );
      return true;
    }

    // Request permissions
    final granted = await requestBluetoothPermissions();
    if (granted) {
      AlLogger.info(
        'Bluetooth permissions granted after request',
        tag: 'AlPermissionUtils',
      );
      return true;
    }

    // Check if permanently denied
    final isPermanentlyDenied = await _isBluetoothPermissionPermanentlyDenied();
    if (isPermanentlyDenied) {
      AlLogger.warning(
        'Bluetooth permissions permanently denied, showing settings dialog',
        tag: 'AlPermissionUtils',
      );
      await _showPermissionDeniedDialog();
      return false;
    }

    AlLogger.warning(
      'Bluetooth permissions denied by user',
      tag: 'AlPermissionUtils',
    );
    return false;
  }

  /// Check if Bluetooth permission is permanently denied
  static Future<bool> _isBluetoothPermissionPermanentlyDenied() async {
    try {
      if (Platform.isAndroid) {
        final androidInfo = await _getAndroidVersion();
        if (androidInfo >= 31) {
          final bluetoothScan = await Permission.bluetoothScan.status;
          final bluetoothConnect = await Permission.bluetoothConnect.status;
          return bluetoothScan.isPermanentlyDenied ||
              bluetoothConnect.isPermanentlyDenied;
        } else {
          final location = await Permission.location.status;
          return location.isPermanentlyDenied;
        }
      } else if (Platform.isIOS) {
        final bluetooth = await Permission.bluetooth.status;
        return bluetooth.isPermanentlyDenied;
      }
      return false;
    } catch (e, stackTrace) {
      AlLogger.error(
        'Failed to check if Bluetooth permission is permanently denied: $e',
        tag: 'AlPermissionUtils',
        error: e,
        stackTrace: stackTrace,
      );
      return false;
    }
  }

  /// Show dialog when permissions are denied
  static Future<void> _showPermissionDeniedDialog() async {
    await Get.dialog(
      AlertDialog(
        title: const Text('Bluetooth Permission Required'),
        content: const Text(
          'Scanning for Bluetooth devices requires Bluetooth permission. Please enable it in Settings.',
        ),
        actions: [
          TextButton(onPressed: () => Get.back(), child: const Text('Cancel')),
          TextButton(
            onPressed: () {
              Get.back();
              openAppSettings();
              AlLogger.info(
                'User opened app settings to grant Bluetooth permissions',
                tag: 'AlPermissionUtils',
              );
            },
            child: const Text('Open Settings'),
          ),
        ],
      ),
      barrierDismissible: false,
    );
  }

  /// Get Android SDK version
  static Future<int> _getAndroidVersion() async {
    if (Platform.isAndroid) {
      try {
        final deviceInfo = DeviceInfoPlugin();
        final androidInfo = await deviceInfo.androidInfo;
        final sdkInt = androidInfo.version.sdkInt;
        AlLogger.debug(
          'Android SDK version: $sdkInt',
          tag: 'AlPermissionUtils',
        );
        return sdkInt;
      } catch (e, stackTrace) {
        AlLogger.error(
          'Failed to get Android SDK version, defaulting to 31: $e',
          tag: 'AlPermissionUtils',
          error: e,
          stackTrace: stackTrace,
        );
        return 31; // Default to Android 12 (API 31) if error occurs
      }
    }
    return 0;
  }
}
