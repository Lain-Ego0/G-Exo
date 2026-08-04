/// A single accelerometer sample within an [AccWave] packet.
class AccSample3 {
  const AccSample3({required this.x, required this.y, required this.z});

  final int x;
  final int y;
  final int z;

  factory AccSample3.fromMap(Map<dynamic, dynamic> map) {
    return AccSample3(
      x: map['x'] as int,
      y: map['y'] as int,
      z: map['z'] as int,
    );
  }
}

/// A batch of accelerometer samples delivered together.
class AccWave {
  const AccWave({required this.packCount, required this.samples, required this.captureTime});

  /// Sequence counter used to detect dropped packets.
  final int packCount;

  final List<AccSample3> samples;

  /// Capture timestamp for this packet.
  final int captureTime;

  factory AccWave.fromMap(Map<dynamic, dynamic> map) {
    final rawSamples = map['samples'] as List<dynamic>;
    return AccWave(
      packCount: map['packCount'] as int,
      samples: rawSamples.map((e) => AccSample3.fromMap(e as Map<dynamic, dynamic>)).toList(),
      captureTime: map['captureTime'] as int,
    );
  }
}
