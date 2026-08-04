import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import '../domain/bridge_message.dart';
import '../domain/bridge_state.dart';
import 'alloop_bridge_adapter.dart';
import 'bridge_rpc_router.dart';

typedef BridgeTokenGenerator = String Function();

class BridgeServer {
  BridgeServer({
    this.requestedPort = 8766,
    this.authenticationTimeout = const Duration(seconds: 5),
    InternetAddress? bindAddress,
    BridgeTokenGenerator? tokenGenerator,
    BridgeRingOperations? ringOperations,
    BridgeRpcRouter? router,
  }) : bindAddress = bindAddress ?? InternetAddress.anyIPv4,
       _tokenGenerator = tokenGenerator ?? _generateToken {
    _ringOperations = ringOperations ?? AlloopBridgeAdapter();
    _router =
        router ??
        BridgeRpcRouter(
          stateProvider: () => state,
          ringOperations: _ringOperations,
        );
    _ringEventSubscription = _ringOperations.events.listen(_handleRingEvent);
  }

  final int requestedPort;
  final Duration authenticationTimeout;
  final InternetAddress bindAddress;
  final BridgeTokenGenerator _tokenGenerator;
  late final BridgeRingOperations _ringOperations;
  late final BridgeRpcRouter _router;
  late final StreamSubscription<BridgeSdkEvent> _ringEventSubscription;

  final StreamController<BridgeState> _stateController =
      StreamController<BridgeState>.broadcast();
  HttpServer? _httpServer;
  WebSocket? _client;
  bool _clientAuthenticated = false;
  Timer? _authenticationTimer;
  String _token = '';
  String? _lastError;

  Stream<BridgeState> get stateStream => _stateController.stream;
  bool get isRunning => _httpServer != null;
  String get token => _token;
  int get port => _httpServer?.port ?? requestedPort;

  BridgeState get state => BridgeState(
    serviceRunning: isRunning,
    webClientConnected: _clientAuthenticated,
    ringConnected: _ringOperations.ringConnected,
    port: port,
    activeOperation: _ringOperations.activeOperation,
    lastError: _lastError,
  );

  Future<void> start() async {
    if (isRunning) return;

    _lastError = null;
    _token = _tokenGenerator();
    try {
      final server = await HttpServer.bind(bindAddress, requestedPort);
      _httpServer = server;
      server.listen(
        _handleHttpRequest,
        onError: (Object error, StackTrace stackTrace) {
          _lastError = error.toString();
          _emitState();
        },
      );
      _emitState();
    } catch (error) {
      _token = '';
      _lastError = error.toString();
      _emitState();
      rethrow;
    }
  }

  Future<void> stop() async {
    final client = _client;
    _client = null;
    _clientAuthenticated = false;
    _authenticationTimer?.cancel();
    _authenticationTimer = null;
    if (client != null) {
      await client.close(WebSocketStatus.goingAway, 'Bridge stopped');
    }

    final server = _httpServer;
    _httpServer = null;
    if (server != null) {
      await server.close(force: true);
    }
    _token = '';
    _emitState();
  }

  Future<void> dispose() async {
    await stop();
    await _ringEventSubscription.cancel();
    await _ringOperations.dispose();
    await _stateController.close();
  }

  Future<void> _handleHttpRequest(HttpRequest request) async {
    if (request.uri.path != '/ws' ||
        !WebSocketTransformer.isUpgradeRequest(request)) {
      request.response.statusCode = HttpStatus.notFound;
      await request.response.close();
      return;
    }

    if (_client != null) {
      request.response.statusCode = HttpStatus.conflict;
      request.response.write('Bridge already has a client');
      await request.response.close();
      return;
    }

    final socket = await WebSocketTransformer.upgrade(request);
    _client = socket;
    _clientAuthenticated = false;
    _authenticationTimer = Timer(authenticationTimeout, () {
      if (identical(_client, socket) && !_clientAuthenticated) {
        unawaited(
          socket.close(
            WebSocketStatus.policyViolation,
            'Authentication timed out',
          ),
        );
      }
    });
    socket.listen(
      (Object? data) => unawaited(_handleSocketMessage(socket, data)),
      onError: (Object error, StackTrace stackTrace) {
        _lastError = error.toString();
        _releaseClient(socket);
      },
      onDone: () => _releaseClient(socket),
      cancelOnError: true,
    );
  }

  Future<void> _handleSocketMessage(WebSocket socket, Object? data) async {
    BridgeRequest request;
    try {
      if (data is! String) {
        throw const BridgeProtocolException(
          code: 'BRIDGE_INVALID_REQUEST',
          message: 'Only JSON text messages are supported',
        );
      }
      request = BridgeRequest.fromJson(jsonDecode(data));
    } on FormatException {
      _send(
        socket,
        BridgeResponse.failure(
          null,
          code: 'BRIDGE_INVALID_JSON',
          message: 'Message is not valid JSON',
        ),
      );
      return;
    } on BridgeProtocolException catch (error) {
      _send(
        socket,
        BridgeResponse.failure(
          error.requestId,
          code: error.code,
          message: error.message,
        ),
      );
      return;
    }

    if (!_clientAuthenticated) {
      await _authenticate(socket, request);
      return;
    }

    final response = await _router.route(request);
    _send(socket, response);
    _emitState();
  }

  Future<void> _authenticate(WebSocket socket, BridgeRequest request) async {
    if (request.method != 'authenticate') {
      _send(
        socket,
        BridgeResponse.failure(
          request.id,
          code: 'BRIDGE_AUTH_REQUIRED',
          message: 'The first request must authenticate the client',
        ),
      );
      await socket.close(
        WebSocketStatus.policyViolation,
        'Authentication required',
      );
      return;
    }

    if (request.params['token'] != _token) {
      _send(
        socket,
        BridgeResponse.failure(
          request.id,
          code: 'BRIDGE_AUTH_FAILED',
          message: 'Invalid bridge token',
        ),
      );
      await socket.close(WebSocketStatus.policyViolation, 'Invalid token');
      return;
    }

    _clientAuthenticated = true;
    _authenticationTimer?.cancel();
    _authenticationTimer = null;
    _emitState();
    _send(
      socket,
      BridgeResponse.success(request.id, {
        'bridgeVersion': BridgeRpcRouter.bridgeVersion,
      }),
    );
    for (final event in _ringOperations.snapshotEvents) {
      _sendEvent(socket, event);
    }
  }

  void _send(WebSocket socket, BridgeResponse response) {
    if (socket.readyState == WebSocket.open) {
      socket.add(jsonEncode(response.toJson()));
    }
  }

  void _handleRingEvent(BridgeSdkEvent event) {
    _emitState();
    final client = _client;
    if (client != null && _clientAuthenticated) {
      _sendEvent(client, event);
    }
  }

  void _sendEvent(WebSocket socket, BridgeSdkEvent event) {
    if (socket.readyState == WebSocket.open) {
      socket.add(jsonEncode(event.toJson()));
    }
  }

  void _releaseClient(WebSocket socket) {
    if (!identical(_client, socket)) return;
    _client = null;
    _clientAuthenticated = false;
    _authenticationTimer?.cancel();
    _authenticationTimer = null;
    _emitState();
  }

  void _emitState() {
    if (!_stateController.isClosed) {
      _stateController.add(state);
    }
  }

  static String _generateToken() {
    final random = Random.secure();
    return random.nextInt(10000).toString().padLeft(4, '0');
  }
}
