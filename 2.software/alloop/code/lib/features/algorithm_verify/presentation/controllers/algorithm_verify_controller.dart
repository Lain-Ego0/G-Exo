import 'dart:async';

import 'package:alloop_blue_lite/alloop_blue_lite.dart';
import 'package:get/get.dart';
import 'package:intl/intl.dart';
import 'package:path/path.dart' as path;

import '../../../../core/utils/al_file_utils.dart';
import '../../../../core/utils/csv_file_writer.dart';
import '../../../../foundations/ui/al_toast.dart';
import '../../../../widgets/chart/realtime_line_chart.dart';
import '../../../base/controller_base.dart';
import '../../../common/presentation/controllers/device_status_controller.dart';
import '../../data/repositories/algorithm_verify_repository.dart';
import '../../domain/models/algorithm_verify_state.dart';

/// Algorithm verification controller (SpO2 verification + PPG/ACC waveforms).
///
/// Manages the measurement lifecycle, coordinates the SpO2 result stream, the
/// PPG waveform data stream (4 channels), and the ACC waveform data stream (3
/// axes), and supports exporting the collected data to CSV.
class AlgorithmVerifyController extends BaseController {
  final AlgorithmVerifyRepository _repository;
  final String deviceId;

  DeviceStatusController get _deviceStatusController =>
      Get.find<DeviceStatusController>();

  // Reactive state
  final Rx<AlgorithmVerifyState> state = AlgorithmVerifyState.idle.obs;
  final Rx<Spo2Result?> latestResult = Rx<Spo2Result?>(null);

  /// Display slots retaining the last received value per metric.
  ///
  /// SpO2-only and HR-only results arrive as separate events; binding the UI
  /// to [latestResult] alone makes each event blank out the other metric.
  /// Values outside the physiological range are placeholder/invalid readings
  /// (hr < 30, spo2 < 70) and are shown as "--" rather than as numbers.
  final RxnInt displaySpo2 = RxnInt();
  final RxnInt displayHr = RxnInt();
  final RxBool isSavingData = false.obs;

  /// PPG waveform data points, 4 channels: ledG / ledGAmb / ledRedAmb / ledIr, fed to RealTimeLineChart.
  final RxList<DataPoint> ppgPointsLedG = <DataPoint>[].obs;
  final RxList<DataPoint> ppgPointsLedGAmb = <DataPoint>[].obs;
  final RxList<DataPoint> ppgPointsLedRedAmb = <DataPoint>[].obs;
  final RxList<DataPoint> ppgPointsLedIr = <DataPoint>[].obs;

  /// ACC waveform data points, 3 axes: x / y / z, fed to RealTimeLineChart.
  final RxList<DataPoint> accPointsX = <DataPoint>[].obs;
  final RxList<DataPoint> accPointsY = <DataPoint>[].obs;
  final RxList<DataPoint> accPointsZ = <DataPoint>[].obs;

  /// Chart window duration (seconds).
  static const double chartWindowSeconds = 5.0;

  /// Fixed PPG sampling rate (Hz).
  static const double _ppgSampleRateHz = 100.0;

  /// Fixed ACC sampling rate (Hz).
  static const double _accSampleRateHz = 25.0;

  /// PPG captureTime sample-index base (anchored to the first packet so it corresponds to t≈0).
  int? _ppgCaptureTimeBase;

  /// ACC captureTime sample-index base (anchored to the first packet so it corresponds to t≈0).
  int? _accCaptureTimeBase;

  /// Cumulative received PPG sample count (fallback time base when captureTime is unavailable).
  int _ppgReceivedSampleCount = 0;

  /// Cumulative received ACC sample count (fallback time base when captureTime is unavailable).
  int _accReceivedSampleCount = 0;

  /// Maximum retained PPG samples, preventing unbounded growth during long measurements (covers ~20 minutes at ~100Hz).
  static const int _maxPpgSamples = 120000;

  /// Maximum retained ACC samples, preventing unbounded growth during long measurements (covers ~80 minutes at ~25Hz).
  static const int _maxAccSamples = 120000;

  StreamSubscription<Spo2Result>? _resultSubscription;
  StreamSubscription<PpgWave>? _ppgSubscription;
  StreamSubscription<AccWave>? _accSubscription;
  StreamSubscription<LiteConnectionState>? _connectionSubscription;

  /// Measurement start time (UTC), used as the time base for charts and CSV.
  DateTime? measurementStartTime;

  /// Collected SpO2 results (timestamp -> result), used for export.
  final Map<DateTime, Spo2Result> _resultsByTimestamp = <DateTime, Spo2Result>{};

  /// Collected PPG samples (relative seconds -> 4-channel values), used for export.
  final List<_PpgSampleRecord> _ppgSamples = <_PpgSampleRecord>[];

  /// Collected ACC samples (relative seconds -> x/y/z values), used for export.
  final List<_AccSampleRecord> _accSamples = <_AccSampleRecord>[];

  AlgorithmVerifyController({
    required this.deviceId,
    required AlgorithmVerifyRepository repository,
  }) : _repository = repository;

  @override
  void onInit() {
    super.onInit();
    // Listen to the global connection state; auto-stop the measurement on disconnect
    _connectionSubscription = _deviceStatusController.connectionStateStream
        .listen((connState) {
      if (connState.state == LiteConnectionStateValue.disconnected &&
          state.value.isVerifying) {
        _handleDisconnection();
      }
    });
  }

  @override
  void onClose() {
    _cleanup();
    _connectionSubscription?.cancel();
    super.onClose();
  }

  /// Starts a measurement.
  Future<void> startMeasurement() async {
    if (!state.value.canStart) {
      AlToast.showError('Measurement is already in progress');
      return;
    }

    _resetLatestData();
    state.value = AlgorithmVerifyState.verifying;
    measurementStartTime = DateTime.now().toUtc();

    try {
      await _repository.startSpo2Verification(deviceId);

      _subscribeToResults();
      _subscribeToPpg();
      _subscribeToAcc();

      logInfo('Started SpO2 measurement at $measurementStartTime');
      AlToast.showSuccess('Measurement started');
    } catch (e) {
      state.value = AlgorithmVerifyState.idle;
      measurementStartTime = null;
      await _cancelSubscriptions();
      AlToast.showError('Failed to start measurement: ${_describeError(e)}');
      logError('Failed to start measurement', e);
    }
  }

  /// Stops the measurement.
  Future<void> stopMeasurement() async {
    if (!state.value.canStop) {
      return;
    }

    state.value = AlgorithmVerifyState.stopping;

    try {
      await _repository.stopAlgorithmVerify(deviceId);
      await _cancelSubscriptions();

      state.value = AlgorithmVerifyState.idle;
      logInfo('Stopped SpO2 measurement');
      AlToast.showSuccess('Measurement stopped');
    } catch (e) {
      state.value = AlgorithmVerifyState.idle;
      await _cancelSubscriptions();
      AlToast.showError('Failed to stop measurement: ${_describeError(e)}');
      logError('Failed to stop measurement', e);
    }
  }

  /// Exports this measurement's data to CSV.
  Future<void> exportData() async {
    if (isSavingData.value) return;

    if (_resultsByTimestamp.isEmpty && _ppgSamples.isEmpty && _accSamples.isEmpty) {
      AlToast.showError('No data to export');
      return;
    }

    isSavingData.value = true;
    try {
      final baseDir = await AlFileUtils.getUserAccessibleDirectory();
      if (baseDir == null) {
        AlToast.showError('Failed to get file path');
        return;
      }
      final exportDir = path.join(baseDir.path, 'algorithm_verify');
      final timeStamp = DateFormat(
        'yyyy-MM-dd_HH-mm-ss',
      ).format(measurementStartTime ?? DateTime.now());
      final baseName = 'spo2_$timeStamp';

      final savedFiles = <String>[];

      if (_resultsByTimestamp.isNotEmpty) {
        final spo2Path = path.join(exportDir, '${baseName}_SpO2.csv');
        final writer = CsvFileWriter(
          filePath: spo2Path,
          headers: ['timestamp', 'spo2', 'hr', 'success', 'isVerified'],
        );
        await writer.initialize();
        final sortedEntries = _resultsByTimestamp.entries.toList()
          ..sort((a, b) => a.key.compareTo(b.key));
        for (final entry in sortedEntries) {
          final r = entry.value;
          writer.writeRow([
            entry.key.toIso8601String(),
            r.spo2?.toString() ?? '',
            r.hr?.toString() ?? '',
            r.success?.toString() ?? '',
            r.isVerified.toString(),
          ]);
        }
        await writer.close();
        savedFiles.add(spo2Path);
      }

      if (_ppgSamples.isNotEmpty) {
        final ppgPath = path.join(exportDir, '${baseName}_PPG.csv');
        final writer = CsvFileWriter(
          filePath: ppgPath,
          headers: ['elapsedSeconds', 'ledG', 'ledGAmb', 'ledRedAmb', 'ledIr'],
        );
        await writer.initialize();
        for (final sample in _ppgSamples) {
          writer.writeRow([
            sample.elapsedSeconds.toStringAsFixed(3),
            sample.ledG,
            sample.ledGAmb,
            sample.ledRedAmb,
            sample.ledIr,
          ]);
        }
        await writer.close();
        savedFiles.add(ppgPath);
      }

      if (_accSamples.isNotEmpty) {
        final accPath = path.join(exportDir, '${baseName}_ACC.csv');
        final writer = CsvFileWriter(
          filePath: accPath,
          headers: ['timestamp', 'x', 'y', 'z'],
        );
        await writer.initialize();
        for (final sample in _accSamples) {
          writer.writeRow([
            sample.elapsedSeconds.toStringAsFixed(3),
            sample.x,
            sample.y,
            sample.z,
          ]);
        }
        await writer.close();
        savedFiles.add(accPath);
      }

      AlToast.showSuccess('Saved ${savedFiles.length} file(s) to $exportDir');
      logInfo('Exported files: ${savedFiles.join(", ")}');
    } catch (e) {
      AlToast.showError('Failed to export data: $e');
      logError('Failed to export data', e);
    } finally {
      isSavingData.value = false;
    }
  }

  void _subscribeToResults() {
    _resultSubscription?.cancel();
    _resultSubscription = _repository.spo2ResultStream(deviceId).listen(
      (result) {
        latestResult.value = result;
        final spo2 = result.spo2;
        if (spo2 != null) {
          displaySpo2.value = (spo2 >= 70 && spo2 <= 100) ? spo2 : null;
        }
        final hr = result.hr;
        if (hr != null) {
          displayHr.value = (hr >= 30 && hr <= 199) ? hr : null;
        }
        final timestamp = DateTime.now().toUtc();
        _resultsByTimestamp[timestamp] = result;
        logInfo(
          'Received SpO2 result: spo2=${result.spo2}, hr=${result.hr}, '
          'isVerified=${result.isVerified}',
        );
      },
      onError: (Object error) {
        logError('SpO2 result stream error', error);
      },
    );
  }

  void _subscribeToPpg() {
    _ppgSubscription?.cancel();
    _ppgSubscription = _repository.ppgWaveStream(deviceId).listen(
      (wave) {
        final startTime = measurementStartTime;
        if (startTime == null) return;

        final sampleCount = wave.samples.length;
        if (sampleCount == 0) return;

        // Per-sample x step is fixed by the sampling rate (never wall-clock
        // packet arrival), so BLE jitter and variable packet sizes can't
        // distort the waveform. Prefer captureTime-derived sample sequence
        // (anchored so the first received sample sits at t≈0); fall back to
        // the cumulative count of received samples when captureTime is
        // unusable (<= 0).
        final firstSampleSequence =
            wave.captureTime > 0 ? wave.captureTime - (sampleCount - 1) : null;
        int? sequenceBase;
        if (firstSampleSequence != null) {
          _ppgCaptureTimeBase ??= firstSampleSequence;
          sequenceBase = _ppgCaptureTimeBase;
        }

        double elapsedForSample(int i) {
          if (firstSampleSequence != null && sequenceBase != null) {
            return (firstSampleSequence + i - sequenceBase) / _ppgSampleRateHz;
          }
          return (_ppgReceivedSampleCount + i) / _ppgSampleRateHz;
        }

        double lastElapsed = 0;
        for (var i = 0; i < sampleCount; i++) {
          final elapsed = elapsedForSample(i);
          lastElapsed = elapsed;
          final sample = wave.samples[i];
          ppgPointsLedG.add(DataPoint(elapsed, sample.ledG.toDouble()));
          ppgPointsLedGAmb.add(DataPoint(elapsed, sample.ledGAmb.toDouble()));
          ppgPointsLedRedAmb.add(DataPoint(elapsed, sample.ledRedAmb.toDouble()));
          ppgPointsLedIr.add(DataPoint(elapsed, sample.ledIr.toDouble()));
          _ppgSamples.add(
            _PpgSampleRecord(
              elapsedSeconds: elapsed,
              ledG: sample.ledG,
              ledGAmb: sample.ledGAmb,
              ledRedAmb: sample.ledRedAmb,
              ledIr: sample.ledIr,
            ),
          );
        }
        _ppgReceivedSampleCount += sampleCount;

        // Cap the retained export buffer so a long-running measurement can't
        // grow _ppgSamples unboundedly; drop the oldest samples beyond the cap.
        if (_ppgSamples.length > _maxPpgSamples) {
          _ppgSamples.removeRange(0, _ppgSamples.length - _maxPpgSamples);
        }

        // Trim old points outside the visible window (keep a little extra).
        final cutoff = lastElapsed - chartWindowSeconds - 1.0;
        for (final points in [
          ppgPointsLedG,
          ppgPointsLedGAmb,
          ppgPointsLedRedAmb,
          ppgPointsLedIr,
        ]) {
          while (points.isNotEmpty && points.first.x < cutoff) {
            points.removeAt(0);
          }
        }
      },
      onError: (Object error) {
        logError('PPG wave stream error', error);
      },
    );
  }

  void _subscribeToAcc() {
    _accSubscription?.cancel();
    _accSubscription = _repository.accStream(deviceId).listen(
      (wave) {
        final startTime = measurementStartTime;
        if (startTime == null) return;

        final sampleCount = wave.samples.length;
        if (sampleCount == 0) return;

        // Per-sample x step is fixed by the sampling rate (never wall-clock
        // packet arrival), so BLE jitter and variable packet sizes can't
        // distort the waveform. Prefer captureTime-derived sample sequence
        // (anchored so the first received sample sits at t≈0); fall back to
        // the cumulative count of received samples when captureTime is
        // unusable (<= 0).
        final firstSampleSequence =
            wave.captureTime > 0 ? wave.captureTime - (sampleCount - 1) : null;
        int? sequenceBase;
        if (firstSampleSequence != null) {
          _accCaptureTimeBase ??= firstSampleSequence;
          sequenceBase = _accCaptureTimeBase;
        }

        double elapsedForSample(int i) {
          if (firstSampleSequence != null && sequenceBase != null) {
            return (firstSampleSequence + i - sequenceBase) / _accSampleRateHz;
          }
          return (_accReceivedSampleCount + i) / _accSampleRateHz;
        }

        double lastElapsed = 0;
        for (var i = 0; i < sampleCount; i++) {
          final elapsed = elapsedForSample(i);
          lastElapsed = elapsed;
          final sample = wave.samples[i];
          accPointsX.add(DataPoint(elapsed, sample.x.toDouble()));
          accPointsY.add(DataPoint(elapsed, sample.y.toDouble()));
          accPointsZ.add(DataPoint(elapsed, sample.z.toDouble()));
          _accSamples.add(
            _AccSampleRecord(
              elapsedSeconds: elapsed,
              x: sample.x,
              y: sample.y,
              z: sample.z,
            ),
          );
        }
        _accReceivedSampleCount += sampleCount;

        // Cap the retained export buffer so a long-running measurement can't
        // grow _accSamples unboundedly; drop the oldest samples beyond the cap.
        if (_accSamples.length > _maxAccSamples) {
          _accSamples.removeRange(0, _accSamples.length - _maxAccSamples);
        }

        // Trim old points outside the visible window (keep a little extra).
        final cutoff = lastElapsed - chartWindowSeconds - 1.0;
        for (final points in [accPointsX, accPointsY, accPointsZ]) {
          while (points.isNotEmpty && points.first.x < cutoff) {
            points.removeAt(0);
          }
        }
      },
      onError: (Object error) {
        logError('ACC wave stream error', error);
      },
    );
  }

  void _resetLatestData() {
    latestResult.value = null;
    displaySpo2.value = null;
    displayHr.value = null;
    ppgPointsLedG.clear();
    ppgPointsLedGAmb.clear();
    ppgPointsLedRedAmb.clear();
    ppgPointsLedIr.clear();
    accPointsX.clear();
    accPointsY.clear();
    accPointsZ.clear();
    _resultsByTimestamp.clear();
    _ppgSamples.clear();
    _accSamples.clear();
    _ppgCaptureTimeBase = null;
    _accCaptureTimeBase = null;
    _ppgReceivedSampleCount = 0;
    _accReceivedSampleCount = 0;
  }

  /// Cleanup on device disconnect: only local cleanup (cancel subscriptions,
  /// reset state); no stop-measurement command is sent to the already-disconnected
  /// device (such a command would inevitably fail / be meaningless). This is kept
  /// distinct from the normal path where the user calls [stopMeasurement] while
  /// the device is still connected.
  void _handleDisconnection() {
    if (state.value.isVerifying) {
      logWarning('Device disconnected during verifying, cleaning up locally');
      unawaited(_cancelSubscriptions());
      state.value = AlgorithmVerifyState.idle;
      AlToast.showError('Device disconnected, verification stopped');
    }
  }

  Future<void> _cancelSubscriptions() async {
    await _resultSubscription?.cancel();
    await _ppgSubscription?.cancel();
    await _accSubscription?.cancel();
    _resultSubscription = null;
    _ppgSubscription = null;
    _accSubscription = null;
  }

  void _cleanup() {
    // If disposed while still measuring and the device is connected, best-effort
    // stop the measurement on the device before tearing down subscriptions, so
    // the device doesn't keep measuring after this page/controller is gone.
    if (state.value.isVerifying && _deviceStatusController.isConnected.value) {
      unawaited(
        _repository
            .stopAlgorithmVerify(deviceId)
            .catchError((Object e) => logError('Failed to stop measurement on dispose', e)),
      );
    }
    unawaited(_cancelSubscriptions());
  }

  String _describeError(Object error) {
    if (error is AlloopBlueLiteException) {
      return '${error.code}: ${error.message ?? ""}';
    }
    return error.toString();
  }
}

/// A single PPG sample export record (relative seconds + 4-channel values).
class _PpgSampleRecord {
  const _PpgSampleRecord({
    required this.elapsedSeconds,
    required this.ledG,
    required this.ledGAmb,
    required this.ledRedAmb,
    required this.ledIr,
  });

  final double elapsedSeconds;
  final int ledG;
  final int ledGAmb;
  final int ledRedAmb;
  final int ledIr;
}

/// A single ACC sample export record (relative seconds + x/y/z values).
class _AccSampleRecord {
  const _AccSampleRecord({
    required this.elapsedSeconds,
    required this.x,
    required this.y,
    required this.z,
  });

  final double elapsedSeconds;
  final int x;
  final int y;
  final int z;
}
