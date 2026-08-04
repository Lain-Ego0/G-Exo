/// A single PPG sample within a [PpgWave] packet.
class PpgSample {
  const PpgSample({
    required this.ledG,
    required this.ledGAmb,
    required this.ledRedAmb,
    required this.ledIr,
  });

  final int ledG;
  final int ledGAmb;
  final int ledRedAmb;
  final int ledIr;

  factory PpgSample.fromMap(Map<dynamic, dynamic> map) {
    return PpgSample(
      ledG: map['ledG'] as int,
      ledGAmb: map['ledGAmb'] as int,
      ledRedAmb: map['ledRedAmb'] as int,
      ledIr: map['ledIr'] as int,
    );
  }
}

/// A batch of PPG samples delivered together.
class PpgWave {
  const PpgWave({required this.packCount, required this.samples, required this.captureTime});

  /// Sequence counter used to detect dropped packets.
  final int packCount;

  final List<PpgSample> samples;

  /// Capture timestamp for this packet.
  final int captureTime;

  factory PpgWave.fromMap(Map<dynamic, dynamic> map) {
    final rawSamples = map['samples'] as List<dynamic>;
    return PpgWave(
      packCount: map['packCount'] as int,
      samples: rawSamples.map((e) => PpgSample.fromMap(e as Map<dynamic, dynamic>)).toList(),
      captureTime: map['captureTime'] as int,
    );
  }
}
