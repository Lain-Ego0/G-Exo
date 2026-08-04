import 'package:alloop/features/common/presentation/controllers/device_status_controller.dart';
import 'package:alloop/features/common/presentation/widgets/common_title_text.dart';
import 'package:alloop/features/device_detail/presentation/widgets/connected_widgets.dart';
import 'package:alloop/features/device_detail/presentation/widgets/diconnect_widgets.dart';
import 'package:alloop_blue_lite/alloop_blue_lite.dart';
import 'package:flutter/material.dart';
import 'package:get/get.dart';

import '../controllers/device_detail_controller.dart';
import 'package:flutter_screenutil/flutter_screenutil.dart';

class DeviceDetailPage extends GetView<DeviceDetailController> {
  final LiteDevice device;

  const DeviceDetailPage({super.key, required this.device});

  DeviceStatusController get _deviceStatusController =>
      Get.find<DeviceStatusController>();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Obx(
          () => CommonTitleText(
            title: controller.deviceName.value.isEmpty
                ? (device.name.isEmpty ? 'Unnamed Device' : device.name)
                : controller.deviceName.value,
          ),
        ),
        actions: [
          Obx(
            () => controller.isConnected.value
                ? IconButton(
                    tooltip: 'Disconnect',
                    icon: const Icon(Icons.bluetooth_disabled),
                    onPressed: controller.disconnect,
                  )
                : const SizedBox.shrink(),
          ),
        ],
      ),
      body: Obx(() {
        final isConnected = controller.isConnected.value;

        return SingleChildScrollView(
          padding: EdgeInsets.all(16.w),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (isConnected) ...[
                ConnectedOverviewCard(
                  deviceId: device.id,
                  status: _deviceStatusController.currentStatus.value,
                  deviceInfo: controller.deviceInfo.value,
                ),
                SizedBox(height: 16.h),
                DebugEntriesCard(
                  onAlgorithmDebug: controller.goToAlgorithmDebug,
                  onHistorySyncDebug: controller.goToHistorySyncDebug,
                ),
              ] else ...[
                DisconnectDeviceInfoCard(device: device),
                SizedBox(height: 16.h),
                ConnectionCard(
                  isConnecting: controller.isConnecting.value,
                  onConnect: controller.connect,
                ),
                SizedBox(height: 16.h),
                DisconnectHintCard(
                  icon: Icons.info_outline,
                  title: 'Features locked',
                  subtitle: 'Connect a device first to use SpO2 verification and history data sync.',
                ),
              ],
            ],
          ),
        );
      }),
    );
  }
}
