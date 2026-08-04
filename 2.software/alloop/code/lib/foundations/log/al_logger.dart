import 'dart:io';
import 'dart:developer' as developer;
import 'dart:async';
import 'dart:convert';
import 'package:alloop/foundations/log/log_thread.dart';
import 'package:flutter/foundation.dart';
import 'package:logger/logger.dart';
import 'package:path_provider/path_provider.dart';

/// Logging manager.
/// Wraps logger 2.5.0 to provide a unified logging API.
///
/// Features:
/// - Logs of all levels are printed to the console
/// - Logs at info level and above are also written to a local file
/// - Local log files are named by "date + seq", with each file ≤ 20 MB
/// - After a segment is closed, it is gzip-compressed asynchronously to disk
/// - Log files older than 7 days are cleaned up automatically (both .log and
///   .log.gz)
/// - A dedicated logging thread performs asynchronous file writes
///
/// Storage location:
/// - Android: `/sdcard/Android/data/<pkg>/files/logs` (no root required, can be
///   viewed in a file manager); falls back to internal `app_flutter/logs/` when
///   external storage is unavailable
/// - iOS: `<documents>/logs` (accessible from the Files app)
class AlLogger {
  static Logger? _logger;
  static String? _logDirectory;
  static File? _currentLogFile;
  static String? _currentLogDate;
  static int _currentLogSeq = 1;
  static int _currentFileBytes = 0;
  static bool _isInitialized = false;
  static LoggerThread? _loggerThread;
  static Completer<void>? _initializationCompleter;

  /// Per-segment size threshold. Once exceeded, the segment is closed and a new
  /// one is started.
  static const int _maxLogFileBytes = 20 * 1024 * 1024;

  /// Private constructor.
  AlLogger._();

  /// Initializes the logging system.
  ///
  /// This is the public initialization method and should be called at app
  /// startup. If it is not called, initialization happens automatically on the
  /// first log call.
  static Future<void> initialize() async {
    if (_isInitialized) return;

    // If initialization is already in progress, wait for it to complete
    if (_initializationCompleter != null &&
        !_initializationCompleter!.isCompleted) {
      return _initializationCompleter!.future;
    }

    // Create the initialization Completer
    _initializationCompleter = Completer<void>();

    try {
      // Initialize the logging thread
      _loggerThread = LoggerThread.instance;
      await _loggerThread!.initialize();

      // Choose the log root directory:
      // - Android: prefer external storage (/sdcard/Android/data/<pkg>/files/logs)
      //   so it can be viewed from a file manager without root; fall back to
      //   internal documents when unavailable.
      // - iOS: use documents (visible in the Files app).
      Directory? baseDir;
      if (Platform.isAndroid) {
        try {
          baseDir = await getExternalStorageDirectory();
        } catch (e) {
          developer.log(
            'getExternalStorageDirectory failed, falling back to documents: $e',
            name: 'AlLogger',
          );
          baseDir = null;
        }
      }
      baseDir ??= await getApplicationDocumentsDirectory();
      _logDirectory = '${baseDir.path}/logs';

      // Create the log directory
      final Directory logDir = Directory(_logDirectory!);
      if (!await logDir.exists()) {
        await logDir.create(recursive: true);
      }

      // Initialize the current log file
      await _initializeCurrentLogFile();

      // Create the Logger instance.
      // Note: ProductionFilter must be specified explicitly. Otherwise the
      // default DevelopmentFilter relies on assert() to decide shouldLog, and
      // asserts are stripped in release builds, which would drop all logs and
      // leave the log file at 0 KB.
      _logger = Logger(
        filter: ProductionFilter(),
        printer: _AlLoggerPrinter(),
        output: _AlLoggerOutput(),
        level: Level.debug, // Set the minimum log level
      );

      // Clean up expired log files
      await _cleanupOldLogs();

      // Re-compress orphan plaintext segments left by a previous crash (any
      // .log other than the currently active segment)
      unawaited(_compressOrphanLogs());

      _isInitialized = true;
      _initializationCompleter!.complete();

      developer.log(
        'AlLogger initialized successfully with thread support',
        name: 'AlLogger',
      );
    } catch (e) {
      developer.log('Failed to initialize AlLogger: $e', name: 'AlLogger');
      // If initialization fails, create a simple console-only Logger
      _logger = Logger(
        filter: ProductionFilter(),
        printer: _AlLoggerPrinter(),
        output: ConsoleOutput(),
      );
      _isInitialized = true;
      _initializationCompleter!.complete();
    }
  }

  /// Ensures initialization has run (internal use).
  static Future<void> _ensureInitialized() async {
    if (!_isInitialized) {
      await initialize();
    }
  }

  /// Finds the largest existing seq for [date]; returns 0 if none exist.
  static int _findMaxSeqForDate(String date) {
    if (_logDirectory == null) return 0;
    final logDir = Directory(_logDirectory!);
    if (!logDir.existsSync()) return 0;
    final pattern = RegExp(r'^app_' + RegExp.escape(date) + r'_(\d+)\.log$');
    int max = 0;
    for (final f in logDir.listSync()) {
      if (f is! File) continue;
      final name = f.uri.pathSegments.last;
      final m = pattern.firstMatch(name);
      if (m == null) continue;
      final seq = int.tryParse(m.group(1)!);
      if (seq != null && seq > max) max = seq;
    }
    return max;
  }

  /// Initializes the current log file.
  ///
  /// Segment naming: `app_<date>_<seq>.log`, where seq is zero-padded to three
  /// digits so lexical order matches chronological order. A cold start scans
  /// the directory for the largest seq of the day; if that file already exceeds
  /// the threshold, it increments by 1 and opens a new segment.
  static Future<void> _initializeCurrentLogFile() async {
    final String today = DateTime.now().toIso8601String().split('T')[0];

    if (_currentLogDate == today && _currentLogFile != null) return;

    _currentLogDate = today;

    int seq = _findMaxSeqForDate(today);
    if (seq < 1) seq = 1;

    String filePath = _buildLogPath(today, seq);
    File file = File(filePath);
    int existingSize = 0;
    if (await file.exists()) {
      try {
        existingSize = await file.length();
      } catch (e) {
        developer.log(
          'Failed to get size of $filePath: $e',
          name: 'AlLogger',
        );
        existingSize = 0;
      }
      if (existingSize >= _maxLogFileBytes) {
        // The previous segment is full — close it (gzip) and open a new one
        unawaited(_gzipAndRemove(filePath));
        seq += 1;
        filePath = _buildLogPath(today, seq);
        file = File(filePath);
        existingSize = 0;
      }
    }

    if (!await file.exists()) {
      await file.create(recursive: true);
    }

    _currentLogSeq = seq;
    _currentLogFile = file;
    _currentFileBytes = existingSize;
  }

  static String _buildLogPath(String date, int seq) {
    final seqStr = seq.toString().padLeft(3, '0');
    return '$_logDirectory/app_${date}_$seqStr.log';
  }

  /// Returns the current log file, rotating segments as needed.
  ///
  /// Before writing, the caller passes the approximate byte count about to be
  /// written; when the accumulator reaches the threshold, the current segment
  /// is closed and a new one is opened. The byte count is estimated from the
  /// UTF-8 length; a few KB of drift does not affect correctness.
  static Future<File?> _getCurrentLogFile(
    String timestamp, {
    int incomingBytes = 0,
  }) async {
    final String today = timestamp.split('T')[0];

    // Run full initialization on day rollover or first use
    if (_currentLogDate != today || _currentLogFile == null) {
      await _initializeCurrentLogFile();
    }

    // Within the same day, rotate by size
    if (_currentFileBytes + incomingBytes >= _maxLogFileBytes) {
      await _rotateToNextSeq();
    }

    return _currentLogFile;
  }

  /// Closes the current segment, opens the next one, and gzips the old file
  /// asynchronously.
  static Future<void> _rotateToNextSeq() async {
    final old = _currentLogFile;
    final today =
        _currentLogDate ?? DateTime.now().toIso8601String().split('T')[0];
    final nextSeq = _currentLogSeq + 1;
    final nextPath = _buildLogPath(today, nextSeq);
    final nextFile = File(nextPath);
    if (!await nextFile.exists()) {
      await nextFile.create(recursive: true);
    }
    _currentLogSeq = nextSeq;
    _currentLogFile = nextFile;
    _currentFileBytes = 0;
    if (old != null) {
      unawaited(_gzipAndRemove(old.path));
    }
  }

  /// Async gzip: writes .log.gz first, then deletes the original .log only
  /// after verifying it landed on disk.
  ///
  /// The gzip runs in a [compute] isolate (streaming, peak memory a few MB) and
  /// does not block the main thread. A crash mid-way only leaves an incomplete
  /// .log.gz; on startup [_compressOrphanLogs] re-compresses it — the original
  /// .log is deleted only **after gzip verification passes**, so a crash never
  /// loses content.
  static Future<void> _gzipAndRemove(String logPath) async {
    try {
      final gzPath = '$logPath.gz';
      // Overwrite any incomplete .gz left by a crash mid-gzip
      final gz = File(gzPath);
      if (await gz.exists()) {
        try {
          await gz.delete();
        } catch (_) {}
      }
      final ok = await compute<_GzipReq, bool>(
        _gzipFileEntry,
        _GzipReq(logPath, gzPath),
      );
      if (ok && await gz.exists() && await gz.length() > 0) {
        try {
          await File(logPath).delete();
        } catch (_) {}
      }
    } catch (e) {
      developer.log('Failed to gzip $logPath: $e', name: 'AlLogger');
    }
  }

  /// On startup, scans remaining .log files (other than the active segment) and
  /// re-compresses each one.
  ///
  /// Covers three failure cases:
  /// 1. An old .log that wasn't compressed after a day rollover
  /// 2. The process was killed mid-gzip (incomplete .log.gz → re-compress
  ///    overwrites it)
  /// 3. gzip completed but the process was killed before delete (.log and
  ///    .log.gz coexist → re-compress, then delete the .log)
  static Future<void> _compressOrphanLogs() async {
    if (_logDirectory == null) return;
    try {
      final logDir = Directory(_logDirectory!);
      if (!await logDir.exists()) return;
      final activePath = _currentLogFile?.path;
      final entries = await logDir.list().toList();
      for (final f in entries) {
        if (f is! File) continue;
        final p = f.path;
        if (!p.endsWith('.log')) continue;
        if (p == activePath) continue;
        await _gzipAndRemove(p);
      }
    } catch (e) {
      developer.log(
        'Failed to compress orphan logs: $e',
        name: 'AlLogger',
      );
    }
  }

  /// Cleans up log files older than 7 days (both .log and .log.gz).
  static Future<void> _cleanupOldLogs() async {
    if (_logDirectory == null) return;

    try {
      final Directory logDir = Directory(_logDirectory!);
      if (!await logDir.exists()) return;

      final DateTime cutoffDate = DateTime.now().subtract(
        const Duration(days: 7),
      );
      final List<FileSystemEntity> files = await logDir.list().toList();

      for (final FileSystemEntity file in files) {
        if (file is! File) continue;
        final p = file.path;
        if (!p.endsWith('.log') && !p.endsWith('.log.gz')) continue;
        final FileStat stat = await file.stat();
        if (stat.modified.isBefore(cutoffDate)) {
          await file.delete();
          developer.log(
            'Deleted old log file: ${file.path}',
            name: 'AlLogger',
          );
        }
      }
    } catch (e) {
      developer.log('Failed to cleanup old logs: $e', name: 'AlLogger');
    }
  }

  // ==================== Public API ====================

  /// Debug-level log - console output only.
  static void debug(
    String message, {
    String? tag,
    dynamic error,
    StackTrace? stackTrace,
  }) async {
    await _ensureInitialized();
    final String logTag = tag != null ? '[$tag][D] ' : '[D] ';
    _logger?.d('$logTag$message', error: error, stackTrace: stackTrace);
  }

  /// Info-level log - console + file output.
  static void info(
    String message, {
    String? tag,
    dynamic error,
    StackTrace? stackTrace,
  }) async {
    await _ensureInitialized();
    final String logTag = tag != null ? '[$tag][I] ' : '[I] ';
    _logger?.i('$logTag$message', error: error, stackTrace: stackTrace);
  }

  /// Warning-level log - console + file output.
  static void warning(
    String message, {
    String? tag,
    dynamic error,
    StackTrace? stackTrace,
  }) async {
    await _ensureInitialized();
    final String logTag = tag != null ? '[$tag][!!!!W!!!!] ' : '[W] ';
    _logger?.w('$logTag$message', error: error, stackTrace: stackTrace);
  }

  /// Error-level log - console + file output.
  static void error(
    String message, {
    String? tag,
    dynamic error,
    StackTrace? stackTrace,
  }) async {
    await _ensureInitialized();
    final String logTag = tag != null ? '[$tag][****Error****] ' : '[E] ';
    _logger?.e('$logTag$message', error: error, stackTrace: stackTrace);
  }

  /// Manually cleans up expired logs.
  static Future<void> cleanupLogs() async {
    await _ensureInitialized();
    await _cleanupOldLogs();
  }

  /// Returns the log directory path.
  static Future<String?> getLogDirectory() async {
    await _ensureInitialized();
    return _logDirectory;
  }

  /// Returns the list of all log files (both .log and .log.gz).
  static Future<List<File>> getLogFiles() async {
    await _ensureInitialized();
    if (_logDirectory == null) return [];

    try {
      final Directory logDir = Directory(_logDirectory!);
      if (!await logDir.exists()) return [];

      final List<FileSystemEntity> files = await logDir.list().toList();
      return files
          .whereType<File>()
          .where((file) =>
              file.path.endsWith('.log') || file.path.endsWith('.log.gz'))
          .toList();
    } catch (e) {
      developer.log('Failed to get log files: $e', name: 'AlLogger');
      return [];
    }
  }

  /// Releases the logging system's resources.
  static Future<void> dispose() async {
    if (_loggerThread != null) {
      await _loggerThread!.dispose();
      _loggerThread = null;
    }
    _isInitialized = false;
    developer.log('AlLogger disposed', name: 'AlLogger');
  }
}

/// Custom log printer.
class _AlLoggerPrinter extends LogPrinter {
  @override
  List<String> log(LogEvent event) {
    // Return the message content directly, keeping the "[$logTag] $message" format
    final String message = event.message.toString();

    // If there is error information, append it after the message
    if (event.error != null) {
      return [
        message,
        'Error: ${event.error}',
        if (event.stackTrace != null) 'StackTrace: ${event.stackTrace}',
      ];
    }

    return [message];
  }
}

/// Custom log output.
class _AlLoggerOutput extends LogOutput {
  @override
  void output(OutputEvent event) {
    // Output all levels to the console
    for (final String line in event.lines) {
      if (kDebugMode) {
        print(line);
      }
    }

    // Also write info level and above to the file
    if (event.level.index >= Level.info.index) {
      _writeToFile(event);
    }
  }

  /// Writes to the file (asynchronous, thread-based version).
  Future<void> _writeToFile(OutputEvent event) async {
    try {
      final String timestamp = DateTime.now().toIso8601String();

      // Estimate this log entry's byte count (via UTF-8 length) for the
      // rotation decision. A few KB of drift is negligible against the 20 MB
      // threshold.
      final StringBuffer buffer = StringBuffer();
      for (final String line in event.lines) {
        buffer.writeln(line);
      }
      final String content = buffer.toString().trim();
      // Approximate total length of `<timestamp> <content>\n`
      final int approxBytes = utf8.encode(timestamp).length +
          1 +
          utf8.encode(content).length +
          1;

      final File? logFile = await AlLogger._getCurrentLogFile(
        timestamp,
        incomingBytes: approxBytes,
      );
      if (logFile == null) return;

      final logMessage = LogMessage(
        content: content,
        timestamp: timestamp,
        logFilePath: logFile.path,
      );

      AlLogger._currentFileBytes += approxBytes;

      // Send to the logging thread for asynchronous writing
      if (AlLogger._loggerThread != null) {
        AlLogger._loggerThread!.sendLogMessage(logMessage);
      } else {
        // Fall back to synchronous writing
        logFile.writeAsStringSync(
          '$timestamp ${logMessage.content}\n',
          mode: FileMode.append,
        );
      }
    } catch (e) {
      developer.log('Failed to write log to file: $e', name: 'AlLogger');
    }
  }
}

/// Input parameters for the gzip compute call.
class _GzipReq {
  final String logPath;
  final String gzPath;
  const _GzipReq(this.logPath, this.gzPath);
}

/// Top-level function — must be top-level to be used with [compute].
///
/// Note: [Stream.pipe] only closes the consumer on the success path; an error
/// mid-way does not close the sink and leaks a file descriptor. This uses
/// try/finally as a safeguard (IOSink.close is idempotent, so repeated calls
/// have no side effects).
Future<bool> _gzipFileEntry(_GzipReq r) async {
  final src = File(r.logPath);
  if (!await src.exists()) return false;
  final sink = File(r.gzPath).openWrite();
  try {
    await src.openRead().transform(gzip.encoder).pipe(sink);
    return true;
  } catch (_) {
    return false;
  } finally {
    await sink.close();
  }
}
