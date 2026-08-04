import 'package:get/get.dart';

import '../../data/scan_repository.dart';
import '../controllers/scan_controller.dart';

/// Scan page dependency injection: repository + controller
class ScanBinding extends Bindings {
  @override
  void dependencies() {
    Get.lazyPut(() => ScanRepository());
    Get.lazyPut(() => ScanController(repository: Get.find()));
  }
}
