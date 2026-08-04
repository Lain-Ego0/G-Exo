class BridgeState {
  const BridgeState({
    required this.serviceRunning,
    required this.webClientConnected,
    required this.ringConnected,
    required this.port,
    this.activeOperation,
    this.lastError,
  });

  const BridgeState.stopped()
    : serviceRunning = false,
      webClientConnected = false,
      ringConnected = false,
      port = 8766,
      activeOperation = null,
      lastError = null;

  final bool serviceRunning;
  final bool webClientConnected;
  final bool ringConnected;
  final int port;
  final String? activeOperation;
  final String? lastError;

  Map<String, dynamic> toJson() {
    return {
      'serviceRunning': serviceRunning,
      'webClientConnected': webClientConnected,
      'ringConnected': ringConnected,
      'port': port,
      'activeOperation': activeOperation,
      'lastError': lastError,
    };
  }
}
