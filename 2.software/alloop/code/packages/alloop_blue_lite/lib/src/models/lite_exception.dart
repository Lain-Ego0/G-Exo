/// Exception thrown by [AlloopBlueLite] when a native call fails.
///
/// Wraps the native error into a stable, plugin-owned type so callers never
/// need to depend on `PlatformException` directly.
class AlloopBlueLiteException implements Exception {
  const AlloopBlueLiteException(this.code, this.message);

  /// Stable machine-readable error code (e.g. "BUSY", "NOT_CONNECTED").
  final String code;

  /// Human-readable description of the failure.
  final String? message;

  @override
  String toString() => 'AlloopBlueLiteException($code, $message)';
}
