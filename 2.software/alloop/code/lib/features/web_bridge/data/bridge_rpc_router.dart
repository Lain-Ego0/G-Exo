import 'package:alloop_blue_lite/alloop_blue_lite.dart';

import '../domain/bridge_message.dart';
import '../domain/bridge_state.dart';
import 'alloop_bridge_adapter.dart';

class BridgeRpcRouter {
  BridgeRpcRouter({
    required BridgeState Function() stateProvider,
    BridgeRingOperations? ringOperations,
    DateTime Function()? clock,
  }) : _stateProvider = stateProvider,
       _ringOperations = ringOperations,
       _clock = clock ?? DateTime.now;

  static const bridgeVersion = '1.0.0';

  final BridgeState Function() _stateProvider;
  final BridgeRingOperations? _ringOperations;
  final DateTime Function() _clock;

  Future<BridgeResponse> route(BridgeRequest request) async {
    switch (request.method) {
      case 'ping':
        return BridgeResponse.success(request.id, {
          'serverTime': _clock().toUtc().toIso8601String(),
          'bridgeVersion': bridgeVersion,
        });
      case 'getBridgeState':
        return BridgeResponse.success(request.id, _stateProvider().toJson());
      case 'startScan':
        return _run(request, () async {
          final timeoutMs = _optionalInt(request, 'timeoutMs');
          final nameFilter = _optionalString(request, 'nameFilter');
          if (timeoutMs != null && (timeoutMs < 1 || timeoutMs > 60000)) {
            throw _invalidParams(
              request,
              'timeoutMs must be between 1 and 60000',
            );
          }
          await _requireRingOperations(request).startScan(
            timeout: timeoutMs == null
                ? const Duration(seconds: 15)
                : Duration(milliseconds: timeoutMs),
            nameFilter: nameFilter,
          );
        });
      case 'stopScan':
        return _run(request, () => _requireRingOperations(request).stopScan());
      case 'connect':
        return _run(
          request,
          () => _requireRingOperations(
            request,
          ).connect(_requiredDeviceId(request)),
        );
      case 'disconnect':
        return _run(
          request,
          () => _requireRingOperations(
            request,
          ).disconnect(_requiredDeviceId(request)),
        );
      case 'getDeviceInfo':
        return _runResult(
          request,
          () => _requireRingOperations(
            request,
          ).getDeviceInfo(_requiredDeviceId(request)),
        );
      case 'startSpo2Verification':
        return _run(
          request,
          () => _requireRingOperations(
            request,
          ).startSpo2Verification(_requiredDeviceId(request)),
        );
      case 'stopMeasurement':
        return _run(
          request,
          () => _requireRingOperations(
            request,
          ).stopMeasurement(_requiredDeviceId(request)),
        );
      case 'syncHistory':
        return _run(
          request,
          () => _requireRingOperations(
            request,
          ).syncHistory(_requiredDeviceId(request)),
        );
      default:
        return BridgeResponse.failure(
          request.id,
          code: 'BRIDGE_METHOD_NOT_FOUND',
          message: 'Unknown method: ${request.method}',
        );
    }
  }

  Future<BridgeResponse> _run(
    BridgeRequest request,
    Future<void> Function() operation,
  ) async {
    try {
      await operation();
      return BridgeResponse.success(request.id, null);
    } on BridgeProtocolException catch (error) {
      return BridgeResponse.failure(
        request.id,
        code: error.code,
        message: error.message,
      );
    } on AlloopBlueLiteException catch (error) {
      return BridgeResponse.failure(
        request.id,
        code: error.code,
        message: error.message ?? error.code,
      );
    } catch (error) {
      return BridgeResponse.failure(
        request.id,
        code: 'BRIDGE_INTERNAL_ERROR',
        message: error.toString(),
      );
    }
  }

  Future<BridgeResponse> _runResult(
    BridgeRequest request,
    Future<Object?> Function() operation,
  ) async {
    try {
      return BridgeResponse.success(request.id, await operation());
    } on BridgeProtocolException catch (error) {
      return BridgeResponse.failure(
        request.id,
        code: error.code,
        message: error.message,
      );
    } on AlloopBlueLiteException catch (error) {
      return BridgeResponse.failure(
        request.id,
        code: error.code,
        message: error.message ?? error.code,
      );
    } catch (error) {
      return BridgeResponse.failure(
        request.id,
        code: 'BRIDGE_INTERNAL_ERROR',
        message: error.toString(),
      );
    }
  }

  BridgeRingOperations _requireRingOperations(BridgeRequest request) {
    final operations = _ringOperations;
    if (operations == null) {
      throw BridgeProtocolException(
        code: 'BRIDGE_INTERNAL_ERROR',
        message: 'Ring operations are unavailable',
        requestId: request.id,
      );
    }
    return operations;
  }

  String _requiredDeviceId(BridgeRequest request) {
    final value = request.params['deviceId'];
    if (value is! String || value.trim().isEmpty) {
      throw _invalidParams(request, 'deviceId must be a non-empty string');
    }
    return value;
  }

  int? _optionalInt(BridgeRequest request, String key) {
    final value = request.params[key];
    if (value == null) return null;
    if (value is! int) {
      throw _invalidParams(request, '$key must be an integer');
    }
    return value;
  }

  String? _optionalString(BridgeRequest request, String key) {
    final value = request.params[key];
    if (value == null) return null;
    if (value is! String) {
      throw _invalidParams(request, '$key must be a string');
    }
    final trimmed = value.trim();
    return trimmed.isEmpty ? null : trimmed;
  }

  BridgeProtocolException _invalidParams(
    BridgeRequest request,
    String message,
  ) => BridgeProtocolException(
    code: 'BRIDGE_INVALID_PARAMS',
    message: message,
    requestId: request.id,
  );
}
