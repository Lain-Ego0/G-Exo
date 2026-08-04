import 'package:alloop/features/main/home_page.dart';
import 'package:alloop/features/scan/presentation/bindings/scan_binding.dart';
import 'package:alloop/features/scan/presentation/pages/scan_page.dart';
import 'package:flutter/material.dart';
import 'package:get/get.dart';

import '../../features/algorithm_verify/data/repositories/algorithm_verify_repository.dart';
import '../../features/algorithm_verify/presentation/controllers/algorithm_verify_controller.dart';
import '../../features/algorithm_verify/presentation/pages/algorithm_verify_page.dart';
import '../../features/common/presentation/controllers/device_status_controller.dart';
import '../../features/device_detail/data/device_detail_repository.dart';
import '../../features/device_detail/presentation/controllers/device_detail_controller.dart';
import '../../features/device_detail/presentation/pages/device_detail_page.dart';
import '../../features/history_sync_debug/presentation/controllers/history_sync_debug_controller.dart';
import '../../features/history_sync_debug/presentation/pages/history_sync_debug_page.dart';
import '../../features/main/splash_page.dart';
import '../../features/web_bridge/presentation/controllers/web_bridge_controller.dart';
import '../../features/web_bridge/presentation/pages/web_bridge_page.dart';
import 'route_utils.dart';

/// Application route configuration.
class AlRoutes {
  // Private constructor to prevent instantiation
  AlRoutes._();

  /// Splash page
  static const String splash = '/splash';

  /// Home page
  static const String home = '/home';

  /// Bluetooth scan page
  static const String scan = '/scan';

  /// Device detail page
  static const String deviceDetail = '/deviceDetail';

  /// Algorithm verification mode page (SpO2)
  static const String algorithmVerify = '/algorithmVerify';

  /// History data sync debug page
  static const String historySyncDebug = '/historySyncDebug';

  /// Android-to-web local bridge page
  static const String webBridge = '/webBridge';
}

class AlPages {
  static List<GetPage> get pages => [
    // Splash page
    GetPage(
      name: AlRoutes.splash,
      page: () => const SplashPage(),
      transition: Transition.fade,
      transitionDuration: const Duration(milliseconds: 300),
    ),

    GetPage(
      name: AlRoutes.home,
      page: () => const HomePage(),
      transition: Transition.fadeIn,
      transitionDuration: const Duration(milliseconds: 300),
    ),

    // Bluetooth scan page
    GetPage(
      name: AlRoutes.scan,
      page: () => const ScanPage(),
      binding: ScanBinding(),
      transition: Transition.fadeIn,
      transitionDuration: const Duration(milliseconds: 300),
    ),

    // Device detail page
    GetPage(
      name: AlRoutes.deviceDetail,
      page: () {
        final device = RouteUtils.extractDevice(Get.arguments);
        if (device == null) {
          return const Scaffold(
            body: Center(child: Text('Invalid device parameter')),
          );
        }
        return DeviceDetailPage(device: device);
      },
      binding: BindingsBuilder(() {
        final device = RouteUtils.extractDevice(Get.arguments);
        if (device != null) {
          // Register the global controllers
          GlobalControllersBinding().dependencies();

          // Register DeviceStatusController as a global singleton (permanent, not removed on page exit)
          if (!Get.isRegistered<DeviceStatusController>()) {
            Get.put<DeviceStatusController>(
              DeviceStatusController(repository: Get.find()),
              permanent: true,
            );
          }

          Get.lazyPut(() => DeviceDetailRepository(deviceId: device.id));
          Get.lazyPut(
            () => DeviceDetailController(
              repository: Get.find(),
              initialName: device.name,
            ),
          );
        }
      }),
      transition: Transition.fadeIn,
      transitionDuration: const Duration(milliseconds: 300),
    ),

    // Algorithm verification mode page (SpO2 verification + PPG waveform)
    GetPage(
      name: AlRoutes.algorithmVerify,
      page: () {
        final deviceId = RouteUtils.extractDeviceId(Get.arguments);
        if (deviceId == null) {
          return const Scaffold(body: Center(child: Text('Device ID missing')));
        }
        return const AlgorithmVerifyPage();
      },
      binding: BindingsBuilder(() {
        final deviceId = RouteUtils.extractDeviceId(Get.arguments);
        if (deviceId != null) {
          // Register the global controllers
          GlobalControllersBinding().dependencies();

          // Register the algorithm-verification-specific controllers
          Get.lazyPut(() => AlgorithmVerifyRepository());
          Get.lazyPut(
            () => AlgorithmVerifyController(
              deviceId: deviceId,
              repository: Get.find(),
            ),
          );
        }
      }),
      transition: Transition.fadeIn,
      transitionDuration: const Duration(milliseconds: 300),
    ),

    // History data sync debug page
    GetPage(
      name: AlRoutes.historySyncDebug,
      page: () {
        final deviceId = RouteUtils.extractDeviceId(Get.arguments);
        if (deviceId == null) {
          return const Scaffold(body: Center(child: Text('Device ID missing')));
        }
        return HistorySyncDebugPage(deviceId: deviceId);
      },
      binding: BindingsBuilder(() {
        final deviceId = RouteUtils.extractDeviceId(Get.arguments);
        if (deviceId != null) {
          // Register the global controllers
          GlobalControllersBinding().dependencies();

          Get.lazyPut(() => HistorySyncDebugController(deviceId: deviceId));
        }
      }),
      transition: Transition.fadeIn,
      transitionDuration: const Duration(milliseconds: 300),
    ),

    GetPage(
      name: AlRoutes.webBridge,
      page: () => const WebBridgePage(),
      binding: BindingsBuilder(() {
        Get.lazyPut(WebBridgeController.new);
      }),
      transition: Transition.fadeIn,
      transitionDuration: const Duration(milliseconds: 300),
    ),
  ];
}
