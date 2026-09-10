import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('iOS native sources do not declare collision-prone FileUtils class', () {
    final roots = <Directory>[
      Directory('ios'),
      Directory('native'),
    ];
    final declaration = RegExp(
      r'@(interface|implementation)\s+FileUtils\b|\bclass\s+FileUtils\b',
    );
    final offenders = <String>[];

    for (final root in roots.where((directory) => directory.existsSync())) {
      for (final entity in root.listSync(recursive: true, followLinks: false)) {
        if (entity is! File ||
            !RegExp(r'\.(h|m|mm|swift)$').hasMatch(entity.path)) {
          continue;
        }
        if (declaration.hasMatch(entity.readAsStringSync())) {
          offenders.add(entity.path);
        }
      }
    }

    expect(
      offenders,
      isEmpty,
      reason: 'Namespace generic Objective-C/Swift class names before linking.',
    );
  });

  test('file_picker stays on its namespaced iOS implementation', () {
    final lock = File('pubspec.lock').readAsStringSync();
    final match = RegExp(
      r'file_picker:\s+dependency:.*?version: "([^"]+)"',
      dotAll: true,
    ).firstMatch(lock);

    expect(match, isNotNull);
    expect(
      int.parse(match!.group(1)!.split('.').first),
      greaterThanOrEqualTo(10),
      reason: 'file_picker 8.x exports a generic iOS FileUtils class.',
    );
  });
}
