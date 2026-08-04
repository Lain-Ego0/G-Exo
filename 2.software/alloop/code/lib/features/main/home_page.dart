import 'package:flutter/material.dart';
import 'package:flutter_screenutil/flutter_screenutil.dart';

import '../../core/utils/al_permission_utils.dart';
import '../../core/utils/al_version_utils.dart';
import '../../foundations/navigation/al_router.dart';
import '../../foundations/navigation/al_routes.dart';

/// Home page: the demo app's single entry point -- navigates to the scan page.
class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  String _versionString = 'v1.0.0 (1)';

  @override
  void initState() {
    super.initState();
    _loadVersionInfo();
  }

  /// Load version information
  Future<void> _loadVersionInfo() async {
    final versionString = await AlVersionUtils.getFormattedVersion();
    if (mounted) {
      setState(() {
        _versionString = versionString;
      });
    }
  }

  /// Handle scan button tap
  Future<void> _handleScanButtonPressed() async {
    // Check and request Bluetooth permissions
    final hasPermission =
        await AlPermissionUtils.checkAndRequestBluetoothPermissions();

    // If permission granted, navigate to the scan page
    if (hasPermission && mounted) {
      AlRouter().toNamed(AlRoutes.scan);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Alloop Kit Demo'),
        centerTitle: true,
        elevation: 2,
      ),
      body: Padding(
        padding: EdgeInsets.all(16.0.w),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Card(
              child: Padding(
                padding: EdgeInsets.all(16.0.w),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Demo Flow',
                      style: TextStyle(
                        fontSize: 18.sp,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    SizedBox(height: 12.h),
                    Text(
                      'Scan → Connect → Device Detail → SpO2 Verification → History Data',
                      style: TextStyle(fontSize: 14.sp),
                    ),
                  ],
                ),
              ),
            ),
            SizedBox(height: 24.h),

            // Start scan button
            ElevatedButton.icon(
              onPressed: _handleScanButtonPressed,
              icon: const Icon(Icons.bluetooth_searching),
              label: const Text('Scan Devices'),
              style: ElevatedButton.styleFrom(padding: EdgeInsets.all(16.w)),
            ),

            SizedBox(height: 12.h),

            OutlinedButton.icon(
              onPressed: () => AlRouter().toNamed(AlRoutes.webBridge),
              icon: const Icon(Icons.lan_outlined),
              label: const Text('Open Web Bridge'),
              style: OutlinedButton.styleFrom(padding: EdgeInsets.all(16.w)),
            ),

            const Spacer(),

            // Version info
            Center(
              child: Text(
                'Alloop Kit Demo $_versionString',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 12.sp, color: Colors.grey[600]),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
