import 'package:alloop_blue_lite/alloop_blue_lite.dart';

/// Scan data repository: wraps AlloopBlueLite's scan and connection streams.
///
/// Exposes scan/connection streams and snapshots, and provides scan
/// start/stop with name filtering.
class ScanRepository {
  final AlloopBlueLite _blue = AlloopBlueLite.instance;

  Stream<LiteDevice> get discoveryStream => _blue.deviceDiscoveredStream;

  Stream<List<LiteDevice>> get connectedDevicesStream =>
      _blue.connectedDevicesStream;

  Stream<bool> get scanningStateStream => _blue.isScanningStream;

  bool get isScanning => _blue.isScanning;

  Future<void> startScan({
    required List<String> filters,
    Duration timeout = const Duration(seconds: 15),
  }) {
    // Lite API only supports a single name filter (not a list). When exactly
    // one keyword is configured we can push it down to the native scan for
    // an efficient filter. When zero or multiple keywords are configured,
    // native filtering can't express the intent (no filter, or an OR across
    // keywords), so we pass no native filter and let the native side return
    // everything; the full OR-across-keywords matching is always enforced
    // client-side (see ScanController).
    final normalizedFilters = filters
        .map((f) => f.trim())
        .where((f) => f.isNotEmpty)
        .toList();

    return _blue.startScan(
      timeout: timeout,
      nameFilter: normalizedFilters.length == 1 ? normalizedFilters.first : null,
    );
  }

  Future<void> stopScan() async {
    if (_blue.isScanning) {
      await _blue.stopScan();
    }
  }
}
