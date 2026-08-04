import 'package:alloop_blue_lite/alloop_blue_lite.dart';

/// Repository for algorithm verification measurement data.
///
/// Wraps the AlloopBlueLite SDK's SpO2 verification operations and data
/// streams. Returns the SDK data types directly, with no conversion.
class AlgorithmVerifyRepository {
  final AlloopBlueLite _blue = AlloopBlueLite.instance;

  /// Starts an SpO2 algorithm verification measurement.
  ///
  /// Throws an [AlloopBlueLiteException] if the device is not ready or the
  /// command fails.
  Future<void> startSpo2Verification(String deviceId) {
    return _blue.startSpo2Verification(deviceId);
  }

  /// Stops the current algorithm verification measurement.
  ///
  /// Safe to call even when no measurement is running.
  Future<void> stopAlgorithmVerify(String deviceId) async {
    await _blue.stopMeasurement(deviceId);
  }

  /// SpO2 verification result stream.
  Stream<Spo2Result> spo2ResultStream(String deviceId) {
    return _blue.spo2ResultStream(deviceId);
  }

  /// PPG waveform data stream.
  Stream<PpgWave> ppgWaveStream(String deviceId) {
    return _blue.ppgWaveStream(deviceId);
  }

  /// ACC waveform data stream.
  Stream<AccWave> accStream(String deviceId) {
    return _blue.accStream(deviceId);
  }
}
