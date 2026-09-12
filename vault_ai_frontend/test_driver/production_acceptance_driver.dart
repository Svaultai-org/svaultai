import 'dart:io';

import 'package:integration_test/integration_test_driver_extended.dart';

Future<void> main() async {
  final outputDirectory = Directory(
    Platform.environment['SVAULTAI_ACCEPTANCE_SCREENSHOTS'] ??
        'build/acceptance-screenshots',
  );
  await outputDirectory.create(recursive: true);

  await integrationDriver(
    onScreenshot: (name, bytes, [args]) async {
      final file = File('${outputDirectory.path}/$name.png');
      await file.writeAsBytes(bytes, flush: true);
      return true;
    },
  );
}
