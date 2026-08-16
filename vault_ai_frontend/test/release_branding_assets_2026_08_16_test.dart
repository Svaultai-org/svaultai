import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Android launch assets use the canonical SVaultAI master', () async {
    final pubspec = await File('pubspec.yaml').readAsString();
    expect(
      pubspec,
      contains('image:            "assets/branding/vaultai-icon-1024.png"'),
    );
    expect(pubspec, contains('icon_background_color:      "#0F1115"'));

    for (final density in <String>[
      'mdpi',
      'hdpi',
      'xhdpi',
      'xxhdpi',
      'xxxhdpi'
    ]) {
      for (final prefix in <String>['drawable-', 'drawable-night-']) {
        for (final name in <String>['splash.png', 'android12splash.png']) {
          final asset = File('android/app/src/main/res/$prefix$density/$name');
          expect(await asset.exists(), isTrue, reason: asset.path);
          final bytes = await asset.readAsBytes();
          expect(bytes.take(8), [137, 80, 78, 71, 13, 10, 26, 10],
              reason: asset.path);
          // The stale stock Flutter marks were tiny, mostly-white generated
          // files (all under 15 KiB). Canonical shield renders exceed this at
          // every density, including mdpi.
          expect(bytes.length, greaterThan(20000), reason: asset.path);
        }
      }
    }

    for (final qualifier in <String>['', '-night', '-v21', '-night-v21']) {
      final xml = await File(
        'android/app/src/main/res/drawable$qualifier/launch_background.xml',
      ).readAsString();
      expect(xml, contains('@drawable/splash'), reason: qualifier);
    }
  });

  test('web manifest and shell contain SVaultAI branding, not placeholders',
      () async {
    final manifest = jsonDecode(await File('web/manifest.json').readAsString())
        as Map<String, dynamic>;
    expect(manifest['short_name'], 'SVaultAI');
    expect(manifest['background_color'], '#0F1115');
    expect(manifest['theme_color'], '#0F1115');
    final icons = (manifest['icons'] as List).cast<Map<String, dynamic>>();
    expect(icons.map((item) => item['src']), contains('icons/Icon-512.png'));
    expect(await File('web/icons/Icon-512.png').length(), greaterThan(20000));

    final index = await File('web/index.html').readAsString();
    expect(index, contains('<title>SVaultAI'));
    expect(index.toLowerCase(), isNot(contains('flutter demo')));
    expect(index.toLowerCase(), isNot(contains('flutter logo')));
  });
}
