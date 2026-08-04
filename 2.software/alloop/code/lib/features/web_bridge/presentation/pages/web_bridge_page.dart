import 'package:flutter/material.dart';
import 'package:get/get.dart';

import '../controllers/web_bridge_controller.dart';
import '../widgets/bridge_status_panel.dart';

class WebBridgePage extends GetView<WebBridgeController> {
  const WebBridgePage({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Web Bridge')),
      body: Obx(() {
        final bridgeState = controller.state.value;
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            SwitchListTile(
              contentPadding: const EdgeInsets.symmetric(horizontal: 4),
              title: const Text('Bridge service'),
              subtitle: const Text('Listen on local IPv4 port 8766'),
              value: bridgeState.serviceRunning,
              onChanged: controller.isUpdating.value
                  ? null
                  : controller.setServiceEnabled,
              secondary: controller.isUpdating.value
                  ? const SizedBox.square(
                      dimension: 22,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.lan_outlined),
            ),
            const SizedBox(height: 8),
            BridgeStatusPanel(
              state: bridgeState,
              localAddresses: controller.localAddresses,
              token: controller.token.value,
              onRefreshAddresses: controller.refreshLocalAddresses,
            ),
            const SizedBox(height: 12),
            _Notice(
              icon: Icons.phone_android_outlined,
              text:
                  'Keep this app in the foreground while using the bridge.',
            ),
            const SizedBox(height: 8),
            _Notice(
              icon: Icons.wifi_outlined,
              text:
                  'The phone and Windows computer must use the same trusted LAN. Router AP isolation can block the connection.',
            ),
          ],
        );
      }),
    );
  }
}

class _Notice extends StatelessWidget {
  const _Notice({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: colors.secondaryContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: colors.onSecondaryContainer),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                text,
                style: TextStyle(color: colors.onSecondaryContainer),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
