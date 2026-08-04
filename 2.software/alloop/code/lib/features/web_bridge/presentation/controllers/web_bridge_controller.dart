import 'dart:async';
import 'dart:io';

import 'package:get/get.dart';

import '../../../../foundations/log/al_logger.dart';
import '../../data/bridge_server.dart';
import '../../domain/bridge_state.dart';

class WebBridgeController extends GetxController {
  WebBridgeController({BridgeServer? server})
    : _server = server ?? BridgeServer();

  final BridgeServer _server;
  final Rx<BridgeState> state = const BridgeState.stopped().obs;
  final RxList<String> localAddresses = <String>[].obs;
  final RxString token = ''.obs;
  final RxBool isUpdating = false.obs;
  StreamSubscription<BridgeState>? _stateSubscription;

  @override
  void onInit() {
    super.onInit();
    _stateSubscription = _server.stateStream.listen((value) {
      state.value = value;
      token.value = _server.token;
    });
    unawaited(refreshLocalAddresses());
  }

  Future<void> setServiceEnabled(bool enabled) async {
    if (isUpdating.value || enabled == _server.isRunning) return;
    isUpdating.value = true;
    try {
      if (enabled) {
        await _server.start();
        await refreshLocalAddresses();
      } else {
        await _server.stop();
      }
      state.value = _server.state;
      token.value = _server.token;
    } catch (error, stackTrace) {
      AlLogger.error(
        'Failed to update web bridge service',
        tag: 'WEB_BRIDGE',
        error: error,
        stackTrace: stackTrace,
      );
      state.value = _server.state;
    } finally {
      isUpdating.value = false;
    }
  }

  Future<void> refreshLocalAddresses() async {
    try {
      final interfaces = await NetworkInterface.list(
        type: InternetAddressType.IPv4,
        includeLoopback: false,
      );
      final addresses =
          interfaces
              .expand((interface) => interface.addresses)
              .map((address) => address.address)
              .where((address) => !address.startsWith('169.254.'))
              .toSet()
              .toList()
            ..sort();
      localAddresses.assignAll(addresses);
    } catch (error, stackTrace) {
      AlLogger.warning(
        'Failed to enumerate local addresses: $error',
        tag: 'WEB_BRIDGE',
        stackTrace: stackTrace,
      );
      localAddresses.clear();
    }
  }

  @override
  void onClose() {
    unawaited(_stateSubscription?.cancel());
    unawaited(_server.dispose());
    super.onClose();
  }
}
