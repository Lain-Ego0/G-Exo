/// A Bluetooth device discovered while scanning.
class LiteDevice {
  const LiteDevice({required this.id, required this.name, required this.rssi});

  /// Stable device identifier used for `connect`/`disconnect`/etc.
  final String id;

  /// Advertised device name.
  final String name;

  /// Received signal strength indicator, in dBm.
  final int rssi;

  factory LiteDevice.fromMap(Map<dynamic, dynamic> map) {
    return LiteDevice(
      id: map['id'] as String,
      name: map['name'] as String,
      rssi: map['rssi'] as int,
    );
  }

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is LiteDevice && other.id == id && other.name == name && other.rssi == rssi);

  @override
  int get hashCode => Object.hash(id, name, rssi);

  @override
  String toString() => 'LiteDevice(id: $id, name: $name, rssi: $rssi)';
}
