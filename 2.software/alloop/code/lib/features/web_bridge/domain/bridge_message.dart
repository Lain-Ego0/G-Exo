class BridgeRequest {
  const BridgeRequest({
    required this.id,
    required this.method,
    required this.params,
  });

  final String id;
  final String method;
  final Map<String, dynamic> params;

  factory BridgeRequest.fromJson(Object? value) {
    if (value is! Map) {
      throw const BridgeProtocolException(
        code: 'BRIDGE_INVALID_REQUEST',
        message: 'Request must be a JSON object',
      );
    }

    final id = value['id'];
    final method = value['method'];
    final params = value['params'];
    if (id is! String || id.isEmpty) {
      throw const BridgeProtocolException(
        code: 'BRIDGE_INVALID_REQUEST',
        message: 'id must be a non-empty string',
      );
    }
    if (method is! String || method.isEmpty) {
      throw BridgeProtocolException(
        code: 'BRIDGE_INVALID_REQUEST',
        message: 'method must be a non-empty string',
        requestId: id,
      );
    }
    if (params is! Map) {
      throw BridgeProtocolException(
        code: 'BRIDGE_INVALID_REQUEST',
        message: 'params must be an object',
        requestId: id,
      );
    }

    return BridgeRequest(
      id: id,
      method: method,
      params: Map<String, dynamic>.from(params),
    );
  }
}

class BridgeResponse {
  const BridgeResponse._({
    required this.id,
    required this.ok,
    this.result,
    this.error,
  });

  factory BridgeResponse.success(String id, Object? result) {
    return BridgeResponse._(id: id, ok: true, result: result);
  }

  factory BridgeResponse.failure(
    String? id, {
    required String code,
    required String message,
  }) {
    return BridgeResponse._(
      id: id,
      ok: false,
      error: BridgeRpcError(code: code, message: message),
    );
  }

  final String? id;
  final bool ok;
  final Object? result;
  final BridgeRpcError? error;

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'ok': ok,
      if (ok) 'result': result else 'error': error!.toJson(),
    };
  }
}

class BridgeRpcError {
  const BridgeRpcError({required this.code, required this.message});

  final String code;
  final String message;

  Map<String, dynamic> toJson() => {'code': code, 'message': message};
}

class BridgeProtocolException implements Exception {
  const BridgeProtocolException({
    required this.code,
    required this.message,
    this.requestId,
  });

  final String code;
  final String message;
  final String? requestId;

  @override
  String toString() => '$code: $message';
}
