import 'dart:async';

import 'package:alloop_blue_lite/alloop_blue_lite.dart';
import 'package:flutter/material.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:flutter_screenutil/flutter_screenutil.dart';
import 'package:get/get.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import 'foundations/error/al_error_handler.dart';
import 'foundations/log/al_logger.dart';
// Import route configuration
import 'foundations/navigation/al_routes.dart';

void main() async {
  // Use a Zone to capture all asynchronous errors
  runZonedGuarded(() async {
    // Ensure Flutter bindings are initialized (must be inside the Zone)
    WidgetsFlutterBinding.ensureInitialized();

    // Initialize the logging system
    await AlLogger.initialize();

    // Initialize the global error handler
    AlErrorHandler.initialize();

    // Load environment variable configuration
    try {
      await dotenv.load(fileName: ".env");
      AlLogger.info('Environment variables loaded successfully', tag: 'INIT');
    } catch (e) {
      AlLogger.warning('Failed to load .env file: $e', tag: 'INIT');
    }

    // Initialize the Alloop Blue Lite SDK
    try {
      await AlloopBlueLite.instance.initialize();
      AlLogger.info('AlloopBlueLite initialized successfully', tag: 'INIT');
    } catch (e) {
      AlLogger.error('Failed to initialize AlloopBlueLite: $e', tag: 'INIT');
    }

    // Enable screen wakelock to keep screen on while app is running
    await WakelockPlus.enable();
    AlLogger.info('Screen wakelock enabled', tag: 'INIT');

    runApp(AlloopApp());
  }, AlErrorHandler.onZoneError);
}

/// Root widget of the application.
class AlloopApp extends StatefulWidget {
  const AlloopApp({super.key});

  @override
  State<StatefulWidget> createState() => _AlloopAppState();
}

class _AlloopAppState extends State<AlloopApp> {
  late String _initialRoute;
  bool _initialized = false;

  @override
  void initState() {
    super.initState();
    // Initialize routing
    _initializeRoute();
  }

  Future<void> _initializeRoute() async {
    // Only resolve the route on the first initialization
    if (!_initialized) {
      _initialRoute = await _getInitialRoute();
      _initialized = true;
      // Rebuild after initialization
      if (mounted) {
        setState(() {});
      }
    }
  }

  Future<String> _getInitialRoute() async {
    try {
      // Initialize the core logging system (required at app startup)
      await AlLogger.initialize();
      AlLogger.info('SDK initialization completed', tag: 'INIT');
    } catch (e, stackTrace) {
      AlLogger.error(
        'Error during initialization',
        tag: 'INIT',
        error: e,
        stackTrace: stackTrace,
      );
    }
    return AlRoutes.splash;
  }

  @override
  Widget build(BuildContext context) {
    // Show a loading screen until initialization completes
    if (!_initialized) {
      return MaterialApp(
        home: Scaffold(body: Center(child: CircularProgressIndicator())),
      );
    }

    // Use ScreenUtil for screen adaptation
    return ScreenUtilInit(
      designSize: const Size(390, 844), // iPhone 14 Pro size as the design baseline
      minTextAdapt: true, // Adaptive font sizing
      splitScreenMode: true, // Support split-screen mode
      builder: (context, child) {
        return GetMaterialApp(
          // Basic app information
          title: 'Alloop',
          debugShowCheckedModeBanner: false,

          // Theme configuration
          theme: ThemeData(
            colorScheme: ColorScheme.fromSeed(
              seedColor: Colors.blue,
              brightness: Brightness.light,
            ),
            useMaterial3: true,

            // AppBar theme
            appBarTheme: const AppBarTheme(centerTitle: true, elevation: 0),

            // Button theme
            elevatedButtonTheme: ElevatedButtonThemeData(
              style: ElevatedButton.styleFrom(
                padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(8),
                ),
              ),
            ),

            outlinedButtonTheme: OutlinedButtonThemeData(
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(8),
                ),
              ),
            ),

            // Card theme
            cardTheme: CardThemeData(
              elevation: 2,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(12),
              ),
            ),
          ),

          // Route configuration - determined dynamically based on user state
          initialRoute: _initialRoute,
          getPages: AlPages.pages,

          // Default transition animation
          defaultTransition: Transition.rightToLeft,
          transitionDuration: const Duration(milliseconds: 300),

          // Enable logging (debug mode only)
          enableLog: true,
          logWriterCallback: (String text, {bool isError = false}) {
            if (isError) {
              debugPrint('GetX Error: $text');
            } else {
              debugPrint('GetX: $text');
            }
          },

          // Error handling
          unknownRoute: GetPage(
            name: '/unknown',
            page: () => const Scaffold(
              body: Center(
                child: Text('Page Not Found', style: TextStyle(fontSize: 24)),
              ),
            ),
          ),
        );
      },
    );
  }
}
