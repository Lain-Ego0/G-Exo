import 'dart:io';
import 'package:path_provider/path_provider.dart';
import 'package:alloop/foundations/log/al_logger.dart';

/// File Storage utility class
///
/// Provides unified file storage path management for Android and iOS
class AlFileUtils {
  AlFileUtils._();

  /// Get user-accessible storage directory
  ///
  /// Android: Returns external storage directory (/sdcard/Android/data/com.alloop.blue.test/files)
  ///          - Android 10+: No permission required (scoped storage)
  ///          - Android 9-: Requires WRITE_EXTERNAL_STORAGE permission
  ///
  /// iOS: Returns application documents directory (accessible via Files app)
  ///
  /// Returns null if unable to get directory
  static Future<Directory?> getUserAccessibleDirectory() async {
    try {
      if (Platform.isAndroid) {
        // Use external storage directory for Android
        // This returns /sdcard/Android/data/com.alloop.blue.test/files
        final directory = await getExternalStorageDirectory();
        if (directory != null) {
          AlLogger.debug(
            'Android external storage directory: ${directory.path}',
            tag: 'AlStorageUtils',
          );
        }
        return directory;
      } else if (Platform.isIOS) {
        // Use application documents directory for iOS
        // This is accessible via Files app
        final directory = await getApplicationDocumentsDirectory();
        AlLogger.debug(
          'iOS documents directory: ${directory.path}',
          tag: 'AlStorageUtils',
        );
        return directory;
      }
      return null;
    } catch (e, stackTrace) {
      AlLogger.error(
        'Failed to get user-accessible directory: $e',
        tag: 'AlStorageUtils',
        error: e,
        stackTrace: stackTrace,
      );
      return null;
    }
  }
}
