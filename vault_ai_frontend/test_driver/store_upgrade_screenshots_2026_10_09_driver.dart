import 'dart:convert';
import 'dart:io';

import 'package:integration_test/integration_test_driver.dart';

Future<void> main() async {
  await integrationDriver(
    timeout: const Duration(minutes: 16),
    writeResponseOnFailure: true,
    responseDataCallback: (data) async {
      final path = Platform.environment['SVAULTAI_DEMO_REPORT'];
      if (path == null || path.isEmpty) {
        throw StateError('Demo report destination is required');
      }
      await File(path).writeAsString(
          const JsonEncoder.withIndent('  ').convert(data),
          flush: true);
    },
  );
}
