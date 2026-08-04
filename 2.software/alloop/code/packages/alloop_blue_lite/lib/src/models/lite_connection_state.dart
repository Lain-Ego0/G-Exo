/// Connection lifecycle state of a device.
enum LiteConnectionStateValue { connecting, connected, disconnected }

/// A connection state change event for a specific device.
class LiteConnectionState {
  const LiteConnectionState({required this.state, this.errorCode});

  final LiteConnectionStateValue state;

  /// Present when [state] is [LiteConnectionStateValue.disconnected] due to
  /// an error.
  final String? errorCode;

  factory LiteConnectionState.fromMap(Map<dynamic, dynamic> map) {
    return LiteConnectionState(
      state: _parseState(map['state'] as String),
      errorCode: map['errorCode'] as String?,
    );
  }

  static LiteConnectionStateValue _parseState(String value) {
    switch (value) {
      case 'connecting':
        return LiteConnectionStateValue.connecting;
      case 'connected':
        return LiteConnectionStateValue.connected;
      case 'disconnected':
        return LiteConnectionStateValue.disconnected;
      default:
        throw ArgumentError.value(value, 'state', 'Unknown connection state');
    }
  }

  @override
  String toString() => 'LiteConnectionState(state: $state, errorCode: $errorCode)';
}
