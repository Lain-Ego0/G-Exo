import 'package:alloop/features/algorithm_verify/domain/models/algorithm_verify_state.dart';
import 'package:alloop/features/common/presentation/widgets/common_title_text.dart';
import 'package:alloop/features/common/presentation/widgets/common_will_pop_scope.dart';
import 'package:flutter/material.dart';
import 'package:flutter_screenutil/flutter_screenutil.dart';
import 'package:get/get.dart';

import '../../../../widgets/chart/realtime_line_chart.dart';
import '../../../common/presentation/controllers/device_status_controller.dart';
import '../../../common/presentation/widgets/common_battery_indicator.dart';
import '../controllers/algorithm_verify_controller.dart';

/// SpO2 algorithm verification page.
///
/// Single-screen layout:
/// - AppBar: page title + device battery
/// - Top: start/stop/export controls + SpO2/HR value display (fixed, does not
///   scroll with the tabs)
/// - Bottom: TabBar (PPG / ACC) + the corresponding per-channel real-time
///   waveform charts
///   - PPG tab: ledG / ledGAmb / ledRedAmb / ledIr, four independent charts
///   - ACC tab: x / y / z, three independent charts with auto Y-axis scaling
class AlgorithmVerifyPage extends GetView<AlgorithmVerifyController> {
  const AlgorithmVerifyPage({super.key});

  DeviceStatusController get _deviceStatusController =>
      Get.find<DeviceStatusController>();

  @override
  Widget build(BuildContext context) {
    return CommonWillPopScope(
      isMeasuring: () => controller.state.value.isVerifying,
      onStopMeasurement: () async {
        if (controller.state.value.isVerifying) {
          await controller.stopMeasurement();
        }
      },
      confirmTitle: 'Stop Verification',
      confirmMessage:
          'Algorithm verification is in progress. Stop verification and exit?',
      child: Scaffold(
        appBar: AppBar(
          title: CommonTitleText(title: 'SpO2 Verification'),
          elevation: 1,
          actions: [
            Obx(
              () => CommonBatteryIndicator(
                batteryLevel:
                    _deviceStatusController.currentStatus.value?.batteryPercent,
                padding: EdgeInsets.only(right: 16.w),
              ),
            ),
          ],
        ),
        body: DefaultTabController(
          length: 2,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Padding(
                padding: EdgeInsets.fromLTRB(16.w, 16.h, 16.w, 0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _buildControlPanel(),
                    SizedBox(height: 16.h),
                    _buildMetricsCard(),
                  ],
                ),
              ),
              Container(
                margin: EdgeInsets.only(top: 16.h),
                color: Theme.of(context).cardColor,
                child: TabBar(
                  labelStyle: TextStyle(
                    fontSize: 13.sp,
                    fontWeight: FontWeight.w600,
                  ),
                  unselectedLabelStyle: TextStyle(fontSize: 13.sp),
                  tabs: const [Tab(text: 'PPG'), Tab(text: 'ACC')],
                ),
              ),
              const Divider(height: 1),
              Expanded(
                child: TabBarView(
                  children: [_buildPpgTab(), _buildAccTab()],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildControlPanel() {
    return Card(
      child: Padding(
        padding: EdgeInsets.all(16.w),
        child: Obx(() {
          final state = controller.state.value;
          return Row(
            children: [
              Expanded(
                child: ElevatedButton.icon(
                  onPressed: state.canStart ? controller.startMeasurement : null,
                  icon: const Icon(Icons.play_arrow),
                  label: const Text('Start'),
                ),
              ),
              SizedBox(width: 12.w),
              Expanded(
                child: ElevatedButton.icon(
                  onPressed: state.canStop ? controller.stopMeasurement : null,
                  icon: const Icon(Icons.stop),
                  label: const Text('Stop'),
                ),
              ),
              SizedBox(width: 12.w),
              Obx(
                () => IconButton(
                  tooltip: 'Export Data',
                  onPressed: controller.isSavingData.value
                      ? null
                      : controller.exportData,
                  icon: controller.isSavingData.value
                      ? SizedBox(
                          width: 20.w,
                          height: 20.w,
                          child: const CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.save_alt),
                ),
              ),
            ],
          );
        }),
      ),
    );
  }

  Widget _buildMetricsCard() {
    return Card(
      child: Padding(
        padding: EdgeInsets.all(16.w),
        child: Obx(() {
          final result = controller.latestResult.value;
          final state = controller.state.value;
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(Icons.favorite, color: Colors.red.shade400),
                  SizedBox(width: 8.w),
                  Text(
                    'SpO2',
                    style: TextStyle(fontSize: 14.sp, color: Colors.black54),
                  ),
                  SizedBox(width: 8.w),
                  Text(
                    controller.displaySpo2.value != null
                        ? '${controller.displaySpo2.value}%'
                        : '--',
                    style: TextStyle(
                      fontSize: 22.sp,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  SizedBox(width: 20.w),
                  Text(
                    'HR',
                    style: TextStyle(fontSize: 14.sp, color: Colors.black54),
                  ),
                  SizedBox(width: 8.w),
                  Text(
                    controller.displayHr.value != null
                        ? '${controller.displayHr.value} bpm'
                        : '--',
                    style: TextStyle(
                      fontSize: 22.sp,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ],
              ),
              SizedBox(height: 8.h),
              Text(
                state.isVerifying ? 'Verifying...' : 'Not measuring',
                style: TextStyle(fontSize: 12.sp, color: Colors.grey.shade600),
              ),
              if (result != null && result.success != null) ...[
                SizedBox(height: 4.h),
                Text(
                  result.success == true ? 'Valid measurement' : 'Invalid measurement',
                  style: TextStyle(
                    fontSize: 12.sp,
                    color: result.success == true ? Colors.green : Colors.orange,
                  ),
                ),
              ],
            ],
          );
        }),
      ),
    );
  }

  /// PPG tab: four independent channel charts stacked vertically, each scrollable.
  Widget _buildPpgTab() {
    return SingleChildScrollView(
      padding: EdgeInsets.all(16.w),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _buildSingleChannelChart(
            title: 'ledG',
            color: Colors.green,
            points: controller.ppgPointsLedG,
            autoScaleY: true,
          ),
          SizedBox(height: 12.h),
          _buildSingleChannelChart(
            title: 'ledGAmb',
            color: Colors.orange,
            points: controller.ppgPointsLedGAmb,
            autoScaleY: true,
          ),
          SizedBox(height: 12.h),
          _buildSingleChannelChart(
            title: 'ledRedAmb',
            color: Colors.red,
            points: controller.ppgPointsLedRedAmb,
            autoScaleY: true,
          ),
          SizedBox(height: 12.h),
          _buildSingleChannelChart(
            title: 'ledIr',
            color: Colors.blue,
            points: controller.ppgPointsLedIr,
            autoScaleY: true,
          ),
        ],
      ),
    );
  }

  /// ACC tab: three independent axis charts stacked vertically, with auto Y-axis scaling.
  Widget _buildAccTab() {
    return SingleChildScrollView(
      padding: EdgeInsets.all(16.w),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _buildSingleChannelChart(
            title: 'X',
            color: Colors.purple,
            points: controller.accPointsX,
            autoScaleY: true,
          ),
          SizedBox(height: 12.h),
          _buildSingleChannelChart(
            title: 'Y',
            color: Colors.teal,
            points: controller.accPointsY,
            autoScaleY: true,
          ),
          SizedBox(height: 12.h),
          _buildSingleChannelChart(
            title: 'Z',
            color: Colors.brown,
            points: controller.accPointsZ,
            autoScaleY: true,
          ),
        ],
      ),
    );
  }

  /// Single-channel chart card: title with a colored dot + RealTimeLineChart.
  Widget _buildSingleChannelChart({
    required String title,
    required Color color,
    required RxList<DataPoint> points,
    required bool autoScaleY,
  }) {
    return Card(
      child: Obx(() {
        return RealTimeLineChart(
          title: title,
          series: [ChartDataSeries(data: points.toList(), color: color, name: title)],
          windowSeconds: AlgorithmVerifyController.chartWindowSeconds,
          autoScaleY: autoScaleY,
          height: 180.h,
        );
      }),
    );
  }
}
