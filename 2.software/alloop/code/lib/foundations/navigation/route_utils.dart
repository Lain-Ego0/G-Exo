import 'package:alloop_blue_lite/alloop_blue_lite.dart';
import 'package:get/get.dart';

import '../../features/common/data/repositories/common_repository.dart';
import '../../features/common/presentation/controllers/device_status_controller.dart';

/// Utility class for parsing route arguments.
///
/// Provides unified argument extraction and validation methods to avoid
/// duplicated code.
class RouteUtils {
  RouteUtils._(); // Private constructor to prevent instantiation

  /// Extracts the deviceId from [arguments].
  ///
  /// Supports two formats:
  /// - [String]: the deviceId directly
  /// - [Map<String, dynamic>]: contains a 'deviceId' key
  ///
  /// Returns the extracted deviceId, or null if it cannot be extracted.
  static String? extractDeviceId(dynamic arguments) {
    if (arguments is String) {
      return arguments;
    } else if (arguments is Map<String, dynamic>) {
      return arguments['deviceId'] as String?;
    } else if (arguments is LiteDevice) {
      return arguments.id;
    }
    return null;
  }

  /// Extracts a LiteDevice from [arguments].
  ///
  /// Used by scenarios that need the full device object, such as the device
  /// detail page.
  static LiteDevice? extractDevice(dynamic arguments) {
    return arguments as LiteDevice?;
  }
}

/// Binding for global controllers.
///
/// Centrally manages the controllers and repositories that need to be shared
/// across the entire app, avoiding repeated registration in each page's
/// binding.
class GlobalControllersBinding extends Bindings {
  @override
  void dependencies() {
    // Register the common repository (lazily)
    if (!Get.isRegistered<CommonRepository>()) {
      Get.lazyPut(() => CommonRepository());
    }
  }
}

/// Base binding class for device-related pages.
///
/// Provides unified dependency injection logic for pages that need a deviceId.
abstract class DevicePageBinding extends Bindings {
  /// Extracts the deviceId from Get.arguments.
  String? extractDeviceId() {
    return RouteUtils.extractDeviceId(Get.arguments);
  }

  /// Registers the common controllers related to device status.
  ///
  /// Subclasses can call this method to ensure the base dependencies are
  /// registered.
  void registerCommonControllers(String deviceId) {
    // Register the global controllers first
    GlobalControllersBinding().dependencies();

    // Register the device status controller (if not already registered)
    if (!Get.isRegistered<DeviceStatusController>()) {
      Get.put<DeviceStatusController>(
        DeviceStatusController(repository: Get.find()),
        permanent: true,
      );
    }
  }
}
