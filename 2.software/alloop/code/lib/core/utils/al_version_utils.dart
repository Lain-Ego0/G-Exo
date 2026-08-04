import 'package:package_info_plus/package_info_plus.dart';

/// Version information utility class
///
/// Provides unified access to app version information using package_info_plus.
class AlVersionUtils {
  AlVersionUtils._();

  static PackageInfo? _cachedPackageInfo;

  /// Get package info (cached)
  ///
  /// Returns the PackageInfo object containing version, buildNumber, etc.
  /// The result is cached after first call for performance.
  static Future<PackageInfo> getPackageInfo() async {
    _cachedPackageInfo ??= await PackageInfo.fromPlatform();
    return _cachedPackageInfo!;
  }

  /// Get app version string (e.g., "1.0.0")
  static Future<String> getVersion() async {
    final info = await getPackageInfo();
    return info.version;
  }

  /// Get formatted version string (e.g., "v1.0.0 (42)")
  ///
  /// [includeBuildNumber] - whether to include build number in parentheses
  static Future<String> getFormattedVersion({
    bool includeBuildNumber = true,
  }) async {
    final info = await getPackageInfo();
    if (includeBuildNumber) {
      return 'v${info.version} (${info.buildNumber})';
    }
    return 'v${info.version}';
  }

  /// Get version string for display (e.g., "Version 1.0.0")
  ///
  /// Suitable for splash screens and about dialogs.
  static Future<String> getDisplayVersion() async {
    final version = await getVersion();
    return 'Version $version';
  }
}
