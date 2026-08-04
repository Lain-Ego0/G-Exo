import 'dart:async';

import 'package:alloop_blue_lite/alloop_blue_lite.dart';
import 'package:flutter/material.dart';
import 'package:get/get.dart';

import '../../../../foundations/ui/al_toast.dart';
import '../../../base/controller_base.dart';
import '../../data/scan_repository.dart';

/// Scan controller: manages the scan lifecycle, filtering, dedup/sort, and
/// isolation of already-connected devices.
class ScanController extends BaseController {
  static const List<String> defaultFilters = ['ring', 'alloop'];

  final ScanRepository _repository;

  final RxBool isScanning = false.obs;
  final RxList<LiteDevice> devices = <LiteDevice>[].obs;
  final RxList<LiteDevice> connectedDevices = <LiteDevice>[].obs;
  final RxList<String> filterTexts = <String>['ring', 'alloop'].obs;
  final TextEditingController filterController = TextEditingController(
    text: 'ring alloop',
  );

  StreamSubscription<LiteDevice>? _discoverySubscription;
  StreamSubscription<List<LiteDevice>>? _connectedDevicesSubscription;
  StreamSubscription<bool>? _scanningStateSubscription;

  ScanController({required ScanRepository repository})
    : _repository = repository;

  @override
  void onInit() {
    super.onInit();
    _bindConnectedDevices();
    _bindScanningState();
  }

  @override
  void onReady() {
    super.onReady();
    startScan();
  }

  @override
  void onClose() {
    _disposeSubscriptions();
    filterController.dispose();
    super.onClose();
  }

  void updateFilter(String value) {
    // Parse comma-separated or space-separated filter names
    final filters = value
        .split(RegExp(r'[,，\s]+'))
        .map((f) => f.trim())
        .where((f) => f.isNotEmpty)
        .toList();
    filterTexts.value = filters.isEmpty ? [] : filters;
  }

  Future<void> startScan() async {
    await stopScan();
    devices.clear();
    _listenToDiscoveryStream();

    try {
      await _repository.startScan(filters: filterTexts);
      isScanning.value = true;
      logInfo('Scan started with filters: ${filterTexts.join(", ")}');
    } catch (e) {
      isScanning.value = false;
      AlToast.showError('Scan failed: $e');
      logError('Failed to start scan', e);
      await _cancelDiscoverySubscription();
    }
  }

  Future<void> stopScan() async {
    await _cancelDiscoverySubscription();
    try {
      await _repository.stopScan();
    } catch (e) {
      logError('Failed to stop scan', e);
    }
    isScanning.value = _repository.isScanning;
  }

  bool _matchesFilter(LiteDevice device) {
    // If no filters, match all devices
    if (filterTexts.isEmpty) return true;

    final deviceName = device.name.toLowerCase();
    // Match if device name contains any of the filter keywords
    return filterTexts.any(
      (filter) => deviceName.contains(filter.toLowerCase()),
    );
  }

  bool _isConnected(LiteDevice device) {
    return connectedDevices.any((item) => item.id == device.id);
  }

  void _onDeviceDiscovered(LiteDevice device) {
    if (_isConnected(device)) return;
    if (!_matchesFilter(device)) return;

    // Dedup by device ID, update RSSI, and keep sorted by signal strength
    final index = devices.indexWhere((item) => item.id == device.id);
    if (index >= 0) {
      devices[index] = device;
    } else {
      devices.add(device);
    }
    devices.sort((a, b) => b.rssi.compareTo(a.rssi));
  }

  void _listenToDiscoveryStream() {
    _discoverySubscription?.cancel();
    _discoverySubscription = _repository.discoveryStream.listen(
      _onDeviceDiscovered,
    );
  }

  void _bindConnectedDevices() {
    _connectedDevicesSubscription?.cancel();
    _connectedDevicesSubscription = _repository.connectedDevicesStream.listen((
      items,
    ) {
      connectedDevices
        ..clear()
        ..addAll(items);
      _removeConnectedFromDiscovery();
    });
  }

  void _bindScanningState() {
    _scanningStateSubscription?.cancel();
    isScanning.value = _repository.isScanning;
    _scanningStateSubscription = _repository.scanningStateStream.listen((
      value,
    ) {
      isScanning.value = value;
    });
  }

  void _removeConnectedFromDiscovery() {
    if (connectedDevices.isEmpty || devices.isEmpty) return;
    final connectedIds = connectedDevices.map((d) => d.id).toSet();
    // Sectioned display in the UI: connected devices are excluded from scan results
    devices.removeWhere((device) => connectedIds.contains(device.id));
  }

  Future<void> _cancelDiscoverySubscription() async {
    await _discoverySubscription?.cancel();
    _discoverySubscription = null;
  }

  void _disposeSubscriptions() {
    _discoverySubscription?.cancel();
    _connectedDevicesSubscription?.cancel();
    _scanningStateSubscription?.cancel();
  }
}
