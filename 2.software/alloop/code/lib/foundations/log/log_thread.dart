import 'dart:io';
import 'dart:isolate';
import 'dart:async';
import 'dart:developer' as developer;

/// Log message data class.
class LogMessage {
  final String content;
  final String timestamp;
  final String logFilePath;

  LogMessage({
    required this.content,
    required this.timestamp,
    required this.logFilePath,
  });

  Map<String, dynamic> toJson() {
    return {
      'content': content,
      'timestamp': timestamp,
      'logFilePath': logFilePath,
    };
  }

  factory LogMessage.fromJson(Map<String, dynamic> json) {
    return LogMessage(
      content: json['content'],
      timestamp: json['timestamp'],
      logFilePath: json['logFilePath'],
    );
  }
}

/// Logging thread manager.
class LoggerThread {
  static LoggerThread? _instance;
  static LoggerThread get instance => _instance ??= LoggerThread._internal();

  LoggerThread._internal();

  Isolate? _logIsolate;
  SendPort? _sendPort;
  ReceivePort? _receivePort;
  bool _isInitialized = false;
  Completer<void>? _initCompleter;

  /// Initializes the logging thread.
  Future<void> initialize() async {
    if (_isInitialized) return;

    // If initialization is already in progress, wait for it to complete
    if (_initCompleter != null && !_initCompleter!.isCompleted) {
      return _initCompleter!.future;
    }

    // Create a new Completer
    _initCompleter = Completer<void>();

    try {
      // Clean up previous resources
      await _cleanup();

      // Create a new ReceivePort
      _receivePort = ReceivePort();

      // Start the logging thread
      _logIsolate = await Isolate.spawn(
        _logIsolateEntryPoint,
        _receivePort!.sendPort,
      );

      // Listen for the initialization message
      late StreamSubscription subscription;
      subscription = _receivePort!.listen((message) {
        if (message is SendPort) {
          _sendPort = message;
          _isInitialized = true;
          subscription.cancel(); // Cancel the listener to avoid duplicate listening
          if (!_initCompleter!.isCompleted) {
            _initCompleter!.complete();
          }
        } else if (message is String && message.startsWith('ERROR:')) {
          subscription.cancel();
          if (!_initCompleter!.isCompleted) {
            _initCompleter!.completeError(Exception(message));
          }
        }
      });
    } catch (e) {
      if (!_initCompleter!.isCompleted) {
        _initCompleter!.completeError(e);
      }
      rethrow;
    }

    return _initCompleter!.future;
  }

  /// Sends a log message to the thread.
  void sendLogMessage(LogMessage message) {
    if (_isInitialized && _sendPort != null) {
      _sendPort!.send(message.toJson());
    } else {
      // If the thread is not initialized, fall back to synchronous writing
      _fallbackWriteToFile(message);
    }
  }

  /// Fallback synchronous write method.
  void _fallbackWriteToFile(LogMessage message) {
    try {
      final file = File(message.logFilePath);

      // Ensure the directory exists
      final directory = file.parent;
      if (!directory.existsSync()) {
        directory.createSync(recursive: true);
      }

      final content = '${message.timestamp} ${message.content}\n';
      file.writeAsStringSync(content, mode: FileMode.append);
    } catch (e) {
      developer.log('Fallback write to file failed: $e', name: 'LoggerThread');
    }
  }

  /// Internal cleanup method.
  Future<void> _cleanup() async {
    if (_logIsolate != null) {
      _sendPort?.send('STOP');
      _logIsolate?.kill(priority: Isolate.immediate);
      _logIsolate = null;
    }
    _receivePort?.close();
    _receivePort = null;
    _sendPort = null;
  }

  /// Stops the logging thread.
  Future<void> dispose() async {
    await _cleanup();
    _isInitialized = false;
    _initCompleter = null;
  }

  /// Logging thread entry point.
  static void _logIsolateEntryPoint(SendPort mainSendPort) async {
    final receivePort = ReceivePort();

    // Send the SendPort back to the main thread
    mainSendPort.send(receivePort.sendPort);

    try {
      // Listen for messages from the main thread
      await for (final message in receivePort) {
        if (message == 'STOP') {
          break;
        } else if (message is Map<String, dynamic>) {
          try {
            final logMessage = LogMessage.fromJson(message);
            await _writeToFileInThread(logMessage);
          } catch (e) {
            // Handle errors inside the thread
            developer.log('Log thread write error: $e');
          }
        }
      }
    } catch (e) {
      mainSendPort.send('ERROR: $e');
    } finally {
      receivePort.close();
    }
  }

  /// Writes to a file inside the logging thread.
  static Future<void> _writeToFileInThread(LogMessage message) async {
    try {
      final file = File(message.logFilePath);

      // Ensure the directory exists
      final directory = file.parent;
      if (!await directory.exists()) {
        await directory.create(recursive: true);
      }

      // Write to the file
      final content = '${message.timestamp} ${message.content}\n';
      await file.writeAsString(content, mode: FileMode.append);
    } catch (e) {
      // Use print inside the thread since developer.log may be unavailable
      print('Write to file failed in thread: $e');
    }
  }
}
