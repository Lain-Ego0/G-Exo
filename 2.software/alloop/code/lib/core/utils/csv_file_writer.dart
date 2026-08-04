import 'dart:async';
import 'dart:io';

import 'package:path/path.dart' as path;

import '../../foundations/log/al_logger.dart';

/// CSV file writer.
///
/// Writes sensor data to a CSV file in real time. Supports streaming writes,
/// automatic flushing, and file splitting.
class CsvFileWriter {
  final String filePath;
  final List<String> headers;
  final bool _includeHeader;
  final int maxRowsPerFile;
  IOSink? _sink;
  File? _file;
  bool _isClosed = false;
  int _rowsWritten = 0;
  int _currentFileIndex = 1;
  late String _baseFilePath;
  late String _fileExtension;
  final List<File> _allFiles = [];
  bool _isSplitting = false; // Flag to prevent concurrent splitting

  /// Creates a CSV writer.
  ///
  /// [filePath] output file path
  /// [headers] CSV header row
  /// [includeHeader] whether to include the header row, defaults to true
  /// [maxRowsPerFile] maximum rows per file, defaults to 1000000 (1 million rows)
  CsvFileWriter({
    required this.filePath,
    required this.headers,
    bool includeHeader = true,
    this.maxRowsPerFile = 1000000,
  }) : _includeHeader = includeHeader {
    // Parse the base file path and extension
    final pathWithoutExt = filePath.replaceAll(
      RegExp(r'\.csv$', caseSensitive: false),
      '',
    );
    _baseFilePath = pathWithoutExt;
    _fileExtension = '.csv';
  }

  /// Initializes the file and writes the header row.
  Future<void> initialize() async {
    if (_isClosed) {
      throw StateError('Cannot initialize closed writer');
    }

    try {
      await _createNewFile();
      AlLogger.info('CSV file writer initialized: $filePath');
    } catch (e) {
      AlLogger.error('Failed to initialize CSV file writer', error: e);
      rethrow;
    }
  }

  /// Creates a new file and writes the header row.
  Future<void> _createNewFile() async {
    // Ensure the directory exists
    final directory = Directory(path.dirname(_getCurrentFilePath()));
    if (!await directory.exists()) {
      await directory.create(recursive: true);
    }

    // Close the current file (if any) and add it to the list
    if (_sink != null) {
      await _sink!.flush();
      await _sink!.close();
      _sink = null; // Important: clear the sink reference
      // Add the current file to the list (first file or an already-split file)
      if (_file != null && !_allFiles.contains(_file)) {
        _allFiles.add(_file!);
      }
    }

    // Build the current file path
    final currentFilePath = _getCurrentFilePath();
    _file = File(currentFilePath);

    // Create the file and obtain a writer
    _sink = _file!.openWrite();

    // Write the header row (UTF-8 BOM for Excel compatibility)
    if (_includeHeader) {
      _sink!.write('﻿'); // UTF-8 BOM
      _sink!.writeln(headers.join(','));
    }

    AlLogger.info('Created CSV file part $_currentFileIndex: $currentFilePath');
  }

  /// Returns the current file path (including the index suffix).
  String _getCurrentFilePath() {
    if (_currentFileIndex == 1) {
      return filePath;
    }
    return '$_baseFilePath'
        '_part'
        '$_currentFileIndex'
        '$_fileExtension';
  }

  /// Writes a single row of data.
  void writeRow(List<dynamic> values) {
    // If a split is in progress, skip this write (the row is dropped, but this
    // avoids a concurrency conflict).
    if (_isSplitting) {
      return;
    }

    if (_isClosed || _sink == null) {
      AlLogger.warning('Cannot write to closed or uninitialized writer');
      return;
    }

    try {
      final csvLine = values.map(_escapeCsvField).join(',');
      _sink!.writeln(csvLine);
      _rowsWritten++;

      // Check whether the file needs to be split
      if (_rowsWritten >= maxRowsPerFile && !_isSplitting) {
        _performSplitSync();
      }
    } catch (e) {
      AlLogger.error('Failed to write CSV row', error: e);
    }
  }

  /// Performs the file split synchronously (directly on the writing thread).
  void _performSplitSync() {
    if (_isSplitting) {
      return;
    }

    _isSplitting = true;
    AlLogger.info('CSV file reached $_rowsWritten rows, splitting to new file');

    try {
      // Close the current sink and add the current file to the list
      if (_sink != null) {
        try {
          _sink!.flush();
          _sink!.close();
        } catch (e) {
          AlLogger.error('Error closing sink during split', error: e);
        }
        _sink = null;
      }

      if (_file != null && !_allFiles.contains(_file)) {
        _allFiles.add(_file!);
      }

      // Increment the index and reset the row counter
      _currentFileIndex++;
      _rowsWritten = 0;

      // Build the new file path
      final currentFilePath = _getCurrentFilePath();

      // Create a new File object and IOSink
      _file = File(currentFilePath);
      _sink = _file!.openWrite();

      // Write the header row
      if (_includeHeader) {
        _sink!.write('﻿'); // UTF-8 BOM
        _sink!.writeln(headers.join(','));
      }

      AlLogger.info(
        'Created CSV file part $_currentFileIndex: $currentFilePath',
      );
    } catch (e) {
      AlLogger.error('Failed to split CSV file', error: e);
    } finally {
      _isSplitting = false;
    }
  }

  /// Closes the file and ensures all data is flushed to disk.
  Future<void> close() async {
    if (_isClosed) return;

    try {
      if (_sink != null) {
        await _sink!.flush();
        await _sink!.close();
        _sink = null; // Clear the sink reference
      }
      _isClosed = true;

      // Ensure the last file is added to the list
      if (_file != null && !_allFiles.contains(_file)) {
        _allFiles.add(_file!);
      }

      final totalFiles = _allFiles.length;
      final totalRows = (totalFiles - 1) * maxRowsPerFile + _rowsWritten;

      AlLogger.info(
        'CSV file writer closed: $filePath, '
        'files created: $totalFiles, total rows written: $totalRows',
      );
    } catch (e) {
      AlLogger.error('Failed to close CSV file writer', error: e);
    }
  }

  /// Number of rows written to the current file.
  int get rowsWritten => _rowsWritten;

  /// Total number of rows written across all split files.
  int get totalRowsWritten {
    if (_allFiles.isEmpty) return _rowsWritten;
    return (_allFiles.length - 1) * maxRowsPerFile + _rowsWritten;
  }

  /// Total number of files generated.
  int get fileCount => _allFiles.length;

  /// Escapes a CSV field.
  String _escapeCsvField(dynamic value) {
    final str = value?.toString() ?? '';

    // Escape if the value contains a comma, newline, or double quote
    if (str.contains(',') || str.contains('\n') || str.contains('"')) {
      final escaped = str.replaceAll('"', '""');
      return '"$escaped"';
    }

    return str;
  }
}
