import 'package:alloop/features/common/presentation/widgets/common_title_text.dart';
import 'package:flutter/material.dart';
import 'package:flutter_screenutil/flutter_screenutil.dart';
import 'package:get/get.dart';

import '../../../../foundations/navigation/al_routes.dart';
import '../controllers/scan_controller.dart';

/// Scan page: filter input, connected devices section, and scan result list.
class ScanPage extends GetView<ScanController> {
  const ScanPage({super.key});

  Color _rssiColor(int rssi) {
    if (rssi >= -50) return Colors.green;
    if (rssi >= -60) return Colors.lightGreen;
    if (rssi >= -70) return Colors.orange;
    return Colors.red;
  }

  String _rssiLabel(int rssi) {
    if (rssi >= -50) return 'Excellent';
    if (rssi >= -60) return 'Good';
    if (rssi >= -70) return 'Fair';
    return 'Weak';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: CommonTitleText(title: 'Scan Devices'),
        actions: [
          Obx(
            () => controller.isScanning.value
                ? Padding(
                    padding: EdgeInsets.all(16.w),
                    child: SizedBox(
                      width: 20.w,
                      height: 20.w,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white,
                      ),
                    ),
                  )
                : IconButton(
                    tooltip: 'Rescan',
                    icon: Icon(Icons.refresh),
                    onPressed: controller.startScan,
                  ),
          ),
        ],
      ),
      body: Obx(
        () => Column(
          children: [
            _buildFilterBar(),
            if (controller.connectedDevices.isNotEmpty)
              _buildConnectedSection(),
            _buildScanStatusBar(),
            Expanded(child: _buildDeviceList()),
          ],
        ),
      ),
      floatingActionButton: Obx(
        () => FloatingActionButton.extended(
          onPressed: controller.isScanning.value
              ? controller.stopScan
              : controller.startScan,
          icon: Icon(
            controller.isScanning.value
                ? Icons.stop
                : Icons.bluetooth_searching,
          ),
          label: Text(controller.isScanning.value ? 'Stop Scan' : 'Start Scan'),
        ),
      ),
    );
  }

  Widget _buildFilterBar() {
    return Padding(
      padding: EdgeInsets.fromLTRB(16.w, 16.h, 16.w, 8.h),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: controller.filterController,
                  onChanged: controller.updateFilter,
                  decoration: InputDecoration(
                    prefixIcon: const Icon(Icons.search),
                    labelText: 'Device name filter',
                    hintText: 'Enter multiple names, separated by commas or spaces',
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12.r),
                    ),
                    suffixIcon: controller.filterController.text.isNotEmpty
                        ? IconButton(
                            tooltip: 'Clear',
                            icon: const Icon(Icons.clear),
                            onPressed: () {
                              controller.filterController.clear();
                              controller.updateFilter('');
                            },
                          )
                        : null,
                  ),
                ),
              ),
              SizedBox(width: 8.w),
              ElevatedButton(
                onPressed: controller.startScan,
                style: ElevatedButton.styleFrom(
                  padding: EdgeInsets.symmetric(horizontal: 14.w, vertical: 14.h),
                ),
                child: const Text('Apply & Scan'),
              ),
            ],
          ),
          if (controller.filterTexts.isNotEmpty) ...[
            SizedBox(height: 8.h),
            Wrap(
              spacing: 8.w,
              runSpacing: 4.h,
              children: controller.filterTexts.map((filter) {
                return Chip(
                  label: Text(filter, style: TextStyle(fontSize: 12.sp)),
                  backgroundColor: Colors.blue.shade50,
                  deleteIcon: Icon(Icons.close, size: 16.r),
                  onDeleted: () {
                    final newFilters = List<String>.from(controller.filterTexts)
                      ..remove(filter);
                    controller.filterController.text = newFilters.join(', ');
                    controller.updateFilter(controller.filterController.text);
                  },
                );
              }).toList(),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildConnectedSection() {
    return Container(
      width: double.infinity,
      padding: EdgeInsets.symmetric(horizontal: 16.w, vertical: 12.h),
      decoration: BoxDecoration(
        color: Colors.green.shade50,
        border: Border(
          bottom: BorderSide(color: Colors.green.shade100, width: 1),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                Icons.check_circle,
                color: Colors.green.shade700,
                size: 20.r,
              ),
              SizedBox(width: 8.w),
              Text(
                'Connected Devices (${controller.connectedDevices.length})',
                style: TextStyle(
                  fontSize: 14.sp,
                  fontWeight: FontWeight.w600,
                  color: Colors.green.shade700,
                ),
              ),
            ],
          ),
          SizedBox(height: 12.h),
          ...controller.connectedDevices.map(
            (device) => Padding(
              padding: EdgeInsets.only(bottom: 8.h),
              child: Material(
                color: Colors.white,
                borderRadius: BorderRadius.circular(8.r),
                elevation: 1,
                child: InkWell(
                  borderRadius: BorderRadius.circular(8.r),
                  onTap: () =>
                      Get.toNamed(AlRoutes.deviceDetail, arguments: device),
                  child: Padding(
                    padding: EdgeInsets.all(12.w),
                    child: Row(
                      children: [
                        Container(
                          width: 8.w,
                          height: 8.w,
                          decoration: const BoxDecoration(
                            color: Colors.green,
                            shape: BoxShape.circle,
                          ),
                        ),
                        SizedBox(width: 12.w),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                device.name.isEmpty ? 'Unnamed Device' : device.name,
                                style: TextStyle(
                                  fontWeight: FontWeight.w600,
                                  fontSize: 14.sp,
                                ),
                              ),
                              SizedBox(height: 2.h),
                              Text(
                                'ID: ${device.id}',
                                style: TextStyle(
                                  fontSize: 11.sp,
                                  color: Colors.grey.shade600,
                                ),
                              ),
                            ],
                          ),
                        ),
                        Icon(Icons.chevron_right, color: Colors.grey.shade400),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildScanStatusBar() {
    return Container(
      width: double.infinity,
      padding: EdgeInsets.all(16.w),
      color: controller.isScanning.value
          ? Colors.blue.shade50
          : Colors.grey.shade100,
      child: Row(
        children: [
          Icon(
            controller.isScanning.value
                ? Icons.bluetooth_searching
                : Icons.bluetooth,
            color: controller.isScanning.value ? Colors.blue : Colors.grey,
          ),
          SizedBox(width: 12.w),
          Expanded(
            child: Text(
              controller.isScanning.value
                  ? 'Scanning... ${controller.devices.length} device(s) found'
                  : 'Scan stopped, ${controller.devices.length} device(s) found',
              style: TextStyle(
                color: controller.isScanning.value
                    ? Colors.blue
                    : Colors.grey.shade700,
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildDeviceList() {
    if (controller.devices.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              controller.isScanning.value
                  ? Icons.bluetooth_searching
                  : Icons.bluetooth_disabled,
              size: 64.r,
              color: Colors.grey,
            ),
            SizedBox(height: 16.h),
            Text(
              controller.isScanning.value ? 'Searching for devices...' : 'No devices found',
              style: TextStyle(fontSize: 16.sp, color: Colors.grey),
            ),
          ],
        ),
      );
    }

    return ListView.builder(
      itemCount: controller.devices.length,
      itemBuilder: (context, index) {
        final device = controller.devices[index];
        return Card(
          margin: EdgeInsets.symmetric(horizontal: 16.w, vertical: 8.h),
          child: ListTile(
            leading: Icon(
              Icons.bluetooth,
              color: _rssiColor(device.rssi),
              size: 32.r,
            ),
            title: Text(
              device.name.isEmpty ? 'Unnamed Device' : device.name,
              style: const TextStyle(fontWeight: FontWeight.bold),
            ),
            subtitle: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(height: 4.h),
                Text(
                  'ID: ${device.id}',
                  style: TextStyle(
                    fontSize: 12.sp,
                    color: Colors.grey.shade600,
                  ),
                ),
                SizedBox(height: 2.h),
                Row(
                  children: [
                    Text(
                      'RSSI: ${device.rssi} dBm',
                      style: TextStyle(
                        fontSize: 12.sp,
                        color: _rssiColor(device.rssi),
                      ),
                    ),
                    SizedBox(width: 8.w),
                    Container(
                      padding: EdgeInsets.symmetric(
                        horizontal: 6.w,
                        vertical: 2.h,
                      ),
                      decoration: BoxDecoration(
                        color: _rssiColor(device.rssi).withValues(alpha: 0.2),
                        borderRadius: BorderRadius.circular(4.r),
                      ),
                      child: Text(
                        _rssiLabel(device.rssi),
                        style: TextStyle(
                          fontSize: 10.sp,
                          color: _rssiColor(device.rssi),
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  ],
                ),
              ],
            ),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Get.toNamed(AlRoutes.deviceDetail, arguments: device),
          ),
        );
      },
    );
  }
}
