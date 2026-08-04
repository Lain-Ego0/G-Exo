import 'package:flutter/material.dart';

import '../../domain/bridge_state.dart';

class BridgeStatusPanel extends StatelessWidget {
  const BridgeStatusPanel({
    required this.state,
    required this.localAddresses,
    required this.token,
    required this.onRefreshAddresses,
    super.key,
  });

  final BridgeState state;
  final List<String> localAddresses;
  final String token;
  final VoidCallback onRefreshAddresses;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final endpoints = localAddresses
        .map((address) => 'ws://$address:${state.port}/ws')
        .toList();

    return Card(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Bridge status', style: theme.textTheme.titleMedium),
            const SizedBox(height: 12),
            _StatusRow(
              icon: Icons.lan_outlined,
              label: 'Service',
              value: state.serviceRunning ? 'Running' : 'Stopped',
              active: state.serviceRunning,
            ),
            _StatusRow(
              icon: Icons.web_asset_outlined,
              label: 'Web client',
              value: state.webClientConnected ? 'Connected' : 'Disconnected',
              active: state.webClientConnected,
            ),
            _StatusRow(
              icon: Icons.circle_outlined,
              label: 'Ring',
              value: state.ringConnected ? 'Connected' : 'Disconnected',
              active: state.ringConnected,
            ),
            const Divider(height: 24),
            Row(
              children: [
                Expanded(
                  child: Text(
                    'LAN endpoint',
                    style: theme.textTheme.labelLarge,
                  ),
                ),
                IconButton(
                  onPressed: onRefreshAddresses,
                  tooltip: 'Refresh addresses',
                  icon: const Icon(Icons.refresh),
                ),
              ],
            ),
            if (!state.serviceRunning)
              const Text('Start the service to accept web clients.')
            else if (endpoints.isEmpty)
              const Text('No reachable IPv4 address found.')
            else
              ...endpoints.map(
                (endpoint) => Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: SelectableText(endpoint),
                ),
              ),
            const SizedBox(height: 12),
            Text('Temporary token', style: theme.textTheme.labelLarge),
            const SizedBox(height: 4),
            SelectableText(
              token.isEmpty ? 'Unavailable while service is stopped' : token,
              style: const TextStyle(fontFamily: 'monospace'),
            ),
            if (state.lastError != null) ...[
              const SizedBox(height: 12),
              Text(
                state.lastError!,
                style: TextStyle(color: theme.colorScheme.error),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _StatusRow extends StatelessWidget {
  const _StatusRow({
    required this.icon,
    required this.label,
    required this.value,
    required this.active,
  });

  final IconData icon;
  final String label;
  final String value;
  final bool active;

  @override
  Widget build(BuildContext context) {
    final color = active
        ? Theme.of(context).colorScheme.primary
        : Theme.of(context).colorScheme.outline;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        children: [
          Icon(icon, size: 20, color: color),
          const SizedBox(width: 10),
          Expanded(child: Text(label)),
          Text(value, style: TextStyle(color: color)),
        ],
      ),
    );
  }
}
