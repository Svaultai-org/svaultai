import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('iOS release compiles out unused location permission strategies', () {
    final plist = File('ios/Runner/Info.plist').readAsStringSync();
    final podfile = File('ios/Podfile').readAsStringSync();
    final pubspec = File('pubspec.yaml').readAsStringSync();
    final dartSources = Directory('lib')
        .listSync(recursive: true)
        .whereType<File>()
        .where((file) => file.path.endsWith('.dart'))
        .map((file) => file.readAsStringSync())
        .join('\n');

    expect(plist, isNot(contains('NSLocationWhenInUseUsageDescription')));
    expect(plist, isNot(contains('NSLocationAlwaysUsageDescription')));
    expect(plist, isNot(contains('NSLocationAlwaysAndWhenInUseUsageDescription')));
    expect(dartSources, isNot(contains('Permission.location')));
    expect(pubspec, contains('enable-swift-package-manager: false'));
    expect(podfile, contains("'PERMISSION_LOCATION=0'"));
    expect(podfile, contains("'PERMISSION_LOCATION_WHENINUSE=0'"));
    expect(podfile, contains("'PERMISSION_LOCATION_ALWAYS=0'"));
  });
}
